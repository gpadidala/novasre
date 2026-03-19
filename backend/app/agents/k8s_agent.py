"""
NovaSRE — Kubernetes Agent (Cluster Health Specialist)

Queries the Kubernetes API for pod health, OOMKilled events, resource
limits/requests, deployment events, and CrashLoopBackOff conditions.

ReAct loop
----------
1. List pods in affected service namespaces, check for bad phases
2. Fetch Warning events for any unhealthy pods
3. Check pod resource limits vs requests (potential OOM candidates)
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
from app.tools.kubernetes import KubernetesEventsTool, KubernetesLogsTool, KubernetesPodsTool

log = structlog.get_logger()

K8S_SYSTEM_PROMPT = """
You are the Kubernetes Agent for NovaSRE. You are a specialist in Kubernetes cluster health.
Your job is to identify pod-level issues that may be causing or contributing to the incident.

MANDATORY STEPS:
1. List pods for the affected services using k8s_pods.
   Use label_selector="app=<service>" to filter.
   Look for pods that are NOT in Running phase, or have high restart counts.

2. For any pods with status issues, fetch Kubernetes events using k8s_events.
   Focus on Warning events: OOMKilled, CrashLoopBackOff, ImagePullBackOff,
   Evicted, FailedScheduling.

3. For pods with recent restarts or OOMKilled status, optionally fetch recent
   logs using k8s_logs to get the last error before the crash.

HEALTH INDICATORS TO CHECK:
- Phase != "Running" → pod not healthy
- restartCount > 3 in last hour → CrashLoopBackOff risk
- reason == "OOMKilled" → memory limit too low
- reason == "Error" or "CrashLoopBackOff" → application crash
- Pending phase → scheduling issue (resource pressure, node affinity)
- Conditions: PodScheduled=False → node pressure
- Resources: memory limit very close to usage → OOM risk

NAMESPACE INFERENCE:
- If namespace is not specified, try "default", "production", and "<service-name>"
- Service names like "checkout" → try namespace "checkout" and "production"

OUTPUT FORMAT — produce findings as JSON:
```json
{
  "namespaces_checked": ["<namespace>"],
  "services": {
    "<service_name>": {
      "pod_summary": {
        "total": <int>,
        "running": <int>,
        "pending": <int>,
        "failed": <int>,
        "crash_loop": <int>,
        "oom_killed": <int>,
        "total_restarts": <int>
      },
      "unhealthy_pods": [
        {
          "name": "<pod_name>",
          "phase": "<phase>",
          "reason": "<reason>",
          "restarts": <int>,
          "last_event": "<most recent warning event message>"
        }
      ],
      "resource_pressure": <bool>,
      "oom_risk": <bool>,
      "scheduling_issues": <bool>
    }
  },
  "cluster_events": [
    {"type": "Warning", "reason": "<reason>", "message": "<msg>", "count": <int>}
  ],
  "k8s_root_cause_detected": <bool>,
  "k8s_root_cause": "<description or null>",
  "summary": "<2-3 sentence summary of K8s findings>",
  "recommendation": "<immediate K8s action if needed, else null>"
}
```

Rules:
- If kubectl / K8s client is not available, note it in the summary and return partial findings.
- Always check both the pod phase AND the container statuses (a Running pod can have a terminated container).
- OOMKilled is often not immediately visible in pod phase — check container_statuses[].reason.
- A pod with restartCount > 5 in the last hour almost certainly has a crashing container.
"""

MAX_ITERATIONS = 8


async def k8s_node(state: InvestigationState) -> dict[str, Any]:
    """
    LangGraph node: Kubernetes Agent.

    Runs a ReAct loop with K8s tools to identify pod-level issues.
    Stores findings in state.findings["k8s"].
    """
    settings = get_settings()
    time_start = time.monotonic()
    incident_id = state.get("incident_id", "unknown")
    affected_services = state.get("affected_services", [])
    time_window = state.get("time_window", {"start": "now-1h", "end": "now"})
    question = state.get("investigation_questions", {}).get(
        "k8s",
        f"Are there pod-level issues for: {', '.join(affected_services)}?",
    )

    log.info(
        "agent.k8s.start",
        incident_id=incident_id,
        services=affected_services,
        time_window=time_window,
    )

    tools_list = [
        KubernetesPodsTool(),
        KubernetesEventsTool(),
        KubernetesLogsTool(),
    ]
    langchain_tools = [t.to_langchain_tool() for t in tools_list]
    tool_by_name = {t.name: t for t in tools_list}

    llm = ChatOpenAI(
        model=settings.openai_model_primary,
        temperature=0,
        api_key=settings.openai_api_key,
    ).bind_tools(langchain_tools)

    user_msg = (
        f"Investigate Kubernetes pod health for incident {incident_id}.\n"
        f"Affected services: {', '.join(affected_services) if affected_services else 'unknown'}\n"
        f"Time window: {time_window.get('start', 'now-1h')} to {time_window.get('end', 'now')}\n"
        f"Specific question: {question}\n\n"
        f"Check pod status for each service. Start with namespace 'default' or 'production'."
    )

    chat_messages = [
        SystemMessage(content=K8S_SYSTEM_PROMPT),
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
            log.error("agent.k8s.llm_error", incident_id=incident_id, error=str(exc))
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
                "agent.k8s.tool_call",
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
                "agent": "k8s",
                "query": str(tool_args),
                "result": tool_result_str[:500],
                "success": success,
                "duration_ms": call_duration,
            })

            chat_messages.append(
                ToolMessage(content=tool_result_str, tool_call_id=tool_call["id"])
            )

    if not findings_raw and iteration >= MAX_ITERATIONS:
        log.warning("agent.k8s.max_iterations_reached", incident_id=incident_id)
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
        "agent.k8s.complete",
        incident_id=incident_id,
        tool_calls=len(tool_call_records),
        duration_ms=elapsed,
    )

    return {
        "findings": {**state.get("findings", {}), "k8s": findings_raw or {"error": "No K8s data collected", "tool_calls": len(tool_call_records)}},
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
