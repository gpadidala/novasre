"""
Integration tests for the full LangGraph investigation graph.

All LLM calls and all tool HTTP calls are mocked so these tests run
without external services.  They verify the graph wiring, state flow,
and graceful handling of partial failures.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agents.graph import build_investigation_graph, route_from_planner
from app.agents.state import InvestigationState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _no_tool_ai_response(content: str) -> AIMessage:
    """Create a mock AIMessage with no tool calls (agent finished reasoning)."""
    msg = MagicMock(spec=AIMessage)
    msg.content = content
    msg.tool_calls = []
    return msg


def _make_base_state(**overrides) -> InvestigationState:
    base: InvestigationState = {
        "incident_id": "graph-test-001",
        "query": "High error rate on checkout service",
        "affected_services": ["checkout"],
        "alert_context": {},
        "time_window": {"start": "now-1h", "end": "now"},
        "messages": [],
        "tool_calls": [],
        "findings": {},
        "confidence": 0.0,
        "recommended_actions": [],
        "status": "planning",
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


METRICS_FINDINGS_JSON = json.dumps({
    "services": {
        "checkout": {
            "error_rate_rps": 0.12,
            "error_rate_pct": 12.3,
            "request_rate_rps": 0.97,
            "p99_latency_ms": 8200.0,
            "anomaly_detected": True,
            "anomaly_description": "Error rate 40x above baseline",
        }
    },
    "summary": "Checkout error rate is 12.3%, P99 latency is 8.2s — both far above baseline.",
    "severity_assessment": "critical",
    "slo_breach": True,
})

LOGS_FINDINGS_JSON = json.dumps({
    "services": {
        "checkout": {
            "total_error_lines": 342,
            "unique_error_patterns": 3,
            "top_errors": [
                {"pattern": "ERROR: DB connection refused", "count": 290, "example": "ERROR: DB connection refused after 30s"},
                {"pattern": "ERROR: connection pool exhausted", "count": 52, "example": "ERROR: all 10 connections in use"},
            ],
            "anomaly_detected": True,
        }
    },
    "root_cause_indicators": ["DB connection refused", "connection pool exhausted"],
    "summary": "3 unique error patterns found; DB connection errors dominate.",
    "cascading_failure_detected": False,
})

TRACES_FINDINGS_JSON = json.dumps({
    "services": {
        "checkout": {
            "slow_trace_count": 45,
            "slowest_trace_ms": 9800.0,
            "error_trace_count": 38,
            "hottest_span": {
                "service": "postgres",
                "operation": "SELECT orders",
                "duration_ms": 7800.0,
                "pct_of_trace": 79.6,
            },
            "anomaly_detected": True,
        }
    },
    "bottleneck_service": "postgres",
    "bottleneck_operation": "SELECT orders",
    "summary": "79% of trace duration is in the postgres SELECT orders span.",
    "trace_pattern": "db_slowdown",
})

SYNTHESIZER_RESPONSE = """---MARKDOWN START---
## Incident Summary
The checkout service experienced a 12.3% error rate and P99 latency of 8.2s starting approximately 14:30 UTC, affecting customer orders.

## Signal Evidence

### Metrics (Mimir)
- Error rate: 12.3% (40x above baseline of ~0.3%)
- P99 latency: 8.2s (up from 180ms baseline)
- Request rate unchanged at ~1 req/s (no traffic spike)

### Logs (Loki)
- 342 error lines in the window, 3 unique patterns
- Primary pattern: "DB connection refused" (290 occurrences)
- Secondary pattern: "connection pool exhausted" (52 occurrences)

### Traces (Tempo)
- 45 slow traces, slowest at 9.8s
- Bottleneck: postgres "SELECT orders" span consuming 79% of trace time

### Profiles (Pyroscope)
No data collected.

### Frontend (Faro)
No data collected.

### Kubernetes
No data collected.

## Root Cause
**The PostgreSQL connection pool for the checkout service became exhausted, causing cascading DB connection refusals.**

The DB span in traces accounts for 79% of request latency. Log errors confirm "connection pool exhausted". Metrics show the error rate spike correlates precisely with the start of DB connection errors in logs.

**Evidence Confidence:** High

## User Impact
- **Affected Sessions:** Unknown
- **Error Rate:** 12.3% of requests
- **Duration:** ~30 minutes (14:30–15:00 UTC estimated)
- **Affected Features:** Order placement, order status

## Recommended Actions

### Immediate (do now)
1. Increase PostgreSQL connection pool size from 10 to 50 in checkout service config.
2. Restart checkout service pods to clear stuck connections.
3. Check PostgreSQL server for long-running queries holding connections.

### Short-term (next 24 hours)
1. Add connection pool monitoring alert (alert when pool > 80% utilised).
2. Implement connection pool circuit breaker in checkout service.
3. Review and optimise the "SELECT orders" query for index usage.

### Long-term (prevent recurrence)
1. Implement PgBouncer connection pooling to reduce direct DB connections.
2. Add chaos engineering tests for DB connection exhaustion scenarios.
3. Review all services for connection pool sizing and add runbook.

## Investigation Timeline
- 14:30 UTC: First DB connection errors appear in logs
- 14:31 UTC: Error rate begins climbing from 0.3% to 12.3%
- 14:35 UTC: P99 latency exceeds 8s
- 14:32–15:00 UTC: Incident persists
---MARKDOWN END---

```json
{
  "confidence": 0.91,
  "root_cause_category": "db_connection",
  "recommended_actions": [
    "Increase PostgreSQL connection pool size",
    "Restart checkout service pods",
    "Add connection pool monitoring alert",
    "Implement PgBouncer connection pooling"
  ],
  "affected_user_count": null,
  "signals_used": ["metrics", "logs", "traces"]
}
```"""


# ---------------------------------------------------------------------------
# Unit tests — route_from_planner
# ---------------------------------------------------------------------------

class TestRouteFRomPlanner:
    def test_routes_to_correct_nodes_for_metrics_logs(self):
        """route_from_planner should return Send objects for each agent."""
        from langgraph.types import Send

        state = _make_base_state(agents_to_invoke=["metrics", "logs"])
        result = route_from_planner(state)

        assert isinstance(result, list)
        assert len(result) == 2
        node_names = [s.node for s in result]
        assert "metrics_agent" in node_names
        assert "logs_agent" in node_names

    def test_routes_to_synthesizer_when_no_agents(self):
        """Empty agents_to_invoke should route directly to synthesizer."""
        state = _make_base_state(agents_to_invoke=[])
        result = route_from_planner(state)
        assert result == "synthesizer"

    def test_routes_to_synthesizer_when_agents_not_set(self):
        """Missing agents_to_invoke should route directly to synthesizer."""
        state = _make_base_state()
        # Remove agents_to_invoke
        state.pop("agents_to_invoke", None)  # type: ignore[misc]
        result = route_from_planner(state)
        assert result == "synthesizer"

    def test_ignores_unknown_agent_names(self):
        """Unknown agent names should be silently skipped."""
        from langgraph.types import Send

        state = _make_base_state(agents_to_invoke=["metrics", "unknown_agent"])
        result = route_from_planner(state)

        # Only metrics should produce a Send
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].node == "metrics_agent"

    def test_all_six_agents_produce_sends(self):
        """All six valid agent names should produce Send objects."""
        from langgraph.types import Send

        state = _make_base_state(
            agents_to_invoke=["metrics", "logs", "traces", "profiles", "frontend", "k8s"]
        )
        result = route_from_planner(state)
        assert isinstance(result, list)
        assert len(result) == 6


# ---------------------------------------------------------------------------
# Graph structure tests
# ---------------------------------------------------------------------------

class TestBuildInvestigationGraph:
    def test_graph_compiles_without_error(self):
        """build_investigation_graph should not raise during compilation."""
        graph = build_investigation_graph()
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        """The compiled graph should contain all expected node names."""
        graph = build_investigation_graph()
        # LangGraph compiled graphs expose get_graph() for inspection
        graph_repr = graph.get_graph()
        node_ids = set(graph_repr.nodes.keys())

        for expected in [
            "planner",
            "metrics_agent",
            "logs_agent",
            "traces_agent",
            "profiles_agent",
            "frontend_agent",
            "k8s_agent",
            "synthesizer",
        ]:
            assert expected in node_ids, f"Node '{expected}' not found in graph"


# ---------------------------------------------------------------------------
# Full integration tests — graph with mocked LLM and tools
# ---------------------------------------------------------------------------

class TestFullInvestigationGraph:
    """End-to-end graph tests with all LLMs and tools mocked."""

    def _mock_planner_llm(self) -> MagicMock:
        """Create a mock ChatOpenAI that returns the planner JSON."""
        mock = AsyncMock()
        planner_response = json.dumps({
            "agents_to_invoke": ["metrics", "logs", "traces"],
            "time_window": {"start": "now-1h", "end": "now"},
            "investigation_questions": {
                "metrics": "What are the RED metrics for checkout?",
                "logs": "What errors are in checkout logs?",
                "traces": "Which trace span is the bottleneck?",
            },
            "hypothesis": "DB connection pool issue.",
            "priority": "metrics → traces → logs",
            "plan": [
                "1. Query RED metrics",
                "2. Extract log errors",
                "3. Find slow traces",
                "4. Synthesise RCA",
            ],
        })
        msg = _no_tool_ai_response(planner_response)
        mock.ainvoke = AsyncMock(return_value=msg)
        return mock

    def _mock_specialist_llm(self, findings_json: str) -> MagicMock:
        """Create a mock ChatOpenAI that returns specialist agent findings."""
        mock = AsyncMock()
        mock.ainvoke = AsyncMock(return_value=_no_tool_ai_response(f"```json\n{findings_json}\n```"))
        # bind_tools returns a new mock that also has ainvoke
        bound = AsyncMock()
        bound.ainvoke = mock.ainvoke
        mock.bind_tools = MagicMock(return_value=bound)
        return mock

    def _mock_synthesizer_llm(self) -> MagicMock:
        """Create a mock ChatOpenAI for the synthesizer."""
        mock = AsyncMock()
        mock.ainvoke = AsyncMock(return_value=_no_tool_ai_response(SYNTHESIZER_RESPONSE))
        return mock

    @pytest.mark.asyncio
    async def test_full_investigation_produces_rca(self):
        """
        Full graph test: planner → metrics + logs + traces → synthesizer → RCA.

        All LLMs are mocked.  Verifies the graph runs end-to-end and produces
        a non-empty RCA with confidence > 0.
        """
        graph = build_investigation_graph()
        state = _make_base_state()

        planner_llm = self._mock_planner_llm()
        metrics_llm = self._mock_specialist_llm(METRICS_FINDINGS_JSON)
        logs_llm = self._mock_specialist_llm(LOGS_FINDINGS_JSON)
        traces_llm = self._mock_specialist_llm(TRACES_FINDINGS_JSON)
        synth_llm = self._mock_synthesizer_llm()

        # We patch ChatOpenAI at module level for each agent
        patches = [
            patch("app.agents.planner.ChatOpenAI", return_value=planner_llm),
            patch("app.agents.metrics_agent.ChatOpenAI", return_value=metrics_llm),
            patch("app.agents.logs_agent.ChatOpenAI", return_value=logs_llm),
            patch("app.agents.traces_agent.ChatOpenAI", return_value=traces_llm),
            patch("app.agents.synthesizer.ChatOpenAI", return_value=synth_llm),
        ]

        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = await graph.ainvoke(state)

        assert result is not None
        assert result.get("rca") is not None
        assert len(result["rca"]) > 100
        assert "Root Cause" in result["rca"]
        assert result.get("confidence", 0) > 0
        assert result.get("status") == "complete"

    @pytest.mark.asyncio
    async def test_graph_completes_with_status_complete(self):
        """The graph should always set status='complete' on the happy path."""
        graph = build_investigation_graph()
        state = _make_base_state()

        planner_llm = self._mock_planner_llm()
        metrics_llm = self._mock_specialist_llm(METRICS_FINDINGS_JSON)
        logs_llm = self._mock_specialist_llm(LOGS_FINDINGS_JSON)
        traces_llm = self._mock_specialist_llm(TRACES_FINDINGS_JSON)
        synth_llm = self._mock_synthesizer_llm()

        patches = [
            patch("app.agents.planner.ChatOpenAI", return_value=planner_llm),
            patch("app.agents.metrics_agent.ChatOpenAI", return_value=metrics_llm),
            patch("app.agents.logs_agent.ChatOpenAI", return_value=logs_llm),
            patch("app.agents.traces_agent.ChatOpenAI", return_value=traces_llm),
            patch("app.agents.synthesizer.ChatOpenAI", return_value=synth_llm),
        ]

        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = await graph.ainvoke(state)

        assert result["status"] == "complete"

    @pytest.mark.asyncio
    async def test_graph_collects_tool_calls_from_all_agents(self):
        """Tool calls from all agents should be accumulated in state.tool_calls."""
        graph = build_investigation_graph()
        state = _make_base_state()

        planner_llm = self._mock_planner_llm()
        metrics_llm = self._mock_specialist_llm(METRICS_FINDINGS_JSON)
        logs_llm = self._mock_specialist_llm(LOGS_FINDINGS_JSON)
        traces_llm = self._mock_specialist_llm(TRACES_FINDINGS_JSON)
        synth_llm = self._mock_synthesizer_llm()

        patches = [
            patch("app.agents.planner.ChatOpenAI", return_value=planner_llm),
            patch("app.agents.metrics_agent.ChatOpenAI", return_value=metrics_llm),
            patch("app.agents.logs_agent.ChatOpenAI", return_value=logs_llm),
            patch("app.agents.traces_agent.ChatOpenAI", return_value=traces_llm),
            patch("app.agents.synthesizer.ChatOpenAI", return_value=synth_llm),
        ]

        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = await graph.ainvoke(state)

        # Should have tool calls from planner + synthesizer at minimum
        tool_calls = result.get("tool_calls", [])
        assert len(tool_calls) >= 2  # planner_llm + synthesizer_llm

        agent_names = {tc.get("agent") for tc in tool_calls}
        assert "planner" in agent_names
        assert "synthesizer" in agent_names

    @pytest.mark.asyncio
    async def test_graph_handles_planner_fallback(self):
        """
        When the planner LLM returns garbage JSON, the graph should fall back
        to all agents and still complete.
        """
        graph = build_investigation_graph()
        state = _make_base_state()

        # Planner returns invalid JSON → triggers fallback (all 6 agents)
        bad_planner_llm = AsyncMock()
        bad_planner_llm.ainvoke = AsyncMock(
            return_value=_no_tool_ai_response("I will investigate this incident carefully.")
        )

        # All specialist agents return empty findings (fast path — no tool calls needed)
        empty_findings = json.dumps({"summary": "No issues detected.", "anomaly_detected": False})
        specialist_llm = self._mock_specialist_llm(empty_findings)
        synth_llm = self._mock_synthesizer_llm()

        patches = [
            patch("app.agents.planner.ChatOpenAI", return_value=bad_planner_llm),
            patch("app.agents.metrics_agent.ChatOpenAI", return_value=specialist_llm),
            patch("app.agents.logs_agent.ChatOpenAI", return_value=specialist_llm),
            patch("app.agents.traces_agent.ChatOpenAI", return_value=specialist_llm),
            patch("app.agents.profiles_agent.ChatOpenAI", return_value=specialist_llm),
            patch("app.agents.frontend_agent.ChatOpenAI", return_value=specialist_llm),
            patch("app.agents.k8s_agent.ChatOpenAI", return_value=specialist_llm),
            patch("app.agents.synthesizer.ChatOpenAI", return_value=synth_llm),
        ]

        with (
            patches[0], patches[1], patches[2], patches[3],
            patches[4], patches[5], patches[6], patches[7]
        ):
            result = await graph.ainvoke(state)

        # Should still complete
        assert result is not None
        assert result.get("status") == "complete"

    @pytest.mark.asyncio
    async def test_graph_with_single_agent_metrics_only(self):
        """Graph should work when only the metrics agent is invoked."""
        graph = build_investigation_graph()
        state = _make_base_state()

        planner_response = json.dumps({
            "agents_to_invoke": ["metrics"],
            "time_window": {"start": "now-1h", "end": "now"},
            "investigation_questions": {"metrics": "Check error rate for checkout."},
            "hypothesis": "High error rate.",
            "priority": "metrics",
            "plan": ["1. Query metrics", "2. Synthesise"],
        })

        planner_llm = AsyncMock()
        planner_llm.ainvoke = AsyncMock(return_value=_no_tool_ai_response(planner_response))

        metrics_llm = self._mock_specialist_llm(METRICS_FINDINGS_JSON)
        synth_llm = self._mock_synthesizer_llm()

        patches = [
            patch("app.agents.planner.ChatOpenAI", return_value=planner_llm),
            patch("app.agents.metrics_agent.ChatOpenAI", return_value=metrics_llm),
            patch("app.agents.synthesizer.ChatOpenAI", return_value=synth_llm),
        ]

        with patches[0], patches[1], patches[2]:
            result = await graph.ainvoke(state)

        assert result.get("status") == "complete"
        # Metrics findings should be populated
        assert result.get("findings", {}).get("metrics") is not None

    @pytest.mark.asyncio
    async def test_graph_rca_contains_root_cause_section(self):
        """The produced RCA markdown must contain a Root Cause section."""
        graph = build_investigation_graph()
        state = _make_base_state()

        planner_llm = self._mock_planner_llm()
        metrics_llm = self._mock_specialist_llm(METRICS_FINDINGS_JSON)
        logs_llm = self._mock_specialist_llm(LOGS_FINDINGS_JSON)
        traces_llm = self._mock_specialist_llm(TRACES_FINDINGS_JSON)
        synth_llm = self._mock_synthesizer_llm()

        patches = [
            patch("app.agents.planner.ChatOpenAI", return_value=planner_llm),
            patch("app.agents.metrics_agent.ChatOpenAI", return_value=metrics_llm),
            patch("app.agents.logs_agent.ChatOpenAI", return_value=logs_llm),
            patch("app.agents.traces_agent.ChatOpenAI", return_value=traces_llm),
            patch("app.agents.synthesizer.ChatOpenAI", return_value=synth_llm),
        ]

        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = await graph.ainvoke(state)

        rca = result.get("rca", "")
        assert "Root Cause" in rca
        assert "Incident Summary" in rca
        assert "Recommended Actions" in rca

    @pytest.mark.asyncio
    async def test_graph_confidence_is_valid_float(self):
        """Synthesizer confidence should be a float between 0 and 1."""
        graph = build_investigation_graph()
        state = _make_base_state()

        planner_llm = self._mock_planner_llm()
        metrics_llm = self._mock_specialist_llm(METRICS_FINDINGS_JSON)
        logs_llm = self._mock_specialist_llm(LOGS_FINDINGS_JSON)
        traces_llm = self._mock_specialist_llm(TRACES_FINDINGS_JSON)
        synth_llm = self._mock_synthesizer_llm()

        patches = [
            patch("app.agents.planner.ChatOpenAI", return_value=planner_llm),
            patch("app.agents.metrics_agent.ChatOpenAI", return_value=metrics_llm),
            patch("app.agents.logs_agent.ChatOpenAI", return_value=logs_llm),
            patch("app.agents.traces_agent.ChatOpenAI", return_value=traces_llm),
            patch("app.agents.synthesizer.ChatOpenAI", return_value=synth_llm),
        ]

        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = await graph.ainvoke(state)

        confidence = result.get("confidence", -1)
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0


# ---------------------------------------------------------------------------
# Synthesizer unit tests
# ---------------------------------------------------------------------------

class TestSynthesizerParsing:
    """Unit tests for the synthesizer response parser."""

    def test_parses_markdown_with_markers(self):
        """Should extract markdown from ---MARKDOWN START/END--- markers."""
        from app.agents.synthesizer import _parse_synthesizer_response

        rca, meta = _parse_synthesizer_response(SYNTHESIZER_RESPONSE)
        assert "Incident Summary" in rca
        assert "Root Cause" in rca
        assert meta["confidence"] == 0.91
        assert meta["root_cause_category"] == "db_connection"

    def test_parses_confidence_from_json(self):
        """Confidence should be extracted from the JSON metadata block."""
        from app.agents.synthesizer import _parse_synthesizer_response

        _, meta = _parse_synthesizer_response(SYNTHESIZER_RESPONSE)
        assert meta["confidence"] == pytest.approx(0.91)

    def test_handles_missing_markers_gracefully(self):
        """Should handle responses without MARKDOWN START/END markers."""
        from app.agents.synthesizer import _parse_synthesizer_response

        content = "## Root Cause\nThe database failed.\n```json\n{\"confidence\": 0.7}\n```"
        rca, meta = _parse_synthesizer_response(content)
        assert "Root Cause" in rca
        assert meta["confidence"] == 0.7

    def test_handles_completely_invalid_response(self):
        """Should not raise on completely invalid content."""
        from app.agents.synthesizer import _parse_synthesizer_response

        rca, meta = _parse_synthesizer_response("random text with no structure")
        assert isinstance(rca, str)
        assert isinstance(meta, dict)
        assert 0.0 <= meta.get("confidence", 0.5) <= 1.0


class TestSynthesizerNode:
    """Integration tests for the synthesizer_node function."""

    @pytest.mark.asyncio
    async def test_synthesizer_node_produces_rca(self):
        """synthesizer_node should call the LLM and return rca + confidence."""
        from app.agents.synthesizer import synthesizer_node

        state = _make_base_state(
            findings={
                "metrics": json.loads(METRICS_FINDINGS_JSON),
                "logs": json.loads(LOGS_FINDINGS_JSON),
                "traces": json.loads(TRACES_FINDINGS_JSON),
            },
            agents_to_invoke=["metrics", "logs", "traces"],
            plan=["1. Query metrics", "2. Query logs", "3. Synthesise"],
            hypothesis="DB connection pool exhaustion.",
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=_no_tool_ai_response(SYNTHESIZER_RESPONSE)
        )

        with patch("app.agents.synthesizer.ChatOpenAI", return_value=mock_llm):
            result = await synthesizer_node(state)

        assert result["rca"] is not None
        assert "Root Cause" in result["rca"]
        assert result["confidence"] == pytest.approx(0.91)
        assert result["status"] == "complete"
        assert len(result["recommended_actions"]) > 0

    @pytest.mark.asyncio
    async def test_synthesizer_handles_llm_error(self):
        """synthesizer_node should produce fallback RCA on LLM exception."""
        from app.agents.synthesizer import synthesizer_node

        state = _make_base_state(
            findings={"metrics": {"summary": "12% error rate"}},
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("OpenAI rate limit"))

        with patch("app.agents.synthesizer.ChatOpenAI", return_value=mock_llm):
            result = await synthesizer_node(state)

        # Should not raise; should return something
        assert result is not None
        assert result.get("status") == "complete"
        assert result.get("rca") is not None

    @pytest.mark.asyncio
    async def test_synthesizer_sets_affected_user_count_from_metadata(self):
        """If metadata contains affected_user_count, it should be set in state."""
        from app.agents.synthesizer import synthesizer_node

        response_with_users = SYNTHESIZER_RESPONSE.replace(
            '"affected_user_count": null',
            '"affected_user_count": 2400'
        )

        state = _make_base_state(
            findings={"metrics": json.loads(METRICS_FINDINGS_JSON)},
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=_no_tool_ai_response(response_with_users)
        )

        with patch("app.agents.synthesizer.ChatOpenAI", return_value=mock_llm):
            result = await synthesizer_node(state)

        assert result.get("affected_user_count") == 2400
