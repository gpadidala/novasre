"""
NovaSRE — Faro (Grafana Frontend Observability) Tool Implementations

Faro stores its telemetry in Loki, so all three tools query Loki using
LogQL with Faro-specific label selectors and JSON parsing.

Tools
-----
FaroWebVitalsTool  — Core Web Vitals (LCP / FID / CLS / TTFB) at P75
FaroErrorsTool     — JavaScript / browser exceptions, deduplicated
FaroSessionsTool   — Count of affected user sessions
"""
from __future__ import annotations

import statistics
import time
from collections import Counter, defaultdict
from typing import Any, Optional

import httpx
import structlog

from app.config import get_settings
from app.tools.base import BaseTool, ToolResult

log = structlog.get_logger()

_mono = time.monotonic

# Core Web Vitals thresholds (milliseconds or score)
WEB_VITALS_THRESHOLDS = {
    "LCP":  {"good": 2500, "needs_improvement": 4000},   # ms
    "FID":  {"good": 100,  "needs_improvement": 300},    # ms
    "INP":  {"good": 200,  "needs_improvement": 500},    # ms
    "CLS":  {"good": 0.1,  "needs_improvement": 0.25},   # score (no unit conversion)
    "TTFB": {"good": 800,  "needs_improvement": 1800},   # ms
    "FCP":  {"good": 1800, "needs_improvement": 3000},   # ms
}


# ---------------------------------------------------------------------------
# Shared Loki client for Faro queries
# ---------------------------------------------------------------------------

def _build_loki_client() -> httpx.AsyncClient:
    """Faro writes to Loki, so we reuse the Loki base URL."""
    settings = get_settings()
    headers: dict[str, str] = {"X-Scope-OrgID": settings.loki_tenant_id}
    return httpx.AsyncClient(
        base_url=settings.loki_url,
        headers=headers,
        timeout=httpx.Timeout(30.0),
    )


# ---------------------------------------------------------------------------
# Loki query helper
# ---------------------------------------------------------------------------

async def _loki_query_range(
    query: str,
    start: str,
    end: str,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """
    Execute a Loki range query and return flat log entries.

    Raises ``httpx.HTTPStatusError`` on non-2xx responses.
    """
    settings = get_settings()
    params = {
        "query": query,
        "start": start,
        "end": end,
        "limit": str(limit),
        "direction": "forward",
    }
    async with _build_loki_client() as client:
        response = await client.get("/loki/api/v1/query_range", params=params)
        response.raise_for_status()
        raw = response.json()

    entries: list[dict[str, Any]] = []
    for stream in raw.get("data", {}).get("result", []):
        stream_labels = stream.get("stream", {})
        for ts_ns, line in stream.get("values", []):
            entries.append(
                {
                    "stream": stream_labels,
                    "timestamp_ns": ts_ns,
                    "line": line,
                }
            )
    return entries


def _parse_json_line(line: str) -> dict[str, Any]:
    """Best-effort JSON parse; returns empty dict on failure."""
    import json
    try:
        return json.loads(line)
    except (ValueError, TypeError):
        return {}


def _percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile (0-100) of a sorted list."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    rank = (p / 100) * (n - 1)
    lower = int(rank)
    upper = lower + 1
    if upper >= n:
        return sorted_vals[-1]
    frac = rank - lower
    return sorted_vals[lower] + frac * (sorted_vals[upper] - sorted_vals[lower])


def _vital_rating(metric_name: str, value: float) -> str:
    """Return 'good', 'needs_improvement', or 'poor' for a Web Vital value."""
    thresholds = WEB_VITALS_THRESHOLDS.get(metric_name)
    if not thresholds:
        return "unknown"
    if value <= thresholds["good"]:
        return "good"
    if value <= thresholds["needs_improvement"]:
        return "needs_improvement"
    return "poor"


# ---------------------------------------------------------------------------
# FaroWebVitalsTool
# ---------------------------------------------------------------------------

class FaroWebVitalsTool(BaseTool):
    """
    Query Faro measurement events from Loki and compute P75 Web Vitals.

    Returns P75 values for LCP, FID/INP, CLS, TTFB, and FCP alongside
    a Good/Needs Improvement/Poor rating based on Google's thresholds.
    """

    name = "faro_web_vitals"
    description = (
        "Query Grafana Faro for Core Web Vitals (LCP, FID, INP, CLS, TTFB). "
        "Returns P75 values per metric with Good/Needs Improvement/Poor rating. "
        "Use to assess frontend performance impact during an incident."
    )

    async def execute(  # type: ignore[override]
        self,
        app: str,
        page: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> ToolResult:
        """
        Parameters
        ----------
        app:
            Faro application name (value of ``app`` label in Loki).
        page:
            Optional page/route to filter by (partial match on ``page_url``).
        start / end:
            Time bounds.
        """
        time_start = _mono()
        settings = get_settings()

        start = start or "now-1h"
        end = end or "now"

        # Faro measurement events are logged with kind="measurement"
        if page:
            logql = f'{{app="{app}",kind="measurement"}} | json | page_url =~ `{page}`'
        else:
            logql = f'{{app="{app}",kind="measurement"}} | json'

        log.info(
            "tool.execute",
            tool_name=self.name,
            app=app,
            page=page,
            query=logql,
        )

        try:
            entries = await _loki_query_range(logql, start, end, limit=2000)
        except httpx.HTTPStatusError as exc:
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                duration_ms=elapsed,
                query=logql,
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
                query=logql,
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        # Accumulate values per metric name
        metric_values: dict[str, list[float]] = defaultdict(list)

        for entry in entries:
            parsed = _parse_json_line(entry["line"])
            # Faro logs measurement events as {"metric": "LCP", "value": 1234.5, ...}
            # or nested under "measurements": [{"metric": "LCP", "value": ...}]
            metric_name = parsed.get("metric") or parsed.get("name")
            raw_value = parsed.get("value")
            if metric_name and raw_value is not None:
                try:
                    metric_values[metric_name.upper()].append(float(raw_value))
                except (TypeError, ValueError):
                    pass

            # Also handle nested measurements array
            for m in parsed.get("measurements", []):
                mn = (m.get("metric") or m.get("name", "")).upper()
                rv = m.get("value")
                if mn and rv is not None:
                    try:
                        metric_values[mn].append(float(rv))
                    except (TypeError, ValueError):
                        pass

        # Compute P75 for each Web Vital
        vitals_summary: dict[str, Any] = {}
        for vital in ["LCP", "FID", "INP", "CLS", "TTFB", "FCP"]:
            values = metric_values.get(vital, [])
            if not values:
                vitals_summary[vital] = {
                    "p75": None,
                    "count": 0,
                    "rating": "no_data",
                }
                continue
            p75 = round(_percentile(values, 75), 3)
            vitals_summary[vital] = {
                "p75": p75,
                "p50": round(_percentile(values, 50), 3),
                "count": len(values),
                "rating": _vital_rating(vital, p75),
            }

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            app=app,
            measurement_count=len(entries),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "app": app,
                "page": page,
                "vitals": vitals_summary,
                "total_measurements": len(entries),
            },
            duration_ms=elapsed,
            query=logql,
        )


# ---------------------------------------------------------------------------
# FaroErrorsTool
# ---------------------------------------------------------------------------

class FaroErrorsTool(BaseTool):
    """
    Query Faro exception events from Loki and return deduplicated error types.
    """

    name = "faro_errors"
    description = (
        "Query Grafana Faro for frontend JavaScript errors and exceptions. "
        "Returns deduplicated error types with counts and example stack traces. "
        "Use to assess frontend error impact during an incident."
    )

    async def execute(  # type: ignore[override]
        self,
        app: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 500,
    ) -> ToolResult:
        """
        Parameters
        ----------
        app:
            Faro application name.
        start / end:
            Time bounds.
        limit:
            Maximum raw log lines to fetch before deduplication.
        """
        time_start = _mono()
        start = start or "now-1h"
        end = end or "now"

        logql = f'{{app="{app}",kind="exception"}} | json'
        log.info("tool.execute", tool_name=self.name, app=app, query=logql)

        try:
            entries = await _loki_query_range(logql, start, end, limit=limit)
        except httpx.HTTPStatusError as exc:
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                duration_ms=elapsed,
                query=logql,
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
                query=logql,
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        # Deduplicate by error type + message (first 100 chars)
        error_counter: Counter[str] = Counter()
        examples: dict[str, dict] = {}

        for entry in entries:
            parsed = _parse_json_line(entry["line"])

            error_type = parsed.get("type") or parsed.get("error_type") or "UnknownError"
            message = (parsed.get("message") or parsed.get("value") or "")[:100]
            key = f"{error_type}: {message}"

            error_counter[key] += 1
            if key not in examples:
                examples[key] = {
                    "type": error_type,
                    "message": parsed.get("message") or parsed.get("value") or "",
                    "stack_trace": parsed.get("stack") or parsed.get("stacktrace") or "",
                    "page_url": parsed.get("page_url") or parsed.get("url") or "",
                    "browser": parsed.get("browser_name") or "",
                }

        top_errors = [
            {
                "error_key": key,
                "count": count,
                **examples[key],
            }
            for key, count in error_counter.most_common(10)
        ]

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            app=app,
            total_events=len(entries),
            unique_errors=len(error_counter),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "app": app,
                "total_error_events": len(entries),
                "unique_error_types": len(error_counter),
                "top_errors": top_errors,
            },
            duration_ms=elapsed,
            query=logql,
        )


# ---------------------------------------------------------------------------
# FaroSessionsTool
# ---------------------------------------------------------------------------

class FaroSessionsTool(BaseTool):
    """
    Count distinct user sessions affected during a time window.

    Faro tags every event with a ``session_id`` field.  This tool counts
    unique session IDs seen in the query window.
    """

    name = "faro_sessions"
    description = (
        "Count distinct Faro user sessions in a time window. "
        "Returns total sessions, error sessions, and affected user count. "
        "Use to quantify the user impact of a frontend incident."
    )

    async def execute(  # type: ignore[override]
        self,
        app: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> ToolResult:
        """
        Parameters
        ----------
        app:
            Faro application name.
        start / end:
            Time bounds.
        """
        time_start = _mono()
        start = start or "now-1h"
        end = end or "now"

        # Fetch all Faro events to count sessions
        logql_all = f'{{app="{app}"}} | json | session_id != ""'
        # Fetch only error events to count error sessions
        logql_errors = f'{{app="{app}",kind="exception"}} | json | session_id != ""'

        log.info("tool.execute", tool_name=self.name, app=app)

        import asyncio

        try:
            all_entries, error_entries = await asyncio.gather(
                _loki_query_range(logql_all, start, end, limit=5000),
                _loki_query_range(logql_errors, start, end, limit=5000),
            )
        except httpx.HTTPStatusError as exc:
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                duration_ms=elapsed,
                query=logql_all,
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
                query=logql_all,
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        def _extract_session_id(entry: dict) -> Optional[str]:
            parsed = _parse_json_line(entry["line"])
            return (
                parsed.get("session_id")
                or parsed.get("sessionId")
                or entry["stream"].get("session_id")
            )

        all_sessions: set[str] = set()
        for e in all_entries:
            sid = _extract_session_id(e)
            if sid:
                all_sessions.add(sid)

        error_sessions: set[str] = set()
        for e in error_entries:
            sid = _extract_session_id(e)
            if sid:
                error_sessions.add(sid)

        total = len(all_sessions)
        with_errors = len(error_sessions)
        error_rate_pct = round((with_errors / total * 100) if total else 0, 2)

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            app=app,
            total_sessions=total,
            sessions_with_errors=with_errors,
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "app": app,
                "total_sessions": total,
                "sessions_with_errors": with_errors,
                "error_rate_pct": error_rate_pct,
                "time_window": {"start": start, "end": end},
            },
            duration_ms=elapsed,
            query=logql_all,
        )
