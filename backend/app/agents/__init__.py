"""
NovaSRE — Multi-Agent Investigation System

This package implements the LangGraph-based multi-agent orchestration layer.
The investigation graph coordinates specialist agents (Metrics, Logs, Traces,
Profiles, Frontend, K8s) under a Planner orchestrator and synthesizes their
findings into a structured Root Cause Analysis report.

Public API
----------
build_investigation_graph   — Build and compile the LangGraph StateGraph
InvestigationState          — TypedDict for shared agent state
SignalFindings              — TypedDict for per-signal findings

Usage
-----
    from app.agents import build_investigation_graph, InvestigationState

    graph = build_investigation_graph()
    result: InvestigationState = await graph.ainvoke({
        "incident_id": "inc-001",
        "query": "High error rate on checkout service",
        "affected_services": ["checkout"],
        "alert_context": {},
        "time_window": {"start": "now-1h", "end": "now"},
    })
    print(result["rca"])
"""

from app.agents.graph import build_investigation_graph
from app.agents.state import InvestigationState, SignalFindings

__all__ = [
    "build_investigation_graph",
    "InvestigationState",
    "SignalFindings",
]
