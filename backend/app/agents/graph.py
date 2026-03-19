"""
NovaSRE — LangGraph Investigation Graph

Defines the multi-agent investigation workflow as a LangGraph StateGraph.

Graph topology
--------------
                        ┌─────────┐
                        │ planner │  (entry point)
                        └────┬────┘
                             │ route_from_planner() — fan-out via Send API
               ┌─────────────┼──────────────────────┐
               │             │          │            │ ...
        ┌──────▼──┐   ┌──────▼──┐  ┌───▼──────┐ ┌──▼──────┐
        │ metrics │   │  logs   │  │ traces   │ │profiles │ ...
        └──────┬──┘   └──────┬──┘  └───┬──────┘ └──┬──────┘
               └─────────────┴──────────┴────────────┘
                                    │ all converge
                              ┌─────▼──────┐
                              │synthesizer │
                              └─────┬──────┘
                                    │
                                   END

Parallel execution
------------------
The router uses the LangGraph ``Send`` API to dispatch multiple specialist
agents in parallel when the Planner identifies more than one signal source to
investigate.  Each Send carries a copy of the full state so agents can read
incident context; their findings are merged back via the ``operator.add``
reducer on ``tool_calls`` and the ``findings`` dict.
"""

from __future__ import annotations

import structlog
from langgraph.graph import END, StateGraph
from langgraph.types import Send

from app.agents.state import InvestigationState

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Import all node functions
# ---------------------------------------------------------------------------

from app.agents.planner import planner_node
from app.agents.metrics_agent import metrics_node
from app.agents.logs_agent import logs_node
from app.agents.traces_agent import traces_node
from app.agents.profiles_agent import profiles_node
from app.agents.frontend_agent import frontend_node
from app.agents.k8s_agent import k8s_node
from app.agents.synthesizer import synthesizer_node

# Map agent name strings → node functions
_AGENT_NODE_MAP = {
    "metrics": "metrics_agent",
    "logs": "logs_agent",
    "traces": "traces_agent",
    "profiles": "profiles_agent",
    "frontend": "frontend_agent",
    "k8s": "k8s_agent",
}


# ---------------------------------------------------------------------------
# Router: planner → specialist agents (fan-out via Send API)
# ---------------------------------------------------------------------------

def route_from_planner(state: InvestigationState) -> list[Send] | str:
    """
    Conditional edge function called after the planner node completes.

    Reads ``state["agents_to_invoke"]`` and returns a list of ``Send``
    objects, one per agent, so LangGraph can execute them in parallel.

    If no agents are selected (empty plan or error) we skip straight to
    the synthesizer.

    Returns
    -------
    list[Send]
        Each Send targets a specialist agent node and passes the full state.
    str
        ``"synthesizer"`` if no agents were selected.
    """
    agents = state.get("agents_to_invoke", [])

    if not agents:
        log.warning(
            "graph.router.no_agents",
            incident_id=state.get("incident_id"),
            reason="Planner returned empty agents_to_invoke; routing to synthesizer",
        )
        return "synthesizer"

    sends = []
    for agent_name in agents:
        node_name = _AGENT_NODE_MAP.get(agent_name)
        if node_name:
            log.info(
                "graph.router.send",
                agent=agent_name,
                node=node_name,
                incident_id=state.get("incident_id"),
            )
            sends.append(Send(node_name, state))
        else:
            log.warning(
                "graph.router.unknown_agent",
                agent=agent_name,
                incident_id=state.get("incident_id"),
            )

    if not sends:
        return "synthesizer"

    return sends


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_investigation_graph() -> StateGraph:
    """
    Build and compile the NovaSRE investigation StateGraph.

    Returns
    -------
    CompiledStateGraph
        Ready-to-invoke compiled graph.  Use ``await graph.ainvoke(state)``
        for async execution or ``graph.invoke(state)`` for sync.
    """
    graph = StateGraph(InvestigationState)

    # --- Register nodes ---
    graph.add_node("planner", planner_node)
    graph.add_node("metrics_agent", metrics_node)
    graph.add_node("logs_agent", logs_node)
    graph.add_node("traces_agent", traces_node)
    graph.add_node("profiles_agent", profiles_node)
    graph.add_node("frontend_agent", frontend_node)
    graph.add_node("k8s_agent", k8s_node)
    graph.add_node("synthesizer", synthesizer_node)

    # --- Entry point ---
    graph.set_entry_point("planner")

    # --- Conditional fan-out from planner ---
    # route_from_planner returns either a list[Send] (parallel dispatch)
    # or the string "synthesizer" (skip straight to synthesis).
    graph.add_conditional_edges(
        "planner",
        route_from_planner,
        # Path map: maps string return values to node names.
        # Send objects bypass this map and go directly to their targets.
        {
            "synthesizer": "synthesizer",
        },
    )

    # --- All specialist agents converge on synthesizer ---
    for agent_node in [
        "metrics_agent",
        "logs_agent",
        "traces_agent",
        "profiles_agent",
        "frontend_agent",
        "k8s_agent",
    ]:
        graph.add_edge(agent_node, "synthesizer")

    # --- Synthesizer → END ---
    graph.add_edge("synthesizer", END)

    compiled = graph.compile()

    log.info(
        "graph.compiled",
        nodes=list(_AGENT_NODE_MAP.keys()) + ["planner", "synthesizer"],
    )

    return compiled
