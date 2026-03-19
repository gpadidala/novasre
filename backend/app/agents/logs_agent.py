"""
NovaSRE — Logs Agent (Loki / LogQL Specialist)

Queries Loki for error patterns, stack traces, and anomalous log volume
for the affected services during the incident time window.

ReAct loop
----------
Uses ``bind_tools`` with the Loki tools.  The agent iterates:
    1. Extract top error patterns using loki_extract_errors
    2. Query raw log context around the first errors
    3. Check log volume for anomaly (sudden spike)
    4. Return structured findings JSON
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.agents.state import InvestigationState
from app.config import get_settings
from app.tools.loki import LokiErrorExtractionTool, LokiInstantQueryTool, LokiQueryTool

log = structlog.get_logger()

LOGS_SYSTEM_PROMPT = """
You are the Logs Agent for NovaSRE. You are a specialist in Loki and LogQL.
Your job is to extract meaningful signal from logs to help diagnose the incident.

MANDATORY STEPS:
1. Use loki_extract_errors for each affected service to get the top error patterns.
   This gives you a deduplicated view of what errors are occurring.

2. Use loki_query_range to get raw log context around the peak of the incident.
   Query with: {app="<service>"} |~ "ERROR|FATAL|panic|Exception" | json
   Set direction="backward" to get newest logs first.

3. Check log VOLUME anomaly:
   Use loki_instant_query with: count_over_time({app="<service>"}[5m])
   Compare current vs. normal (same query at -1h offset).

4. Look for specific patterns that indicate root cause:
   - "connection refused" / "connection pool exhausted" → downstream dependency issue
   - "timeout" / "deadline exceeded" → latency issue in dependency
   - "OOM" / "out of memory" → memory pressure
   - "nil pointer" / "null pointer" / "NullPointerException" → code bug
   - "authentication failed" / "permission denied" → auth/authz issue
   - "circuit breaker open" → cascading failure protection triggered

OUTPUT FORMAT:
Produce your findings as a JSON code block when done:
```json
{
  "services": {
    "<service_name>": {
      "total_error_lines": <int>,
      "unique_error_patterns": <int>,
      "top_errors": [
        {"pattern": "<normalised error>", "count": <int>, "example": "<raw line>"}
      ],
      "has_stack_traces": <bool>,
      "log_volume_spike": <bool>,
      "anomaly_detected": <bool>
    }
  },
  "root_cause_indicators": ["<list of key phrases that point to root cause>"],
  "summary": "<2-3 sentence summary of what the logs show>",
  "error_onset_time": "<ISO timestamp or relative like 'approximately 14:32 UTC'>",
  "cascading_failure_detected": <bool>
}
```

Rules:
- Do not include more than 5 top errors per service in the findings.
- If a service has no errors, note it explicitly.
- Look for timestamps to identify when errors first started.
- If you see connection errors, always note which upstream service is being called.
"""

MAX_ITERATIONS = 10


async def logs_node(state: InvestigationState) -> dict[str, Any]:
    """
    LangGraph node: Logs Agent.

    Runs a ReAct loop with Loki tools to extract error patterns and log
    anomalies.  Stores findings in state.findings["logs"].
    """
    settings = get_settings()
    time_start = time.monotonic()
    incident_id = state.get("incident_id", "unknown")
    affected_services = state.get("affected_services", [])
    time_window = state.get("time_window", {"start": "now-1h", "end": "now"})
    question = state.get("investigation_questions", {}).get(
        "logs",
        f"What error patterns appear in logs for: {', '.join(affected_services)}?",
    )

    log.info(
        "agent.logs.start",
        incident_id=incident_id,
        services=affected_services,
        time_window=time_window,
    )

    tools_list = [
        LokiQueryTool(),
        LokiInstantQueryTool(),
        LokiErrorExtractionTool(),
    ]
    langchain_tools = [t.to_langchain_tool() for t in tools_list]
    tool_by_name = {t.name: t for t in tools_list}

    llm = ChatOpenAI(
        model=settings.openai_model_primary,
        temperature=0,
        api_key=settings.openai_api_key,
    ).bind_tools(langchain_tools)

    user_msg = (
        f"Investigate logs for incident {incident_id}.\n"
        f"Affected services: {', '.join(affected_services) if affected_services else 'unknown'}\n"
        f"Time window: {time_window.get('start', 'now-1h')} to {time_window.get('end', 'now')}\n"
        f"Specific question: {question}\n\n"
        f"Start by extracting error patterns for each service, then get raw log context."
    )

    chat_messages = [
        SystemMessage(content=LOGS_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ]

    tool_call_records: list[dict] = []
    findings_raw: dict = {}
    iteration = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1

        try:
            response: AIMessage = await llm.ainvoke(chat_messages)
        except Exception as exc:  # noqa: BLE001
            log.error("agent.logs.llm_error", incident_id=incident_id, error=str(exc))
            break

        chat_messages.append(response)

        if not response.tool_calls:
            findings_raw = _extract_json_findings(response.content)
            break

        for tool_call in response.tool_calls:
            tool_name: str = tool_call["name"]
            tool_args: dict = tool_call["args"]
            call_start = time.monotonic()

            log.info(
                "agent.logs.tool_call",
                incident_id=incident_id,
                tool=tool_name,
                iteration=iteration,
            )

            tool_obj = tool_by_name.get(tool_name)
            if tool_obj is None:
                tool_result_str = json.dumps({"error": f"Unknown tool: {tool_name}"})
                success = False
            else:
                try:
                    result = await tool_obj.safe_execute(**tool_args)
                    tool_result_str = json.dumps(result.data) if result.success else json.dumps({"error": result.error})
                    success = result.success
                except Exception as exc:  # noqa: BLE001
                    tool_result_str = json.dumps({"error": str(exc)})
                    success = False

            call_duration = round((time.monotonic() - call_start) * 1000, 2)
            tool_call_records.append({
                "tool_name": tool_name,
                "agent": "logs",
                "query": str(tool_args),
                "result": tool_result_str[:500],
                "success": success,
                "duration_ms": call_duration,
            })

            chat_messages.append(
                ToolMessage(content=tool_result_str, tool_call_id=tool_call["id"])
            )

    if not findings_raw and iteration >= MAX_ITERATIONS:
        log.warning("agent.logs.max_iterations_reached", incident_id=incident_id)
        chat_messages.append(
            HumanMessage(
                content="Maximum tool calls reached. Summarise findings in the required JSON format now."
            )
        )
        try:
            final_response = await llm.ainvoke(chat_messages)
            findings_raw = _extract_json_findings(final_response.content)
        except Exception:  # noqa: BLE001
            pass

    elapsed = round((time.monotonic() - time_start) * 1000, 2)
    log.info(
        "agent.logs.complete",
        incident_id=incident_id,
        tool_calls=len(tool_call_records),
        duration_ms=elapsed,
    )

    return {
        "findings": {**state.get("findings", {}), "logs": findings_raw or {"error": "No log data collected", "tool_calls": len(tool_call_records)}},
        "tool_calls": tool_call_records,
    }


def _extract_json_findings(content: str) -> dict:
    if not content:
        return {}
    if "```json" in content:
        try:
            start = content.index("```json") + 7
            end = content.index("```", start)
            return json.loads(content[start:end].strip())
        except (ValueError, json.JSONDecodeError):
            pass
    if "```" in content:
        try:
            start = content.index("```") + 3
            end = content.index("```", start)
            return json.loads(content[start:end].strip())
        except (ValueError, json.JSONDecodeError):
            pass
    try:
        first_brace = content.index("{")
        last_brace = content.rindex("}") + 1
        return json.loads(content[first_brace:last_brace])
    except (ValueError, json.JSONDecodeError):
        pass
    return {"summary": content[:500], "raw_response": True}
