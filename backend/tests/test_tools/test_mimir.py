"""
Tests for the Mimir tool implementations.

Uses ``respx`` to mock all HTTP calls — no live Mimir instance required.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx

from app.tools.base import ToolResult
from app.tools.mimir import (
    MimirLabelValuesTool,
    MimirQueryTool,
    MimirRangeTool,
    _parse_matrix,
    _parse_vector,
    get_error_rate,
    get_latency_p99,
    get_slo_burn_rate,
    get_throughput,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

MIMIR_BASE = "https://mimir.test.internal"

# Minimal Prometheus instant query response
VECTOR_RESPONSE: dict[str, Any] = {
    "status": "success",
    "data": {
        "resultType": "vector",
        "result": [
            {
                "metric": {"app": "checkout", "status": "500"},
                "value": [1710000000, "0.05"],
            }
        ],
    },
}

# Minimal Prometheus range query response
MATRIX_RESPONSE: dict[str, Any] = {
    "status": "success",
    "data": {
        "resultType": "matrix",
        "result": [
            {
                "metric": {"app": "checkout"},
                "values": [
                    [1710000000, "0.01"],
                    [1710000060, "0.02"],
                    [1710000120, "0.05"],
                ],
            }
        ],
    },
}

LABEL_VALUES_RESPONSE: dict[str, Any] = {
    "status": "success",
    "data": ["checkout", "payment", "inventory"],
}


def _mock_settings(base_url: str = MIMIR_BASE) -> dict:
    """Return a minimal settings dict for patching."""
    return {
        "mimir_url": base_url,
        "mimir_tenant_id": "test-tenant",
        "mimir_basic_auth_user": "",
        "mimir_basic_auth_password": "",
    }


# ---------------------------------------------------------------------------
# Unit tests — _parse_vector / _parse_matrix
# ---------------------------------------------------------------------------

class TestParseHelpers:
    def test_parse_vector_extracts_metric_and_value(self):
        raw = VECTOR_RESPONSE["data"]["result"]
        parsed = _parse_vector(raw)
        assert len(parsed) == 1
        assert parsed[0]["metric"] == {"app": "checkout", "status": "500"}
        assert parsed[0]["value"] == "0.05"
        assert parsed[0]["timestamp"] == 1710000000

    def test_parse_matrix_extracts_series(self):
        raw = MATRIX_RESPONSE["data"]["result"]
        parsed = _parse_matrix(raw)
        assert len(parsed) == 1
        series = parsed[0]
        assert series["metric"] == {"app": "checkout"}
        assert len(series["values"]) == 3
        assert series["values"][0] == {"timestamp": 1710000000, "value": "0.01"}

    def test_parse_vector_empty_result(self):
        assert _parse_vector([]) == []

    def test_parse_matrix_empty_result(self):
        assert _parse_matrix([]) == []


# ---------------------------------------------------------------------------
# MimirQueryTool tests
# ---------------------------------------------------------------------------

class TestMimirQueryTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_vector_result(self):
        """Successful instant query returns parsed vector data."""
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query").mock(
                return_value=httpx.Response(200, json=VECTOR_RESPONSE)
            )

            tool = MimirQueryTool()
            result = await tool.execute(query="rate(http_requests_total[5m])")

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.tool_name == "mimir_query"
        assert result.data["resultType"] == "vector"
        assert len(result.data["result"]) == 1
        assert result.data["result"][0]["value"] == "0.05"
        assert result.duration_ms >= 0
        assert result.query == "rate(http_requests_total[5m])"

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_with_time_parameter(self):
        """Query with explicit time parameter is forwarded correctly."""
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            route = respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query").mock(
                return_value=httpx.Response(200, json=VECTOR_RESPONSE)
            )

            tool = MimirQueryTool()
            result = await tool.execute(
                query="up", time="2024-03-17T10:00:00Z"
            )

        assert result.success is True
        # Verify the time was sent
        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_error_on_http_500(self):
        """HTTP 500 from Mimir results in a failed ToolResult, not an exception."""
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query").mock(
                return_value=httpx.Response(500, text="internal server error")
            )

            tool = MimirQueryTool()
            result = await tool.execute(query="up")

        assert result.success is False
        assert "500" in result.error

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_error_on_connection_failure(self):
        """Connection error results in a failed ToolResult."""
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )

            tool = MimirQueryTool()
            result = await tool.execute(query="up")

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_circuit_breaker_opens_after_three_failures(self):
        """After 3 consecutive failures the circuit breaker opens."""
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query").mock(
                return_value=httpx.Response(503, text="unavailable")
            )

            tool = MimirQueryTool()
            # Three failures
            for _ in range(3):
                await tool.execute(query="up")

        assert tool._cb.is_open is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_circuit_breaker_resets_on_success(self):
        """A successful call resets the circuit breaker."""
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            # Two failures then success
            respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query").mock(
                side_effect=[
                    httpx.Response(503, text="err"),
                    httpx.Response(503, text="err"),
                    httpx.Response(200, json=VECTOR_RESPONSE),
                ]
            )

            tool = MimirQueryTool()
            await tool.execute(query="up")
            await tool.execute(query="up")
            result = await tool.execute(query="up")

        assert result.success is True
        assert tool._cb.is_open is False
        assert tool._cb.failures == 0

    @pytest.mark.asyncio
    async def test_safe_execute_short_circuits_open_breaker(self):
        """safe_execute returns an error immediately when circuit is open."""
        tool = MimirQueryTool()
        tool._cb.failures = 3
        tool._cb.is_open = True

        result = await tool.safe_execute(query="up")
        assert result.success is False
        assert "Circuit breaker open" in result.error


# ---------------------------------------------------------------------------
# MimirRangeTool tests
# ---------------------------------------------------------------------------

class TestMimirRangeTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_matrix_result(self):
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=MATRIX_RESPONSE)
            )

            tool = MimirRangeTool()
            result = await tool.execute(
                query="rate(http_requests_total[5m])",
                start="now-1h",
                end="now",
                step="60s",
            )

        assert result.success is True
        assert result.tool_name == "mimir_query_range"
        assert result.data["resultType"] == "matrix"
        series = result.data["result"]
        assert len(series) == 1
        assert len(series[0]["values"]) == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_handles_empty_matrix(self):
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query_range").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "status": "success",
                        "data": {"resultType": "matrix", "result": []},
                    },
                )
            )

            tool = MimirRangeTool()
            result = await tool.execute(
                query="nonexistent_metric", start="now-1h", end="now"
            )

        assert result.success is True
        assert result.data["result"] == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_error_on_404(self):
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query_range").mock(
                return_value=httpx.Response(404, text="not found")
            )

            tool = MimirRangeTool()
            result = await tool.execute(
                query="up", start="now-1h", end="now"
            )

        assert result.success is False
        assert "404" in result.error


# ---------------------------------------------------------------------------
# MimirLabelValuesTool tests
# ---------------------------------------------------------------------------

class TestMimirLabelValuesTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_label_values(self):
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            respx.get(f"{MIMIR_BASE}/prometheus/api/v1/label/app/values").mock(
                return_value=httpx.Response(200, json=LABEL_VALUES_RESPONSE)
            )

            tool = MimirLabelValuesTool()
            result = await tool.execute(label_name="app")

        assert result.success is True
        assert result.tool_name == "mimir_label_values"
        assert result.data["label"] == "app"
        assert "checkout" in result.data["values"]
        assert "payment" in result.data["values"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_with_match_selector(self):
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            route = respx.get(
                f"{MIMIR_BASE}/prometheus/api/v1/label/app/values"
            ).mock(
                return_value=httpx.Response(200, json=LABEL_VALUES_RESPONSE)
            )

            tool = MimirLabelValuesTool()
            result = await tool.execute(
                label_name="app", match='{namespace="production"}'
            )

        assert result.success is True
        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_error_on_http_error(self):
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            respx.get(
                f"{MIMIR_BASE}/prometheus/api/v1/label/app/values"
            ).mock(return_value=httpx.Response(401, text="unauthorized"))

            tool = MimirLabelValuesTool()
            result = await tool.execute(label_name="app")

        assert result.success is False
        assert "401" in result.error


# ---------------------------------------------------------------------------
# Module-level helper function tests
# ---------------------------------------------------------------------------

class TestMimirHelpers:
    @pytest.mark.asyncio
    @respx.mock
    async def test_get_error_rate_uses_correct_promql(self):
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            route = respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query").mock(
                return_value=httpx.Response(200, json=VECTOR_RESPONSE)
            )

            result = await get_error_rate("checkout", window="5m")

        assert result.success is True
        assert "checkout" in result.query
        assert "5.." in result.query  # Status 5xx filter

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_latency_p99_uses_histogram_quantile(self):
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query").mock(
                return_value=httpx.Response(200, json=VECTOR_RESPONSE)
            )

            result = await get_latency_p99("checkout")

        assert result.success is True
        assert "0.99" in result.query
        assert "histogram_quantile" in result.query

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_throughput_uses_rate(self):
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query").mock(
                return_value=httpx.Response(200, json=VECTOR_RESPONSE)
            )

            result = await get_throughput("checkout")

        assert result.success is True
        assert "rate" in result.query
        assert "checkout" in result.query

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_slo_burn_rate_returns_structured_data(self):
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            # Two calls: 1h burn rate + 5m burn rate
            respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query").mock(
                return_value=httpx.Response(200, json=VECTOR_RESPONSE)
            )

            result = await get_slo_burn_rate("checkout", slo=99.9)

        assert result.tool_name == "mimir_slo_burn_rate"
        assert "service" in result.data
        assert result.data["service"] == "checkout"
        assert "slo_target" in result.data
        assert result.data["slo_target"] == 99.9
        assert "burn_rate_1h" in result.data
        assert "multi_window_alert_firing" in result.data

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_slo_burn_rate_detects_high_burn(self):
        """When burn rate > 14x error budget threshold, alert should fire."""
        with patch("app.tools.mimir.get_settings") as mock_settings:
            mock_settings.return_value.mimir_url = MIMIR_BASE
            mock_settings.return_value.mimir_tenant_id = "test"
            mock_settings.return_value.mimir_basic_auth_user = ""
            mock_settings.return_value.mimir_basic_auth_password = ""

            # SLO = 99.9%, error budget = 0.001, threshold = 14 * 0.001 = 0.014
            # Return burn rate of 0.05 (50x error budget — high burn)
            high_burn_response = {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {"metric": {}, "value": [1710000000, "0.05"]}
                    ],
                },
            }
            respx.post(f"{MIMIR_BASE}/prometheus/api/v1/query").mock(
                return_value=httpx.Response(200, json=high_burn_response)
            )

            result = await get_slo_burn_rate("checkout", slo=99.9)

        assert result.data["multi_window_alert_firing"] is True


# ---------------------------------------------------------------------------
# Tool repr / string tests
# ---------------------------------------------------------------------------

class TestToolRepr:
    def test_mimir_query_tool_repr(self):
        tool = MimirQueryTool()
        assert "MimirQueryTool" in repr(tool)
        assert "mimir_query" in repr(tool)

    def test_mimir_range_tool_name(self):
        assert MimirRangeTool.name == "mimir_query_range"

    def test_mimir_label_values_tool_name(self):
        assert MimirLabelValuesTool.name == "mimir_label_values"


# ---------------------------------------------------------------------------
# Tool registry integration
# ---------------------------------------------------------------------------

class TestToolRegistryMimir:
    def test_mimir_tools_are_in_default_registry(self):
        from app.tools.registry import get_default_registry

        registry = get_default_registry()
        assert "mimir_query" in registry
        assert "mimir_query_range" in registry
        assert "mimir_label_values" in registry

    def test_registry_get_returns_correct_type(self):
        from app.tools.registry import get_default_registry

        registry = get_default_registry()
        tool = registry.get("mimir_query")
        assert isinstance(tool, MimirQueryTool)

    def test_registry_raises_key_error_for_unknown_tool(self):
        from app.tools.registry import ToolRegistry

        registry = ToolRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.get("nonexistent_tool")
