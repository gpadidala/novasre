"""
NovaSRE — Loki (LogQL) Tool Implementations

Tools
-----
LokiQueryTool          — Range log query  (GET /loki/api/v1/query_range)
LokiInstantQueryTool   — Instant query    (GET /loki/api/v1/query)
LokiErrorExtractionTool — Extract + deduplicate top-N error patterns

All tools set the ``X-Scope-OrgID`` header for multi-tenant Loki.
Parsed log lines are returned as structured dicts rather than raw API JSON.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any, Optional

import httpx
import structlog

from app.config import get_settings
from app.tools.base import BaseTool, ToolResult

log = structlog.get_logger()

# Default patterns that classify a log line as an error
DEFAULT_ERROR_PATTERN = r"ERROR|FATAL|panic|Exception|CRITICAL|error"

# Maximum log lines to pull per query (guards against OOM on huge result sets)
MAX_LOG_LINES = 1_000


# ---------------------------------------------------------------------------
# Shared HTTP client
# ---------------------------------------------------------------------------

def _build_loki_client() -> httpx.AsyncClient:
    settings = get_settings()
    headers: dict[str, str] = {"X-Scope-OrgID": settings.loki_tenant_id}
    return httpx.AsyncClient(
        base_url=settings.loki_url,
        headers=headers,
        timeout=httpx.Timeout(30.0),
    )


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------

def _parse_streams(data: dict) -> list[dict[str, Any]]:
    """
    Convert Loki's ``streams`` result format to a flat list of log entries.

    Each entry has the shape::

        {
            "stream": {"app": "checkout", ...},
            "timestamp_ns": "1710000000000000000",
            "line": "ERROR: connection refused",
        }
    """
    entries: list[dict[str, Any]] = []
    for stream in data.get("result", []):
        stream_labels = stream.get("stream", {})
        for ts_ns, line in stream.get("values", []):
            entries.append(
                {
                    "stream": stream_labels,
                    "timestamp_ns": ts_ns,
                    "line": line,
                }
            )
    # Sort chronologically (ascending)
    entries.sort(key=lambda e: int(e["timestamp_ns"]))
    return entries


def _parse_metric_result(data: dict) -> list[dict[str, Any]]:
    """Parse a Loki metric (``vector``) query result."""
    parsed = []
    for item in data.get("result", []):
        metric = item.get("metric", {})
        ts, value = item.get("value", [None, None])
        parsed.append({"metric": metric, "timestamp": ts, "value": value})
    return parsed


# ---------------------------------------------------------------------------
# LokiQueryTool — Range query
# ---------------------------------------------------------------------------

class LokiQueryTool(BaseTool):
    """
    Execute a LogQL range query against Loki.

    Returns structured log lines with stream labels and timestamps.
    """

    name = "loki_query_range"
    description = (
        "Execute a LogQL range query against Loki. "
        "Returns log lines matching the query within the time window. "
        "Use for retrieving logs for a service, namespace, or error pattern."
    )

    async def execute(  # type: ignore[override]
        self,
        query: str,
        start: str,
        end: str,
        limit: int = 100,
        direction: str = "backward",
    ) -> ToolResult:
        """
        Parameters
        ----------
        query:
            LogQL expression, e.g. ``{app="checkout"} |~ "ERROR"``.
        start:
            Start time (RFC3339, Unix nano, or relative like ``now-1h``).
        end:
            End time (same formats).
        limit:
            Maximum number of log lines to return (capped at 1 000).
        direction:
            ``"backward"`` (newest first) or ``"forward"`` (oldest first).
        """
        time_start = time.monotonic()
        limit = min(limit, MAX_LOG_LINES)

        log.info(
            "tool.execute",
            tool_name=self.name,
            query=query,
            start=start,
            end=end,
            limit=limit,
        )

        params = {
            "query": query,
            "start": start,
            "end": end,
            "limit": str(limit),
            "direction": direction,
        }

        try:
            async with _build_loki_client() as client:
                raw = await self._get(client, "/loki/api/v1/query_range", params=params)
        except httpx.HTTPStatusError as exc:
            elapsed = round((time.monotonic() - time_start) * 1000, 2)
            self._record_failure()
            log.error(
                "tool.execute.http_error",
                tool_name=self.name,
                status=exc.response.status_code,
                query=query,
                duration_ms=elapsed,
            )
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                duration_ms=elapsed,
                query=query,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = round((time.monotonic() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(exc),
                duration_ms=elapsed,
                query=query,
            )

        elapsed = round((time.monotonic() - time_start) * 1000, 2)
        self._record_success()

        data_section = raw.get("data", {})
        result_type = data_section.get("resultType", "streams")

        if result_type == "streams":
            parsed = _parse_streams(data_section)
        else:
            parsed = _parse_metric_result(data_section)

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            query=query,
            entry_count=len(parsed),
            result_type=result_type,
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "resultType": result_type,
                "entries": parsed,
                "total": len(parsed),
            },
            duration_ms=elapsed,
            query=query,
        )


# ---------------------------------------------------------------------------
# LokiInstantQueryTool — Instant query
# ---------------------------------------------------------------------------

class LokiInstantQueryTool(BaseTool):
    """
    Execute a LogQL instant query.

    Useful for metric queries (``count_over_time``, ``rate``) that return a
    single value rather than a stream of log lines.
    """

    name = "loki_instant_query"
    description = (
        "Execute a LogQL instant query against Loki. "
        "Use for metric queries like count_over_time or rate that return "
        "a single aggregated value rather than individual log lines."
    )

    async def execute(  # type: ignore[override]
        self,
        query: str,
        time: Optional[str] = None,
        limit: int = 100,
    ) -> ToolResult:
        """
        Parameters
        ----------
        query:
            LogQL metric expression, e.g.
            ``count_over_time({app="checkout"}[5m])``.
        time:
            Optional evaluation timestamp (RFC3339 or Unix).
        limit:
            Maximum series to return.
        """
        time_start = _mono()
        log.info("tool.execute", tool_name=self.name, query=query)

        params: dict[str, str] = {"query": query, "limit": str(limit)}
        if time:
            params["time"] = time

        try:
            async with _build_loki_client() as client:
                raw = await self._get(client, "/loki/api/v1/query", params=params)
        except httpx.HTTPStatusError as exc:
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                duration_ms=elapsed,
                query=query,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(exc),
                duration_ms=elapsed,
                query=query,
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        data_section = raw.get("data", {})
        result_type = data_section.get("resultType", "vector")
        parsed = _parse_metric_result(data_section)

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            query=query,
            result_count=len(parsed),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"resultType": result_type, "result": parsed},
            duration_ms=elapsed,
            query=query,
        )


# ---------------------------------------------------------------------------
# LokiErrorExtractionTool — Deduplicated error extraction
# ---------------------------------------------------------------------------

class LokiErrorExtractionTool(BaseTool):
    """
    Fetch error/exception logs for a service and return deduplicated patterns.

    This tool:
    1. Queries Loki with an error pattern filter.
    2. Normalises each log line (strips timestamps, UUIDs, IPs, hex values).
    3. Returns the top-10 unique normalised error messages with occurrence counts.
    """

    name = "loki_extract_errors"
    description = (
        "Extract and deduplicate error patterns from Loki logs for a service. "
        "Returns the top-10 unique error messages with counts. "
        "Use to quickly identify the most frequent errors in a time window."
    )

    # Regex substitutions to normalise dynamic values out of log lines
    _NORMALISE_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
        (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b"), "<timestamp>"),
        (re.compile(r"\b\d{10,13}\b"), "<epoch>"),
        (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b"), "<ip>"),
        (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<hex>"),
        (re.compile(r'"[^"]{32,}"'), '"<long_string>"'),
        (re.compile(r"\b\d{5,}\b"), "<num>"),
    ]

    def _normalise(self, line: str) -> str:
        """Strip dynamic tokens to produce a canonical error signature."""
        normalised = line
        for pattern, replacement in self._NORMALISE_PATTERNS:
            normalised = pattern.sub(replacement, normalised)
        # Collapse multiple spaces
        return re.sub(r" +", " ", normalised).strip()

    async def execute(  # type: ignore[override]
        self,
        app: str,
        start: str,
        end: str,
        error_pattern: str = DEFAULT_ERROR_PATTERN,
        top_n: int = 10,
    ) -> ToolResult:
        """
        Parameters
        ----------
        app:
            Value of the ``app`` label (e.g. ``"checkout"``).
        start / end:
            Time bounds for the query.
        error_pattern:
            Regex pattern to filter error lines.
        top_n:
            Number of most-frequent unique error patterns to return.
        """
        time_start = _mono()

        logql_query = f'{{app="{app}"}} |~ `{error_pattern}`'
        log.info(
            "tool.execute",
            tool_name=self.name,
            app=app,
            query=logql_query,
            start=start,
            end=end,
        )

        params = {
            "query": logql_query,
            "start": start,
            "end": end,
            "limit": str(MAX_LOG_LINES),
            "direction": "forward",
        }

        try:
            async with _build_loki_client() as client:
                raw = await self._get(client, "/loki/api/v1/query_range", params=params)
        except httpx.HTTPStatusError as exc:
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                duration_ms=elapsed,
                query=logql_query,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(exc),
                duration_ms=elapsed,
                query=logql_query,
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        data_section = raw.get("data", {})
        entries = _parse_streams(data_section)

        # Deduplicate
        counter: Counter[str] = Counter()
        examples: dict[str, str] = {}  # normalised → one raw example

        for entry in entries:
            normalised = self._normalise(entry["line"])
            counter[normalised] += 1
            if normalised not in examples:
                examples[normalised] = entry["line"]

        top_errors = [
            {
                "pattern": pattern,
                "count": count,
                "example": examples[pattern],
            }
            for pattern, count in counter.most_common(top_n)
        ]

        total_lines = len(entries)
        log.info(
            "tool.execute.success",
            tool_name=self.name,
            app=app,
            total_lines=total_lines,
            unique_patterns=len(counter),
            top_n=len(top_errors),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "app": app,
                "total_error_lines": total_lines,
                "unique_patterns": len(counter),
                "top_errors": top_errors,
            },
            duration_ms=elapsed,
            query=logql_query,
        )


# ---------------------------------------------------------------------------
# Convenience alias for time.monotonic
# ---------------------------------------------------------------------------
_mono = time.monotonic
