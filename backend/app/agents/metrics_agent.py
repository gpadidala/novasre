"""
NovaSRE — Metrics Agent (Mimir / PromQL Specialist)

Queries Mimir for RED metrics (Rate, Error rate, Duration) for affected
services, computes SLO burn rates, and compares current values against a
1-hour-ago baseline.

ReAct loop
----------
The agent implements a Reason → Act → Observe cycle using LangChain's
``bind_tools`` pattern:

    iteration 1: LLM reasons about what to query → calls mimir_query
    iteration 2: LLM sees result → decides to query mimir_query_range for trend
    ...
    iteration N: LLM has enough data → produces structured findings JSON

Max iterations: 10  (prevents runaway tool loops)
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
from app.tools.mimir import MimirLabelValuesTool, MimirQueryTool, MimirRangeTool

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

METRICS_SYSTEM_PROMPT = """
You are the Metrics Agent for NovaSRE. You are a specialist in Prometheus/Mimir metrics.
Your job is to query Mimir using PromQL to understand what the metrics tell us about the incident.

MANDATORY QUERY ORDER for each affected service:
1. Error rate:
   rate(http_requests_total{app="<service>",status=~"5.."}[5m])

2. Request rate (throughput):
   rate(http_requests_total{app="<service>"}[5m])

3. P99 latency:
   histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{app="<service>"}[5m]))

4. CPU usage:
   rate(container_cpu_usage_seconds_total{container="<service>"}[5m])

5. Memory usage:
   container_memory_working_set_bytes{container="<service>"}

6. SLO burn rate comparison (1h window for trend):
   Use mimir_query_range with start=<time_window.start>, end=<time_window.end>

COMPARISON RULE:
After querying current values, ALWAYS query the same metrics with time offset to get baseline:
  Use mimir_query with time parameter set to 1 hour before the start of the incident window.

OUTPUT FORMAT:
When you have gathered sufficient data, produce your findings as a JSON code block:
```json
{
  "services": {
    "<service_name>": {
      "error_rate_rps": <float or null>,
      "error_rate_pct": <float or null>,
      "request_rate_rps": <float or null>,
      "p99_latency_ms": <float or null>,
      "cpu_cores": <float or null>,
      "memory_mb": <float or null>,
      "baseline_error_rate_rps": <float or null>,
      "anomaly_detected": <bool>,
      "anomaly_description": "<string>"
    }
  },
  "summary": "<2-3 sentence summary of what the metrics show>",
  "severity_assessment": "critical | high | medium | low",
  "key_metric": "<name of the most abnormal metric>",
  "slo_breach": <bool>
}
```

Rules:
- If a metric is not available (no data), use null — do not fabricate values.
- Express error rates as both RPS and percentage of total traffic.
- Always compare to baseline to assess whether this is anomalous.
- If you cannot query a metric (tool error), note it in the summary.
- Stop querying after 10 tool calls to avoid runaway loops.
"""

MAX_ITERATIONS = 10


# ---------------------------------------------------------------------------
# Metrics node
# ---------------------------------------------------------------------------

async def metrics_node(state: InvestigationState) -> dict[str, Any]:
    """
    LangGraph node: Metrics Agent.

    Runs a ReAct loop with Mimir tools to gather RED metrics for all
    affected services.  Stores findings in state.findings["metrics"].
    """
    settings = get_settings()
    time_start = time.monotonic()
    incident_id = state.get("incident_id", "unknown")
    affected_services = state.get("affected_services", [])
    time_window = state.get("time_window", {"start": "now-1h", "end": "now"})
    question = state.get("investigation_questions", {}).get(
        "metrics",
        f"What are the RED metrics for: {', '.join(affected_services)}?",
    )

    log.info(
        "agent.metrics.start",
        incident_id=incident_id,
        services=affected_services,
        time_window=time_window,
    )

    # --- Tool setup ---
    tools_list = [
        MimirQueryTool(),
        MimirRangeTool(),
        MimirLabelValuesTool(),
    ]
    langchain_tools = [t.to_langchain_tool() for t in tools_list]
    tool_by_name = {t.name: t for t in tools_list}

    llm = ChatOpenAI(
        model=settings.openai_model_primary,
        temperature=0,
        api_key=settings.openai_api_key,
    ).bind_tools(langchain_tools)

    # --- Build initial messages ---
    user_msg = (
        f"Investigate metrics for incident {incident_id}.\n"
        f"Affected services: {', '.join(affected_services) if affected_services else 'unknown'}\n"
        f"Time window: {time_window.get('start', 'now-1h')} to {time_window.get('end', 'now')}\n"
        f"Specific question: {question}\n\n"
        f"Start by querying error rate and request rate for each affected service."
    )

    chat_messages = [
        SystemMessage(content=METRICS_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ]

    tool_call_records: list[dict] = []
    findings_raw: dict = {}
    iteration = 0

    # --- ReAct loop ---
    while iteration < MAX_ITERATIONS:
        iteration += 1

        try:
            response: AIMessage = await llm.ainvoke(chat_messages)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "agent.metrics.llm_error",
                incident_id=incident_id,
                iteration=iteration,
                error=str(exc),
            )
            break

        chat_messages.append(response)

        # If no tool calls, the agent has finished reasoning
        if not response.tool_calls:
            # Extract findings JSON from the response if present
            findings_raw = _extract_json_findings(response.content)
            break

        # Execute each tool call
        for tool_call in response.tool_calls:
            tool_name: str = tool_call["name"]
            tool_args: dict = tool_call["args"]
            call_start = time.monotonic()

            log.info(
                "agent.metrics.tool_call",
                incident_id=incident_id,
                tool=tool_name,
                args=tool_args,
                iteration=iteration,
            )

            # Execute tool
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

            # Record tool call
            tool_call_records.append({
                "tool_name": tool_name,
                "agent": "metrics",
                "query": str(tool_args),
                "result": tool_result_str[:500],  # Truncate for state size
                "success": success,
                "duration_ms": call_duration,
            })

            # Feed result back to LLM
            chat_messages.append(
                ToolMessage(
                    content=tool_result_str,
                    tool_call_id=tool_call["id"],
                )
            )

    # If findings_raw is empty but we have chat messages, do one final synthesis
    if not findings_raw and iteration >= MAX_ITERATIONS:
        log.warning(
            "agent.metrics.max_iterations_reached",
            incident_id=incident_id,
        )
        # Ask LLM to summarise what it found
        chat_messages.append(
            HumanMessage(
                content="You have reached the maximum number of tool calls. "
                "Please summarise your findings in the required JSON format now."
            )
        )
        try:
            final_response = await llm.ainvoke(chat_messages)
            findings_raw = _extract_json_findings(final_response.content)
        except Exception:  # noqa: BLE001
            pass

    elapsed = round((time.monotonic() - time_start) * 1000, 2)

    log.info(
        "agent.metrics.complete",
        incident_id=incident_id,
        tool_calls=len(tool_call_records),
        has_findings=bool(findings_raw),
        duration_ms=elapsed,
    )

    return {
        "findings": {**state.get("findings", {}), "metrics": findings_raw or {"error": "No metrics data collected", "tool_calls": len(tool_call_records)}},
        "tool_calls": tool_call_records,
    }


# ---------------------------------------------------------------------------
# Helper: extract JSON findings block from LLM response
# ---------------------------------------------------------------------------

def _extract_json_findings(content: str) -> dict:
    """
    Parse the structured JSON findings block from the LLM response.

    The LLM is prompted to wrap its final output in a ```json ... ``` block.
    Falls back to scanning for the first ``{`` ... ``}`` if the fence is absent.
    """
    if not content:
        return {}

    # Try fenced block first
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

    # Try bare JSON object
    try:
        first_brace = content.index("{")
        last_brace = content.rindex("}") + 1
        return json.loads(content[first_brace:last_brace])
    except (ValueError, json.JSONDecodeError):
        pass

    # Return a minimal findings dict with the raw text as summary
    return {"summary": content[:500], "raw_response": True}
