"""
NovaSRE — Traces Agent (Tempo / TraceQL Specialist)

Queries Tempo to find slow traces, identify hot spans, and trace error
propagation across service boundaries.

ReAct loop
----------
1. Search for slow traces above a latency threshold
2. Fetch the slowest trace to inspect span breakdown
3. Search for error traces (status=error)
4. Identify which service/span is the bottleneck
5. Return structured findings JSON
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
from app.tools.tempo import TempoGetTraceTool, TempoSearchTool, TempoSlowTracesTool

log = structlog.get_logger()

TRACES_SYSTEM_PROMPT = """
You are the Traces Agent for NovaSRE. You are a specialist in distributed tracing with Tempo and TraceQL.
Your job is to find the traces that explain the incident — slow traces, error traces,
and the specific span that is the bottleneck.

MANDATORY STEPS:
1. Find slow traces for each affected service using tempo_slow_traces.
   Start with threshold_ms=2000 (2 seconds). If no results, try 500ms.

2. For the top slow trace, fetch the full waterfall using tempo_get_trace.
   Identify which span takes the most time (hottest span).

3. Search for error traces using tempo_search:
   Query: { .service.name = "<service>" && status = error }

4. Look for patterns:
   - All slow traces have a common "db" or "cache" span → downstream issue
   - Error traces all fail at the same span → specific operation failing
   - Traces from one service call chain are slow → service topology problem
   - P99 of span duration >> P50 → tail latency / timeout issue

5. Identify the blast radius: which upstream services are affected by the
   slow downstream service?

OUTPUT FORMAT — produce findings as JSON:
```json
{
  "services": {
    "<service_name>": {
      "slow_trace_count": <int>,
      "slowest_trace_ms": <float or null>,
      "p99_trace_ms": <float or null>,
      "error_trace_count": <int>,
      "hottest_span": {
        "service": "<service>",
        "operation": "<operation name>",
        "duration_ms": <float>,
        "pct_of_trace": <float>
      } or null,
      "anomaly_detected": <bool>
    }
  },
  "bottleneck_service": "<service name or null>",
  "bottleneck_operation": "<span name or null>",
  "error_propagation_path": ["svc-a", "svc-b", "svc-c"],
  "summary": "<2-3 sentence summary of what traces reveal>",
  "trace_pattern": "cascading_timeout | single_service_error | db_slowdown | unknown"
}
```

Rules:
- Never fetch more than 3 full traces (to avoid state explosion).
- If traces show the hot span is a "db" or "redis" call, note the downstream service.
- Include trace IDs for the most interesting traces so engineers can look them up.
"""

MAX_ITERATIONS = 10


async def traces_node(state: InvestigationState) -> dict[str, Any]:
    """
    LangGraph node: Traces Agent.

    Runs a ReAct loop with Tempo tools to find slow/erroring traces and
    identify the bottleneck span.  Stores findings in state.findings["traces"].
    """
    settings = get_settings()
    time_start = time.monotonic()
    incident_id = state.get("incident_id", "unknown")
    affected_services = state.get("affected_services", [])
    time_window = state.get("time_window", {"start": "now-1h", "end": "now"})
    question = state.get("investigation_questions", {}).get(
        "traces",
        f"Which traces are slow or erroring for: {', '.join(affected_services)}?",
    )

    log.info(
        "agent.traces.start",
        incident_id=incident_id,
        services=affected_services,
        time_window=time_window,
    )

    tools_list = [
        TempoSearchTool(),
        TempoGetTraceTool(),
        TempoSlowTracesTool(),
    ]
    langchain_tools = [t.to_langchain_tool() for t in tools_list]
    tool_by_name = {t.name: t for t in tools_list}

    llm = ChatOpenAI(
        model=settings.openai_model_primary,
        temperature=0,
        api_key=settings.openai_api_key,
    ).bind_tools(langchain_tools)

    user_msg = (
        f"Investigate distributed traces for incident {incident_id}.\n"
        f"Affected services: {', '.join(affected_services) if affected_services else 'unknown'}\n"
        f"Time window: {time_window.get('start', 'now-1h')} to {time_window.get('end', 'now')}\n"
        f"Specific question: {question}\n\n"
        f"Start by finding slow traces (>2s) for each service, then drill into the slowest one."
    )

    chat_messages = [
        SystemMessage(content=TRACES_SYSTEM_PROMPT),
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
            log.error("agent.traces.llm_error", incident_id=incident_id, error=str(exc))
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
                "agent.traces.tool_call",
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
                "agent": "traces",
                "query": str(tool_args),
                "result": tool_result_str[:500],
                "success": success,
                "duration_ms": call_duration,
            })

            chat_messages.append(
                ToolMessage(content=tool_result_str, tool_call_id=tool_call["id"])
            )

    if not findings_raw and iteration >= MAX_ITERATIONS:
        log.warning("agent.traces.max_iterations_reached", incident_id=incident_id)
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
        "agent.traces.complete",
        incident_id=incident_id,
        tool_calls=len(tool_call_records),
        duration_ms=elapsed,
    )

    return {
        "findings": {**state.get("findings", {}), "traces": findings_raw or {"error": "No trace data collected", "tool_calls": len(tool_call_records)}},
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
