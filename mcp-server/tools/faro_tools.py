"""
Faro (Real User Monitoring / Frontend Observability) tool implementations.

Faro stores its signals in Loki as structured JSON logs with specific
`kind` labels: "measurement" (Web Vitals), "exception" (JS errors),
"log" (console), "event" (custom events).

All tools are read-only.
"""

from __future__ import annotations

import statistics
import time
from collections import defaultdict
from typing import Any, Optional

import httpx
import structlog
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class FaroSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    faro_collector_url: str = "http://localhost:12347"
    faro_api_key: str = ""
    loki_url: str = "http://localhost:3100"
    loki_tenant_id: str = "anonymous"


_settings = FaroSettings()


# ---------------------------------------------------------------------------
# Shared result model
# ---------------------------------------------------------------------------
class ToolResult(BaseModel):
    tool_name: str
    success: bool
    data: Any
    error: Optional[str] = None
    duration_ms: float
    query: Optional[str] = None


# ---------------------------------------------------------------------------
# Loki client (Faro backend is Loki)
# ---------------------------------------------------------------------------
def _build_loki_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=_settings.loki_url,
        headers={"X-Scope-OrgID": _settings.loki_tenant_id},
        timeout=30.0,
    )


async def _loki_query_range(
    logql: str,
    start: Optional[str],
    end: Optional[str],
    limit: int = 500,
) -> list[tuple[str, str]]:
    """
    Execute a Loki range query and return flat list of (timestamp, log_line) pairs.
    """
    params: dict[str, Any] = {
        "query":     logql,
        "limit":     limit,
        "direction": "backward",
    }
    if start:
        params["start"] = start
    if end:
        params["end"] = end

    try:
        async with _build_loki_client() as client:
            resp = await client.get("/loki/api/v1/query_range", params=params)
            resp.raise_for_status()
            streams = resp.json().get("data", {}).get("result", [])
            lines: list[tuple[str, str]] = []
            for stream in streams:
                for ts, line in stream.get("values", []):
                    lines.append((ts, line))
            return lines
    except Exception as exc:
        log.error("faro_loki_error", exc=str(exc))
        return []


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * p / 100
    f, c = int(k), min(int(k) + 1, len(sorted_v) - 1)
    return sorted_v[f] + (sorted_v[c] - sorted_v[f]) * (k - f)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
class FaroWebVitalsTool:
    """Query Faro for Core Web Vitals via Loki."""

    name = "faro_web_vitals"

    # Web Vital thresholds (Google's Good/Needs Improvement/Poor)
    _THRESHOLDS = {
        "LCP":  {"good": 2500,  "poor": 4000},   # ms
        "INP":  {"good": 200,   "poor": 500},    # ms
        "CLS":  {"good": 0.1,   "poor": 0.25},   # unitless
        "TTFB": {"good": 800,   "poor": 1800},   # ms
        "FCP":  {"good": 1800,  "poor": 3000},   # ms
        "FID":  {"good": 100,   "poor": 300},    # ms (legacy)
    }

    async def execute(
        self,
        app: str,
        page: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> ToolResult:
        log.info("faro_web_vitals", app=app, page=page)
        t0 = time.monotonic()

        selector = f'{{app="{app}",kind="measurement"}}'
        if page:
            selector = f'{{app="{app}",kind="measurement",page_url=~".*{page}.*"}}'

        logql = f"{selector} | json"
        lines = await _loki_query_range(logql, start, end)

        # Group measurements by metric name
        import json as _json
        metric_values: dict[str, list[float]] = defaultdict(list)

        for _ts, line in lines:
            try:
                entry = _json.loads(line)
                metric = entry.get("name") or entry.get("metric")
                value_str = entry.get("value")
                if metric and value_str is not None:
                    try:
                        metric_values[metric.upper()].append(float(value_str))
                    except (ValueError, TypeError):
                        pass
            except _json.JSONDecodeError:
                pass

        results: dict[str, Any] = {}
        for metric, values in metric_values.items():
            if metric not in self._THRESHOLDS:
                continue
            p75   = _percentile(values, 75)
            p95   = _percentile(values, 95)
            thres = self._THRESHOLDS[metric]
            rating = (
                "good" if p75 <= thres["good"]
                else "needs_improvement" if p75 <= thres["poor"]
                else "poor"
            )
            results[metric] = {
                "p50": round(_percentile(values, 50), 2),
                "p75": round(p75, 2),
                "p95": round(p95, 2),
                "count": len(values),
                "rating": rating,
                "threshold_good": thres["good"],
                "threshold_poor": thres["poor"],
            }

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "app": app,
                "page": page,
                "vitals": results,
                "sample_count": sum(len(v) for v in metric_values.values()),
            },
            duration_ms=(time.monotonic() - t0) * 1000,
            query=logql,
        )


class FaroErrorsTool:
    """Query Faro for frontend JavaScript exceptions."""

    name = "faro_errors"

    async def execute(
        self,
        app: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 50,
    ) -> ToolResult:
        log.info("faro_errors", app=app)
        t0 = time.monotonic()

        logql = f'{{app="{app}",kind="exception"}} | json'
        lines = await _loki_query_range(logql, start, end, limit=500)

        import json as _json
        from collections import Counter

        error_counter: Counter[str] = Counter()
        error_examples: dict[str, dict[str, Any]] = {}

        for _ts, line in lines:
            try:
                entry = _json.loads(line)
                # Faro exception fields
                err_type  = entry.get("type") or entry.get("errorType") or "UnknownError"
                err_value = entry.get("value") or entry.get("message") or ""
                # Normalise key: type + first 100 chars of message
                key = f"{err_type}: {err_value[:100]}"
                error_counter[key] += 1
                if key not in error_examples:
                    error_examples[key] = {
                        "type":  err_type,
                        "value": err_value,
                        "stacktrace": entry.get("stacktrace") or entry.get("stack"),
                        "url":   entry.get("page_url") or entry.get("url"),
                    }
            except _json.JSONDecodeError:
                pass

        top_errors = [
            {
                "count":   count,
                "key":     key,
                **error_examples[key],
            }
            for key, count in error_counter.most_common(limit)
        ]

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "app":           app,
                "total_events":  len(lines),
                "unique_errors": len(error_counter),
                "top_errors":    top_errors,
            },
            duration_ms=(time.monotonic() - t0) * 1000,
            query=logql,
        )


class FaroSessionsTool:
    """Count unique user sessions in Faro for impact assessment."""

    name = "faro_sessions"

    async def execute(
        self,
        app: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> ToolResult:
        log.info("faro_sessions", app=app)
        t0 = time.monotonic()

        logql = f'{{app="{app}"}} | json | session_id != ""'
        lines = await _loki_query_range(logql, start, end, limit=2000)

        import json as _json

        session_ids:    set[str] = set()
        user_ids:       set[str] = set()
        page_counters:  dict[str, int] = defaultdict(int)

        for _ts, line in lines:
            try:
                entry = _json.loads(line)
                sid = entry.get("session_id") or entry.get("sessionId")
                uid = entry.get("user_id") or entry.get("userId")
                page = entry.get("page_url") or entry.get("url") or "unknown"
                if sid:
                    session_ids.add(sid)
                if uid:
                    user_ids.add(uid)
                page_counters[page] += 1
            except _json.JSONDecodeError:
                pass

        top_pages = sorted(
            [{"url": url, "events": count} for url, count in page_counters.items()],
            key=lambda x: x["events"],
            reverse=True,
        )[:10]

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "app":             app,
                "unique_sessions": len(session_ids),
                "unique_users":    len(user_ids),
                "total_events":    len(lines),
                "top_pages":       top_pages,
            },
            duration_ms=(time.monotonic() - t0) * 1000,
            query=logql,
        )
