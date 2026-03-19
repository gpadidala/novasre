"""
NovaSRE — Agent State Definitions

Defines the shared TypedDict state that flows through the LangGraph
investigation graph.  Every node reads from and writes to this state.

Key design decisions
--------------------
- ``messages`` and ``tool_calls`` use ``Annotated[list, operator.add]`` so
  LangGraph merges them across parallel branches (fan-out/fan-in).
- ``findings`` is a typed dict of per-signal results, initialised to None
  so each specialist agent can be checked independently.
- ``agents_to_invoke`` is set by the Planner and consumed by the graph
  router to determine which specialist agents to activate.
"""

from __future__ import annotations

import operator
from typing import Annotated, Optional, TypedDict


class SignalFindings(TypedDict, total=False):
    """Per-signal investigation findings accumulated during a run."""

    metrics: Optional[dict]    # Mimir / PromQL findings
    logs: Optional[dict]       # Loki / LogQL findings
    traces: Optional[dict]     # Tempo / TraceQL findings
    profiles: Optional[dict]   # Pyroscope profiling findings
    frontend: Optional[dict]   # Faro / RUM findings
    k8s: Optional[dict]        # Kubernetes pod/event findings


class InvestigationState(TypedDict, total=False):
    """
    Shared state for the LangGraph investigation workflow.

    Input fields (set before graph invocation)
    -------------------------------------------
    incident_id         : Unique incident identifier (UUID string or short ID).
    query               : Free-text investigation question or incident description.
    affected_services   : List of service names known to be impacted.
    alert_context       : Raw alert payload / Alertmanager context dict.
    time_window         : ``{"start": "now-1h", "end": "now"}`` dict.

    Planner-set fields
    ------------------
    plan                : Human-readable list of investigation steps.
    agents_to_invoke    : Subset of signal names the Planner chose to activate.
                          Valid values: "metrics", "logs", "traces",
                          "profiles", "frontend", "k8s".
    investigation_questions : Per-agent focused questions from the Planner.

    Accumulated fields (LangGraph merges these across branches)
    -----------------------------------------------------------
    messages            : Full chat message history (HumanMessage / AIMessage).
    tool_calls          : All tool call records across all agents.
                          Each record: {tool_name, query, result, duration_ms,
                          agent, success, timestamp}.

    Signal findings
    ---------------
    findings            : SignalFindings dict; each key is set by its agent.

    Output fields
    -------------
    rca                 : Markdown Root Cause Analysis produced by Synthesizer.
    confidence          : Synthesizer confidence score 0.0–1.0.
    recommended_actions : Immediate / short-term / long-term action items.
    affected_user_count : Estimated number of affected users (from Faro).
    status              : Workflow lifecycle state.
                          Values: planning | investigating | synthesizing | complete | failed
    error               : Error message if something went catastrophically wrong.
    """

    # --- Input ---
    incident_id: str
    query: str
    affected_services: list[str]
    alert_context: dict
    time_window: dict  # {"start": ..., "end": ...}

    # --- Planner output ---
    plan: list[str]
    agents_to_invoke: list[str]
    investigation_questions: dict  # {"metrics": "...", "logs": "...", ...}
    hypothesis: str

    # --- Accumulated (reducer = operator.add means LangGraph appends) ---
    messages: Annotated[list, operator.add]
    tool_calls: Annotated[list, operator.add]

    # --- Per-signal findings ---
    findings: SignalFindings

    # --- Final output ---
    rca: Optional[str]
    confidence: float
    recommended_actions: list[str]
    affected_user_count: Optional[int]
    status: str   # planning | investigating | synthesizing | complete | failed
    error: Optional[str]
