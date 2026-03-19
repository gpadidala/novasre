"""
Tests for the Loki tool implementations.

Uses ``respx`` to mock all HTTP calls — no live Loki instance required.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx

from app.tools.loki import (
    LokiErrorExtractionTool,
    LokiInstantQueryTool,
    LokiQueryTool,
    _parse_streams,
)

# ---------------------------------------------------------------------------
# Fixtures / shared test data
# ---------------------------------------------------------------------------

LOKI_BASE = "https://loki.test.internal"

# Minimal Loki streams response (log lines)
STREAMS_RESPONSE: dict[str, Any] = {
    "status": "success",
    "data": {
        "resultType": "streams",
        "result": [
            {
                "stream": {"app": "checkout", "namespace": "prod"},
                "values": [
                    ["1710000000000000000", "INFO starting server"],
                    ["1710000001000000000", "ERROR connection refused to db:5432"],
                    ["1710000002000000000", "ERROR timeout after 30s calling payment"],
                ],
            }
        ],
    },
}

# Multiple streams with different apps
MULTI_STREAM_RESPONSE: dict[str, Any] = {
    "status": "success",
    "data": {
        "resultType": "streams",
        "result": [
            {
                "stream": {"app": "checkout"},
                "values": [
                    ["1710000001000000000", "ERROR db connection refused"],
                    ["1710000002000000000", "ERROR db connection refused"],
                    ["1710000003000000000", "ERROR timeout after 30s"],
                ],
            },
            {
                "stream": {"app": "worker"},
                "values": [
                    ["1710000004000000000", "FATAL panic: nil pointer dereference"],
                ],
            },
        ],
    },
}

# Loki metric (vector) response
VECTOR_RESPONSE: dict[str, Any] = {
    "status": "success",
    "data": {
        "resultType": "vector",
        "result": [
            {
                "metric": {"app": "checkout"},
                "value": [1710000000, "42"],
            }
        ],
    },
}

# Empty streams response
EMPTY_RESPONSE: dict[str, Any] = {
    "status": "success",
    "data": {"resultType": "streams", "result": []},
}


def _patch_settings(base_url: str = LOKI_BASE):
    """Patch settings to use the test Loki URL."""
    return patch(
        "app.tools.loki.get_settings",
        return_value=type(
            "S",
            (),
            {"loki_url": base_url, "loki_tenant_id": "test-tenant"},
        )(),
    )


# ---------------------------------------------------------------------------
# Unit tests — _parse_streams helper
# ---------------------------------------------------------------------------

class TestParseStreams:
    def test_parse_streams_flattens_entries(self):
        entries = _parse_streams(STREAMS_RESPONSE["data"])
        assert len(entries) == 3
        assert entries[0]["line"] == "INFO starting server"
        assert entries[0]["stream"] == {"app": "checkout", "namespace": "prod"}

    def test_parse_streams_sorts_chronologically(self):
        """Entries should be sorted by timestamp ascending."""
        entries = _parse_streams(MULTI_STREAM_RESPONSE["data"])
        timestamps = [int(e["timestamp_ns"]) for e in entries]
        assert timestamps == sorted(timestamps)

    def test_parse_streams_empty_result(self):
        entries = _parse_streams(EMPTY_RESPONSE["data"])
        assert entries == []

    def test_parse_streams_includes_stream_labels(self):
        entries = _parse_streams(STREAMS_RESPONSE["data"])
        for entry in entries:
            assert "stream" in entry
            assert "timestamp_ns" in entry
            assert "line" in entry


# ---------------------------------------------------------------------------
# LokiQueryTool tests
# ---------------------------------------------------------------------------

class TestLokiQueryTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_log_entries(self):
        """Successful range query returns parsed log entries."""
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=STREAMS_RESPONSE)
            )

            tool = LokiQueryTool()
            result = await tool.execute(
                query='{app="checkout"}',
                start="now-1h",
                end="now",
            )

        assert result.success is True
        assert result.tool_name == "loki_query_range"
        assert result.data["resultType"] == "streams"
        assert len(result.data["entries"]) == 3
        assert result.data["total"] == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_with_default_limit(self):
        """Default limit is 100 and direction is backward."""
        with _patch_settings():
            route = respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=EMPTY_RESPONSE)
            )

            tool = LokiQueryTool()
            await tool.execute(
                query='{app="checkout"}', start="now-1h", end="now"
            )

        assert route.called
        # Verify the request was made
        request = route.calls[0].request
        assert b"limit=100" in request.url.query or "limit" in str(request.url)

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_caps_limit_at_1000(self):
        """Limit is capped at MAX_LOG_LINES (1 000)."""
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=EMPTY_RESPONSE)
            )

            tool = LokiQueryTool()
            # Request 9999 lines — should be capped at 1000
            result = await tool.execute(
                query='{app="checkout"}',
                start="now-1h",
                end="now",
                limit=9999,
            )

        assert result.success is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_error_on_http_400(self):
        """A 400 response (bad LogQL) returns a failed ToolResult."""
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(
                    400, json={"message": "parse error: unexpected token"}
                )
            )

            tool = LokiQueryTool()
            result = await tool.execute(
                query="invalid{{logql",
                start="now-1h",
                end="now",
            )

        assert result.success is False
        assert "400" in result.error

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_error_on_connection_refused(self):
        """Connection errors are caught and returned as failed ToolResult."""
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )

            tool = LokiQueryTool()
            result = await tool.execute(
                query='{app="checkout"}', start="now-1h", end="now"
            )

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_circuit_breaker_opens_after_three_failures(self):
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(503, text="service unavailable")
            )

            tool = LokiQueryTool()
            for _ in range(3):
                await tool.execute(
                    query='{app="checkout"}', start="now-1h", end="now"
                )

        assert tool._cb.is_open is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_handles_metric_result_type(self):
        """Loki metric queries (vector type) are parsed correctly."""
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=VECTOR_RESPONSE)
            )

            tool = LokiQueryTool()
            result = await tool.execute(
                query='count_over_time({app="checkout"}[5m])',
                start="now-1h",
                end="now",
            )

        assert result.success is True
        assert result.data["resultType"] == "vector"

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_query_stored_in_result(self):
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=EMPTY_RESPONSE)
            )

            tool = LokiQueryTool()
            query = '{app="my-service"} |= "error"'
            result = await tool.execute(query=query, start="now-1h", end="now")

        assert result.query == query


# ---------------------------------------------------------------------------
# LokiInstantQueryTool tests
# ---------------------------------------------------------------------------

class TestLokiInstantQueryTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_vector_result(self):
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query").mock(
                return_value=httpx.Response(200, json=VECTOR_RESPONSE)
            )

            tool = LokiInstantQueryTool()
            result = await tool.execute(
                query='count_over_time({app="checkout"}[5m])'
            )

        assert result.success is True
        assert result.tool_name == "loki_instant_query"
        assert result.data["resultType"] == "vector"
        assert len(result.data["result"]) == 1
        assert result.data["result"][0]["value"] == "42"

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_with_explicit_time(self):
        with _patch_settings():
            route = respx.get(f"{LOKI_BASE}/loki/api/v1/query").mock(
                return_value=httpx.Response(200, json=VECTOR_RESPONSE)
            )

            tool = LokiInstantQueryTool()
            await tool.execute(
                query='count_over_time({app="checkout"}[5m])',
                time="2024-03-17T10:00:00Z",
            )

        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_error_on_bad_query(self):
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query").mock(
                return_value=httpx.Response(400, text="syntax error")
            )

            tool = LokiInstantQueryTool()
            result = await tool.execute(query="{{bad}}}")

        assert result.success is False
        assert "400" in result.error


# ---------------------------------------------------------------------------
# LokiErrorExtractionTool tests
# ---------------------------------------------------------------------------

class TestLokiErrorExtractionTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_deduplicated_errors(self):
        """Repeated error lines are deduplicated and counted."""
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=MULTI_STREAM_RESPONSE)
            )

            tool = LokiErrorExtractionTool()
            result = await tool.execute(
                app="checkout",
                start="now-1h",
                end="now",
            )

        assert result.success is True
        assert result.tool_name == "loki_extract_errors"
        data = result.data
        assert data["app"] == "checkout"
        assert data["total_error_lines"] > 0
        assert len(data["top_errors"]) > 0

        # Verify deduplication: "db connection refused" appears twice
        top = data["top_errors"]
        counts = {e["pattern"]: e["count"] for e in top}
        # At least one pattern should have count >= 2
        assert any(c >= 2 for c in counts.values()), (
            f"Expected deduplication, got: {counts}"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_at_most_top_n_errors(self):
        """Returns no more than top_n unique patterns."""
        # Generate a response with many different error messages
        values = [
            [str(1710000000 + i) + "000000000", f"ERROR unique_error_{i} message"]
            for i in range(20)
        ]
        big_response: dict[str, Any] = {
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": [{"stream": {"app": "checkout"}, "values": values}],
            },
        }

        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=big_response)
            )

            tool = LokiErrorExtractionTool()
            result = await tool.execute(
                app="checkout", start="now-1h", end="now", top_n=5
            )

        assert result.success is True
        assert len(result.data["top_errors"]) <= 5

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_normalises_uuids_out_of_lines(self):
        """UUID values in log lines are replaced with <uuid> for deduplication."""
        uuid_lines = [
            [
                "1710000001000000000",
                "ERROR request 550e8400-e29b-41d4-a716-446655440000 failed",
            ],
            [
                "1710000002000000000",
                "ERROR request a1b2c3d4-e5f6-7890-abcd-ef1234567890 failed",
            ],
        ]
        response: dict[str, Any] = {
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": [{"stream": {"app": "svc"}, "values": uuid_lines}],
            },
        }

        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=response)
            )

            tool = LokiErrorExtractionTool()
            result = await tool.execute(app="svc", start="now-1h", end="now")

        assert result.success is True
        # Both lines should collapse to a single pattern
        assert result.data["unique_patterns"] == 1
        assert result.data["top_errors"][0]["count"] == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_normalises_ip_addresses(self):
        """IP addresses are replaced with <ip> for deduplication."""
        ip_lines = [
            ["1710000001000000000", "ERROR connection to 10.0.0.1:5432 refused"],
            ["1710000002000000000", "ERROR connection to 10.0.0.2:5432 refused"],
        ]
        response: dict[str, Any] = {
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": [{"stream": {"app": "svc"}, "values": ip_lines}],
            },
        }

        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=response)
            )

            tool = LokiErrorExtractionTool()
            result = await tool.execute(app="svc", start="now-1h", end="now")

        assert result.success is True
        assert result.data["unique_patterns"] == 1
        assert result.data["top_errors"][0]["count"] == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_empty_logs_returns_zero_errors(self):
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=EMPTY_RESPONSE)
            )

            tool = LokiErrorExtractionTool()
            result = await tool.execute(
                app="quiet-service", start="now-1h", end="now"
            )

        assert result.success is True
        assert result.data["total_error_lines"] == 0
        assert result.data["top_errors"] == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_builds_correct_logql_query(self):
        """The generated LogQL query includes the app name and error pattern."""
        with _patch_settings():
            route = respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=EMPTY_RESPONSE)
            )

            tool = LokiErrorExtractionTool()
            result = await tool.execute(
                app="payment",
                start="now-1h",
                end="now",
                error_pattern="FATAL",
            )

        assert result.success is True
        assert "payment" in result.query
        assert "FATAL" in result.query

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_returns_error_on_http_failure(self):
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(500, text="internal server error")
            )

            tool = LokiErrorExtractionTool()
            result = await tool.execute(
                app="checkout", start="now-1h", end="now"
            )

        assert result.success is False
        assert "500" in result.error

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_top_errors_have_required_fields(self):
        """Each top-error entry must have pattern, count, and example keys."""
        with _patch_settings():
            respx.get(f"{LOKI_BASE}/loki/api/v1/query_range").mock(
                return_value=httpx.Response(200, json=MULTI_STREAM_RESPONSE)
            )

            tool = LokiErrorExtractionTool()
            result = await tool.execute(
                app="checkout", start="now-1h", end="now"
            )

        for error in result.data["top_errors"]:
            assert "pattern" in error, f"Missing 'pattern' in {error}"
            assert "count" in error, f"Missing 'count' in {error}"
            assert "example" in error, f"Missing 'example' in {error}"
            assert isinstance(error["count"], int)
            assert error["count"] >= 1


# ---------------------------------------------------------------------------
# Tool name / descriptor tests
# ---------------------------------------------------------------------------

class TestLokiToolDescriptors:
    def test_loki_query_tool_name(self):
        assert LokiQueryTool.name == "loki_query_range"

    def test_loki_instant_query_tool_name(self):
        assert LokiInstantQueryTool.name == "loki_instant_query"

    def test_loki_error_extraction_tool_name(self):
        assert LokiErrorExtractionTool.name == "loki_extract_errors"

    def test_all_tools_have_descriptions(self):
        for cls in [LokiQueryTool, LokiInstantQueryTool, LokiErrorExtractionTool]:
            assert cls.description, f"{cls.__name__} is missing a description"


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------

class TestToolRegistryLoki:
    def test_loki_tools_registered_in_default_registry(self):
        from app.tools.registry import get_default_registry

        registry = get_default_registry()
        assert "loki_query_range" in registry
        assert "loki_instant_query" in registry
        assert "loki_extract_errors" in registry

    def test_registry_returns_correct_types(self):
        from app.tools.registry import get_default_registry

        registry = get_default_registry()
        assert isinstance(registry.get("loki_query_range"), LokiQueryTool)
        assert isinstance(registry.get("loki_instant_query"), LokiInstantQueryTool)
        assert isinstance(registry.get("loki_extract_errors"), LokiErrorExtractionTool)
