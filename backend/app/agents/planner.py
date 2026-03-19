"""
NovaSRE — Planner Agent (Orchestrator)

The Planner is the entry point of the investigation graph.  It receives the
incident context and decides:

1. Which signal sources to query (metrics / logs / traces / profiles / frontend / k8s)
2. What time window to investigate
3. A focused question for each specialist agent
4. An initial hypothesis about the root cause

The Planner outputs structured JSON which is parsed and stored in the
InvestigationState so downstream nodes can use it.
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agents.state import InvestigationState
from app.config import get_settings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """
You are the Planner agent for NovaSRE, an AI-powered SRE investigation system.
Your role is to analyse an incoming incident or question and produce a focused
investigation plan that determines which signal sources to query.

SIGNAL SELECTION RULES (apply ALL matching rules):
- High latency / slow response                → ALWAYS: metrics + traces + profiles
- Error rate spike / 5xx surge                → ALWAYS: metrics + logs + traces
- Frontend slowness / bad Web Vitals          → ALWAYS: frontend + traces + metrics
- OOMKilled / memory pressure                 → ALWAYS: metrics + profiles + k8s + logs
- Unknown / general / "investigate this"      → ALL signals
- CPU spike / high CPU                        → metrics + profiles + k8s
- Database issues / slow queries              → traces + logs + metrics
- Pod crashing / CrashLoopBackOff             → k8s + logs + metrics
- Deployment regression                       → metrics + traces + profiles + logs
- User impact / session errors                → frontend + logs + metrics
- Goroutine leak / thread exhaustion          → profiles + metrics + k8s

TIME WINDOW RULES:
- If a specific time is mentioned, centre the window around it ±30 minutes.
- If "recently" or "now", use "now-1h" to "now".
- For slow-burn issues, use "now-4h" to "now".
- Default: "now-1h" to "now".

OUTPUT FORMAT — respond with ONLY valid JSON (no markdown fences, no commentary):
{
  "agents_to_invoke": ["metrics", "logs"],
  "time_window": {"start": "now-1h", "end": "now"},
  "investigation_questions": {
    "metrics": "What is the current error rate and P99 latency for the checkout service? Has throughput dropped?",
    "logs": "What error messages appear in checkout service logs in the last hour? Any stack traces?"
  },
  "hypothesis": "The checkout service is experiencing elevated error rates, possibly due to a downstream dependency failure or a recent deployment.",
  "priority": "metrics → traces → logs",
  "plan": [
    "1. Query RED metrics (rate, error rate, P99 latency) for affected services",
    "2. Extract error log patterns from the incident time window",
    "3. Find slow/erroring traces to identify the hot span",
    "4. Synthesise findings into a Root Cause Analysis"
  ]
}

Valid agent names: metrics, logs, traces, profiles, frontend, k8s
"""


# ---------------------------------------------------------------------------
# Planner node
# ---------------------------------------------------------------------------

async def planner_node(state: InvestigationState) -> dict[str, Any]:
    """
    LangGraph node: Planner / Orchestrator.

    Reads incident context from state, calls GPT-4o to produce an
    investigation plan, parses the JSON response, and updates state with:
    - plan
    - agents_to_invoke
    - time_window (if refined by the LLM)
    - investigation_questions
    - hypothesis
    - status = "investigating"

    Falls back gracefully on JSON parse errors to avoid blocking the graph.
    """
    settings = get_settings()
    time_start = time.monotonic()
    incident_id = state.get("incident_id", "unknown")

    log.info(
        "agent.planner.start",
        incident_id=incident_id,
        query=state.get("query"),
        affected_services=state.get("affected_services", []),
    )

    # --- Build user message ---
    affected_services = state.get("affected_services", [])
    query = state.get("query", "No query provided")
    time_window = state.get("time_window", {"start": "now-1h", "end": "now"})
    alert_context = state.get("alert_context", {})

    user_content = f"""INCIDENT CONTEXT:
Incident ID: {incident_id}
Query / Description: {query}
Affected Services: {", ".join(affected_services) if affected_services else "Unknown"}
Time Window: {time_window.get("start", "now-1h")} to {time_window.get("end", "now")}
Alert Context: {json.dumps(alert_context, indent=2) if alert_context else "None"}

Produce an investigation plan for this incident."""

    messages = [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]

    try:
        llm = ChatOpenAI(
            model=settings.openai_model_primary,
            temperature=0,
            api_key=settings.openai_api_key,
        )
        response = await llm.ainvoke(messages)
        raw_content = response.content

        # Strip markdown code fences if present
        cleaned = raw_content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first and last line (``` markers)
            cleaned = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            cleaned = cleaned.strip()

        plan_json = json.loads(cleaned)

    except json.JSONDecodeError as exc:
        log.error(
            "agent.planner.json_parse_error",
            incident_id=incident_id,
            error=str(exc),
            raw_response=raw_content[:500] if "raw_content" in dir() else "no response",
        )
        # Fall back: investigate all signals
        plan_json = _default_plan(query, time_window)

    except Exception as exc:  # noqa: BLE001
        log.error(
            "agent.planner.error",
            incident_id=incident_id,
            error=str(exc),
        )
        plan_json = _default_plan(query, time_window)

    elapsed = round((time.monotonic() - time_start) * 1000, 2)

    agents_to_invoke: list[str] = plan_json.get("agents_to_invoke", _all_agents())
    # Validate: filter to known agent names
    valid_agents = {"metrics", "logs", "traces", "profiles", "frontend", "k8s"}
    agents_to_invoke = [a for a in agents_to_invoke if a in valid_agents]
    if not agents_to_invoke:
        agents_to_invoke = _all_agents()

    plan: list[str] = plan_json.get("plan", [
        "1. Query all signal sources for the affected services",
        "2. Synthesise findings into RCA",
    ])

    # Refined time window from Planner (may override input)
    refined_window = plan_json.get("time_window", time_window)
    hypothesis = plan_json.get("hypothesis", "")
    investigation_questions = plan_json.get("investigation_questions", {})

    log.info(
        "agent.planner.complete",
        incident_id=incident_id,
        agents_to_invoke=agents_to_invoke,
        time_window=refined_window,
        hypothesis=hypothesis[:100] if hypothesis else "",
        duration_ms=elapsed,
    )

    # Record the planner's tool call (its own "tool" is LLM reasoning)
    planner_call = {
        "tool_name": "planner_llm",
        "agent": "planner",
        "query": user_content[:300],
        "result": {
            "agents_to_invoke": agents_to_invoke,
            "hypothesis": hypothesis[:200] if hypothesis else "",
        },
        "success": True,
        "duration_ms": elapsed,
    }

    return {
        "plan": plan,
        "agents_to_invoke": agents_to_invoke,
        "time_window": refined_window,
        "investigation_questions": investigation_questions,
        "hypothesis": hypothesis,
        "status": "investigating",
        "tool_calls": [planner_call],
        "messages": [
            HumanMessage(content=user_content),
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_agents() -> list[str]:
    """Return all valid specialist agent names."""
    return ["metrics", "logs", "traces", "profiles", "frontend", "k8s"]


def _default_plan(query: str, time_window: dict) -> dict:
    """
    Safe fallback plan used when the LLM call or JSON parsing fails.

    Activates all agents to ensure no signal is missed.
    """
    return {
        "agents_to_invoke": _all_agents(),
        "time_window": time_window,
        "investigation_questions": {
            "metrics": f"What are the RED metrics (rate, error rate, latency) for the affected services? Query: {query}",
            "logs": f"What error log patterns appear in the incident window? Query: {query}",
            "traces": f"Are there slow or erroring traces? Which span is the bottleneck? Query: {query}",
            "profiles": f"Is there CPU or memory hot-spotting? Query: {query}",
            "frontend": f"Are Core Web Vitals degraded? What JS errors are occurring? Query: {query}",
            "k8s": f"Are any pods in a bad state (OOMKilled, CrashLoopBackOff, Pending)? Query: {query}",
        },
        "hypothesis": "Investigation pending — LLM planning failed, running all signal collectors.",
        "priority": "metrics → traces → logs → profiles → frontend → k8s",
        "plan": [
            "1. Query RED metrics for affected services (Mimir)",
            "2. Extract error log patterns (Loki)",
            "3. Find slow/erroring traces (Tempo)",
            "4. Check CPU/memory profiles (Pyroscope)",
            "5. Check Core Web Vitals and JS errors (Faro)",
            "6. Check pod health and K8s events",
            "7. Synthesise all findings into RCA",
        ],
    }
