"""
NovaSRE — Profiles Agent (Pyroscope / Continuous Profiling Specialist)

Queries Pyroscope for CPU and memory profiles, identifies hot functions,
and compares before/after a deployment to detect regressions.

ReAct loop
----------
1. Fetch CPU profile for each affected service in the incident window
2. If a recent deployment annotation exists, run a diff (before vs after)
3. Identify top CPU-consuming or memory-allocating functions
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
from app.tools.pyroscope import PyroscopeDiffTool, PyroscopeQueryTool

log = structlog.get_logger()

PROFILES_SYSTEM_PROMPT = """
You are the Profiles Agent for NovaSRE. You are a specialist in continuous profiling with Pyroscope.
Your job is to identify CPU hot spots, memory allocation patterns, and performance regressions
from profiling data.

MANDATORY STEPS:
1. Fetch the CPU profile for each affected service during the incident window.
   Use pyroscope_query with profile_type="cpu".
   Set from_time and until_time to the incident time window.

2. Fetch the memory profile (alloc_objects or inuse_space):
   Use pyroscope_query with profile_type="memory".

3. If you suspect a deployment regression (based on the incident context),
   use pyroscope_diff to compare:
   - Baseline: 1 hour before the incident
   - Comparison: during the incident

4. Analyse the top_functions list:
   - Functions with high CPU% that shouldn't be CPU-intensive → hot spot
   - GC functions dominating → memory pressure / allocation churn
   - Lock/mutex functions high → contention issue
   - Network/IO functions high → I/O bound bottleneck

PROFILE TYPE SELECTION:
- CPU spike → profile_type="cpu"
- Memory pressure / OOM → profile_type="memory" or "inuse_space"
- Goroutine leak (Go) → profile_type="goroutines"
- Lock contention → profile_type="mutex"

OUTPUT FORMAT — produce findings as JSON:
```json
{
  "services": {
    "<service_name>": {
      "cpu_top_functions": [
        {"function": "<name>", "pct": <float>, "samples": <int>}
      ],
      "memory_top_allocators": [
        {"function": "<name>", "pct": <float>}
      ],
      "cpu_regression_detected": <bool>,
      "memory_regression_detected": <bool>,
      "top_changed_functions": [
        {"function": "<name>", "baseline_pct": <float>, "comparison_pct": <float>, "delta_pct": <float>}
      ],
      "anomaly_detected": <bool>,
      "anomaly_description": "<string>"
    }
  },
  "hot_function": "<function name most likely causing the incident>",
  "regression_introduced_by": "<deployment or code change if identifiable, else null>",
  "summary": "<2-3 sentence summary of profiling findings>",
  "profile_pattern": "cpu_hotspot | memory_churn | goroutine_leak | lock_contention | normal"
}
```

Rules:
- If Pyroscope returns no data (service not instrumented), note it and return empty findings.
- A function consuming >20% CPU is significant.
- For diff analysis, a delta_pct > 10% is a meaningful regression.
- Avoid over-interpreting profiles — note uncertainty when present.
"""

MAX_ITERATIONS = 8  # Profiles are expensive; fewer iterations


async def profiles_node(state: InvestigationState) -> dict[str, Any]:
    """
    LangGraph node: Profiles Agent.

    Runs a ReAct loop with Pyroscope tools to identify CPU/memory hot spots
    and deployment regressions.  Stores findings in state.findings["profiles"].
    """
    settings = get_settings()
    time_start = time.monotonic()
    incident_id = state.get("incident_id", "unknown")
    affected_services = state.get("affected_services", [])
    time_window = state.get("time_window", {"start": "now-1h", "end": "now"})
    question = state.get("investigation_questions", {}).get(
        "profiles",
        f"Are there CPU/memory hot spots for: {', '.join(affected_services)}?",
    )

    log.info(
        "agent.profiles.start",
        incident_id=incident_id,
        services=affected_services,
        time_window=time_window,
    )

    tools_list = [
        PyroscopeQueryTool(),
        PyroscopeDiffTool(),
    ]
    langchain_tools = [t.to_langchain_tool() for t in tools_list]
    tool_by_name = {t.name: t for t in tools_list}

    llm = ChatOpenAI(
        model=settings.openai_model_primary,
        temperature=0,
        api_key=settings.openai_api_key,
    ).bind_tools(langchain_tools)

    user_msg = (
        f"Investigate CPU and memory profiles for incident {incident_id}.\n"
        f"Affected services: {', '.join(affected_services) if affected_services else 'unknown'}\n"
        f"Time window: {time_window.get('start', 'now-1h')} to {time_window.get('end', 'now')}\n"
        f"Specific question: {question}\n\n"
        f"Start by fetching the CPU profile for each service, then check memory if CPU looks normal."
    )

    chat_messages = [
        SystemMessage(content=PROFILES_SYSTEM_PROMPT),
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
            log.error("agent.profiles.llm_error", incident_id=incident_id, error=str(exc))
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
                "agent.profiles.tool_call",
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
                    # Pyroscope data can be large; summarise flamebearer, keep top_functions
                    if result.success and result.data:
                        # Strip raw flamebearer to avoid massive state
                        data_summary = {
                            k: v for k, v in result.data.items()
                            if k != "flamebearer"
                        }
                        tool_result_str = json.dumps(data_summary)
                    else:
                        tool_result_str = json.dumps({"error": result.error})
                    success = result.success
                except Exception as exc:  # noqa: BLE001
                    tool_result_str = json.dumps({"error": str(exc)})
                    success = False

            call_duration = round((time.monotonic() - call_start) * 1000, 2)
            tool_call_records.append({
                "tool_name": tool_name,
                "agent": "profiles",
                "query": str(tool_args),
                "result": tool_result_str[:500],
                "success": success,
                "duration_ms": call_duration,
            })

            chat_messages.append(
                ToolMessage(content=tool_result_str, tool_call_id=tool_call["id"])
            )

    if not findings_raw and iteration >= MAX_ITERATIONS:
        log.warning("agent.profiles.max_iterations_reached", incident_id=incident_id)
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
        "agent.profiles.complete",
        incident_id=incident_id,
        tool_calls=len(tool_call_records),
        duration_ms=elapsed,
    )

    return {
        "findings": {**state.get("findings", {}), "profiles": findings_raw or {"error": "No profiling data collected", "tool_calls": len(tool_call_records)}},
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
