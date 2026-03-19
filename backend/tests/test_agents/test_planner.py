"""
Tests for the Planner agent.

All LLM calls are mocked so these tests run without an OpenAI API key
and execute in milliseconds.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agents.planner import _default_plan, _all_agents, planner_node
from app.agents.state import InvestigationState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_PLANNER_JSON = {
    "agents_to_invoke": ["metrics", "logs", "traces"],
    "time_window": {"start": "now-1h", "end": "now"},
    "investigation_questions": {
        "metrics": "What is the error rate and P99 latency for checkout?",
        "logs": "What errors appear in checkout logs?",
        "traces": "Which span is the bottleneck in checkout traces?",
    },
    "hypothesis": "DB connection pool exhaustion causing checkout errors.",
    "priority": "metrics → traces → logs",
    "plan": [
        "1. Query RED metrics for checkout service",
        "2. Extract error log patterns",
        "3. Find slow traces",
        "4. Synthesise RCA",
    ],
}


def _make_ai_response(content: str) -> AIMessage:
    """Helper to create a mock AIMessage."""
    msg = MagicMock(spec=AIMessage)
    msg.content = content
    msg.tool_calls = []
    return msg


def _make_base_state(**overrides) -> InvestigationState:
    """Build a minimal valid InvestigationState for testing."""
    base: InvestigationState = {
        "incident_id": "test-inc-001",
        "query": "High error rate on checkout service",
        "affected_services": ["checkout"],
        "alert_context": {"alertname": "HighErrorRate", "severity": "critical"},
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


# ---------------------------------------------------------------------------
# Unit tests — _default_plan helper
# ---------------------------------------------------------------------------

class TestDefaultPlan:
    def test_returns_all_agents(self):
        plan = _default_plan("some query", {"start": "now-1h", "end": "now"})
        assert set(plan["agents_to_invoke"]) == {"metrics", "logs", "traces", "profiles", "frontend", "k8s"}

    def test_preserves_time_window(self):
        tw = {"start": "now-2h", "end": "now-30m"}
        plan = _default_plan("query", tw)
        assert plan["time_window"] == tw

    def test_includes_hypothesis(self):
        plan = _default_plan("query", {})
        assert "hypothesis" in plan
        assert len(plan["hypothesis"]) > 0

    def test_includes_investigation_questions_for_all_agents(self):
        plan = _default_plan("high error rate", {})
        for agent in _all_agents():
            assert agent in plan["investigation_questions"]
            assert "high error rate" in plan["investigation_questions"][agent]


class TestAllAgents:
    def test_returns_six_agents(self):
        agents = _all_agents()
        assert len(agents) == 6

    def test_contains_expected_agents(self):
        agents = _all_agents()
        for expected in ["metrics", "logs", "traces", "profiles", "frontend", "k8s"]:
            assert expected in agents


# ---------------------------------------------------------------------------
# Integration tests — planner_node with mocked LLM
# ---------------------------------------------------------------------------

class TestPlannerNode:
    @pytest.mark.asyncio
    async def test_planner_parses_valid_llm_response(self):
        """Planner should correctly parse a valid JSON response from the LLM."""
        state = _make_base_state()

        with patch("app.agents.planner.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(
                return_value=_make_ai_response(json.dumps(VALID_PLANNER_JSON))
            )
            mock_llm_class.return_value = mock_llm

            result = await planner_node(state)

        assert result["agents_to_invoke"] == ["metrics", "logs", "traces"]
        assert result["status"] == "investigating"
        assert len(result["plan"]) == 4
        assert result["hypothesis"] == "DB connection pool exhaustion causing checkout errors."
        assert result["time_window"] == {"start": "now-1h", "end": "now"}

    @pytest.mark.asyncio
    async def test_planner_handles_json_in_markdown_fence(self):
        """Planner should strip markdown fences from the LLM response."""
        state = _make_base_state()
        fenced = f"```json\n{json.dumps(VALID_PLANNER_JSON)}\n```"

        with patch("app.agents.planner.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=_make_ai_response(fenced))
            mock_llm_class.return_value = mock_llm

            result = await planner_node(state)

        assert result["agents_to_invoke"] == ["metrics", "logs", "traces"]

    @pytest.mark.asyncio
    async def test_planner_falls_back_on_invalid_json(self):
        """Planner should activate all agents when LLM returns non-JSON."""
        state = _make_base_state()

        with patch("app.agents.planner.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(
                return_value=_make_ai_response("I will investigate all the signals.")
            )
            mock_llm_class.return_value = mock_llm

            result = await planner_node(state)

        # Fallback activates all agents
        assert set(result["agents_to_invoke"]) == {
            "metrics", "logs", "traces", "profiles", "frontend", "k8s"
        }
        assert result["status"] == "investigating"

    @pytest.mark.asyncio
    async def test_planner_falls_back_on_llm_exception(self):
        """Planner should activate all agents when LLM call raises."""
        state = _make_base_state()

        with patch("app.agents.planner.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(side_effect=Exception("OpenAI timeout"))
            mock_llm_class.return_value = mock_llm

            result = await planner_node(state)

        assert set(result["agents_to_invoke"]) == {
            "metrics", "logs", "traces", "profiles", "frontend", "k8s"
        }
        assert result["status"] == "investigating"

    @pytest.mark.asyncio
    async def test_planner_filters_unknown_agent_names(self):
        """Planner should discard any agent names not in the valid set."""
        state = _make_base_state()
        invalid_plan = {**VALID_PLANNER_JSON, "agents_to_invoke": ["metrics", "invalid_agent", "logs"]}

        with patch("app.agents.planner.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=_make_ai_response(json.dumps(invalid_plan)))
            mock_llm_class.return_value = mock_llm

            result = await planner_node(state)

        assert "invalid_agent" not in result["agents_to_invoke"]
        assert "metrics" in result["agents_to_invoke"]
        assert "logs" in result["agents_to_invoke"]

    @pytest.mark.asyncio
    async def test_planner_adds_tool_call_record(self):
        """Planner should add a tool_call record for its own LLM invocation."""
        state = _make_base_state()

        with patch("app.agents.planner.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=_make_ai_response(json.dumps(VALID_PLANNER_JSON)))
            mock_llm_class.return_value = mock_llm

            result = await planner_node(state)

        assert len(result["tool_calls"]) == 1
        tc = result["tool_calls"][0]
        assert tc["tool_name"] == "planner_llm"
        assert tc["agent"] == "planner"
        assert tc["success"] is True
        assert "duration_ms" in tc

    @pytest.mark.asyncio
    async def test_planner_populates_investigation_questions(self):
        """Planner should store the per-agent investigation questions."""
        state = _make_base_state()

        with patch("app.agents.planner.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=_make_ai_response(json.dumps(VALID_PLANNER_JSON)))
            mock_llm_class.return_value = mock_llm

            result = await planner_node(state)

        assert "investigation_questions" in result
        assert "metrics" in result["investigation_questions"]
        assert "checkout" in result["investigation_questions"]["metrics"].lower() or \
               "error" in result["investigation_questions"]["metrics"].lower()

    @pytest.mark.asyncio
    async def test_planner_respects_empty_agents_in_response_by_using_fallback(self):
        """If LLM returns empty agents_to_invoke, planner falls back to all agents."""
        state = _make_base_state()
        empty_plan = {**VALID_PLANNER_JSON, "agents_to_invoke": []}

        with patch("app.agents.planner.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=_make_ai_response(json.dumps(empty_plan)))
            mock_llm_class.return_value = mock_llm

            result = await planner_node(state)

        # Should fall back to all agents when list is empty after filtering
        assert len(result["agents_to_invoke"]) == 6

    @pytest.mark.asyncio
    async def test_planner_with_multiple_services(self):
        """Planner should work correctly with multiple affected services."""
        state = _make_base_state(
            query="Payment and checkout both returning 500s",
            affected_services=["checkout", "payment", "api-gateway"],
        )
        multi_plan = {
            **VALID_PLANNER_JSON,
            "investigation_questions": {
                "metrics": "Check error rates for checkout, payment, api-gateway",
                "logs": "Look for errors across checkout and payment logs",
                "traces": "Find traces spanning checkout → payment → api-gateway",
            },
        }

        with patch("app.agents.planner.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=_make_ai_response(json.dumps(multi_plan)))
            mock_llm_class.return_value = mock_llm

            result = await planner_node(state)

        # Should not crash with multiple services
        assert result["status"] == "investigating"
        assert len(result["agents_to_invoke"]) > 0
