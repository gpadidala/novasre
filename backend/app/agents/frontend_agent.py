"""
NovaSRE — Frontend Agent (Faro / RUM Specialist)

Queries Grafana Faro for Core Web Vitals degradation, JavaScript errors,
and affected user sessions to quantify the user-facing impact of an incident.

ReAct loop
----------
1. Fetch Core Web Vitals (LCP, FID/INP, CLS, TTFB) via faro_web_vitals
2. Fetch JS error counts and deduplicated error types via faro_errors
3. Count affected user sessions via faro_sessions
4. Correlate frontend signals with backend incident timing
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
from app.tools.faro import FaroErrorsTool, FaroSessionsTool, FaroWebVitalsTool

log = structlog.get_logger()

FRONTEND_SYSTEM_PROMPT = """
You are the Frontend Agent for NovaSRE. You are a specialist in Real User Monitoring (RUM)
and frontend observability using Grafana Faro.

Your job is to determine the user-facing impact of the incident:
- Are Core Web Vitals degraded?
- Are users experiencing JavaScript errors?
- How many user sessions are affected?

MANDATORY STEPS:
1. Fetch Core Web Vitals using faro_web_vitals for each affected frontend app.
   The app name is typically the service name or the frontend application name.

2. Fetch JavaScript errors using faro_errors.
   Look for errors that correlate with the backend incident (similar timing).

3. Count affected sessions using faro_sessions.
   This gives us the user impact number: "X out of Y sessions affected".

WEB VITALS THRESHOLDS (Google's CrUX standards):
- LCP (Largest Contentful Paint): Good < 2500ms, Needs Improvement < 4000ms, Poor >= 4000ms
- FID (First Input Delay): Good < 100ms, Needs Improvement < 300ms
- INP (Interaction to Next Paint): Good < 200ms, Needs Improvement < 500ms
- CLS (Cumulative Layout Shift): Good < 0.1, Needs Improvement < 0.25
- TTFB (Time to First Byte): Good < 800ms, Needs Improvement < 1800ms

CORRELATION RULES:
- High TTFB → backend latency is affecting frontend (check traces/metrics)
- High LCP without high TTFB → frontend rendering issue (check JS errors)
- Spike in JS errors correlating with backend error rate → API errors surface in frontend
- Session error rate > 5% → significant user impact

OUTPUT FORMAT — produce findings as JSON:
```json
{
  "apps": {
    "<app_name>": {
      "web_vitals": {
        "LCP": {"p75": <float or null>, "rating": "good|needs_improvement|poor|no_data"},
        "INP": {"p75": <float or null>, "rating": "..."},
        "CLS": {"p75": <float or null>, "rating": "..."},
        "TTFB": {"p75": <float or null>, "rating": "..."},
        "FCP": {"p75": <float or null>, "rating": "..."}
      },
      "js_errors": {
        "total_events": <int>,
        "unique_types": <int>,
        "top_errors": [{"type": "<string>", "count": <int>, "message": "<string>"}]
      },
      "sessions": {
        "total": <int>,
        "with_errors": <int>,
        "error_rate_pct": <float>
      },
      "user_impact_detected": <bool>
    }
  },
  "total_affected_users": <int>,
  "frontend_degraded": <bool>,
  "degraded_vitals": ["LCP", "TTFB"],
  "backend_correlation": "<how frontend signals correlate with backend incident>",
  "summary": "<2-3 sentence summary of frontend/user impact>"
}
```

Rules:
- If Faro is not configured for the service, note it and return empty findings.
- Always report the total_affected_users count — this is critical for incident severity.
- If session data is unavailable, estimate based on error event counts.
- TTFB degradation almost always has a backend root cause — note this explicitly.
"""

MAX_ITERATIONS = 8


async def frontend_node(state: InvestigationState) -> dict[str, Any]:
    """
    LangGraph node: Frontend Agent.

    Runs a ReAct loop with Faro tools to assess user-facing impact.
    Stores findings in state.findings["frontend"] and sets
    state.affected_user_count if session data is available.
    """
    settings = get_settings()
    time_start = time.monotonic()
    incident_id = state.get("incident_id", "unknown")
    affected_services = state.get("affected_services", [])
    time_window = state.get("time_window", {"start": "now-1h", "end": "now"})
    question = state.get("investigation_questions", {}).get(
        "frontend",
        f"What is the user-facing impact for: {', '.join(affected_services)}?",
    )

    log.info(
        "agent.frontend.start",
        incident_id=incident_id,
        services=affected_services,
        time_window=time_window,
    )

    tools_list = [
        FaroWebVitalsTool(),
        FaroErrorsTool(),
        FaroSessionsTool(),
    ]
    langchain_tools = [t.to_langchain_tool() for t in tools_list]
    tool_by_name = {t.name: t for t in tools_list}

    llm = ChatOpenAI(
        model=settings.openai_model_primary,
        temperature=0,
        api_key=settings.openai_api_key,
    ).bind_tools(langchain_tools)

    user_msg = (
        f"Investigate frontend / user impact for incident {incident_id}.\n"
        f"Affected services (use as Faro app names): {', '.join(affected_services) if affected_services else 'unknown'}\n"
        f"Time window: {time_window.get('start', 'now-1h')} to {time_window.get('end', 'now')}\n"
        f"Specific question: {question}\n\n"
        f"Start by checking Web Vitals, then JS errors, then session impact."
    )

    chat_messages = [
        SystemMessage(content=FRONTEND_SYSTEM_PROMPT),
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
            log.error("agent.frontend.llm_error", incident_id=incident_id, error=str(exc))
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
                "agent.frontend.tool_call",
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
                "agent": "frontend",
                "query": str(tool_args),
                "result": tool_result_str[:500],
                "success": success,
                "duration_ms": call_duration,
            })

            chat_messages.append(
                ToolMessage(content=tool_result_str, tool_call_id=tool_call["id"])
            )

    if not findings_raw and iteration >= MAX_ITERATIONS:
        log.warning("agent.frontend.max_iterations_reached", incident_id=incident_id)
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

    # Extract affected_user_count for top-level state if available
    affected_user_count: int | None = None
    if findings_raw:
        affected_user_count = findings_raw.get("total_affected_users")

    log.info(
        "agent.frontend.complete",
        incident_id=incident_id,
        tool_calls=len(tool_call_records),
        affected_users=affected_user_count,
        duration_ms=elapsed,
    )

    output: dict[str, Any] = {
        "findings": {**state.get("findings", {}), "frontend": findings_raw or {"error": "No frontend data collected", "tool_calls": len(tool_call_records)}},
        "tool_calls": tool_call_records,
    }
    if affected_user_count is not None:
        output["affected_user_count"] = affected_user_count

    return output


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
