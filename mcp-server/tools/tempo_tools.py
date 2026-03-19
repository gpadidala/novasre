"""
Tempo (TraceQL) tool implementations.

All tools are read-only.
Tenant isolation is enforced via the X-Scope-OrgID header.
"""

from __future__ import annotations

import time
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
class TempoSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    tempo_url: str = "http://localhost:3200"
    tempo_tenant_id: str = "anonymous"


_settings = TempoSettings()


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
# Helpers
# ---------------------------------------------------------------------------
def _build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=_settings.tempo_url,
        headers={"X-Scope-OrgID": _settings.tempo_tenant_id},
        timeout=30.0,
    )


async def _get(
    path: str,
    params: dict[str, Any],
    tool_name: str,
    query: Optional[str] = None,
) -> ToolResult:
    start = time.monotonic()
    try:
        async with _build_client() as client:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            return ToolResult(
                tool_name=tool_name,
                success=True,
                data=resp.json(),
                duration_ms=(time.monotonic() - start) * 1000,
                query=query,
            )
    except httpx.HTTPStatusError as exc:
        log.error("tempo_http_error", status=exc.response.status_code, tool=tool_name)
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
            duration_ms=(time.monotonic() - start) * 1000,
            query=query,
        )
    except Exception as exc:
        log.error("tempo_error", exc=str(exc), tool=tool_name)
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=str(exc),
            duration_ms=(time.monotonic() - start) * 1000,
            query=query,
        )


# ---------------------------------------------------------------------------
# Helpers: span flattening
# ---------------------------------------------------------------------------
def _flatten_spans(batches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten Tempo's protobuf-JSON nested structure into a flat list of spans."""
    spans = []
    for batch in batches:
        resource_attrs = {
            a["key"]: a.get("value", {}).get("stringValue", "")
            for a in batch.get("resource", {}).get("attributes", [])
        }
        service_name = resource_attrs.get("service.name", "unknown")
        for scope in batch.get("scopeSpans", []):
            for span in scope.get("spans", []):
                span_attrs = {
                    a["key"]: a.get("value", {}).get("stringValue", "")
                    for a in span.get("attributes", [])
                }
                start_ns = int(span.get("startTimeUnixNano", 0))
                end_ns   = int(span.get("endTimeUnixNano", 0))
                duration_ms = (end_ns - start_ns) / 1_000_000 if end_ns > start_ns else 0

                spans.append({
                    "traceId":     span.get("traceId"),
                    "spanId":      span.get("spanId"),
                    "parentSpanId": span.get("parentSpanId"),
                    "name":        span.get("name"),
                    "service":     service_name,
                    "duration_ms": round(duration_ms, 3),
                    "status":      span.get("status", {}).get("code", "STATUS_CODE_UNSET"),
                    "attributes":  span_attrs,
                })
    return sorted(spans, key=lambda s: s["duration_ms"], reverse=True)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
class TempoSearchTool:
    """Search for traces using TraceQL."""

    name = "tempo_search"

    async def execute(
        self,
        query: str,
        start: str,
        end: str,
        limit: int = 20,
    ) -> ToolResult:
        log.info("tempo_search", query=query, start=start, end=end)
        params: dict[str, Any] = {
            "q":     query,
            "start": start,
            "end":   end,
            "limit": limit,
        }
        result = await _get(
            "/api/search",
            params=params,
            tool_name=self.name,
            query=query,
        )

        # Enrich with human-readable summary
        if result.success and result.data:
            traces = result.data.get("traces", [])
            summary = []
            for t in traces:
                dur_ms = round(int(t.get("durationMs", 0)), 1)
                summary.append({
                    "traceId":       t.get("traceID"),
                    "rootService":   t.get("rootServiceName"),
                    "rootOperation": t.get("rootTraceName"),
                    "duration_ms":   dur_ms,
                    "spanCount":     t.get("spanSets", [{}])[0].get("matched", 0),
                    "startTime":     t.get("startTimeUnixNano"),
                })
            result.data = {"total": len(summary), "traces": summary}

        return result


class TempoGetTraceTool:
    """Fetch a full trace by ID with all spans."""

    name = "tempo_get_trace"

    async def execute(self, trace_id: str) -> ToolResult:
        log.info("tempo_get_trace", trace_id=trace_id)
        result = await _get(
            f"/api/traces/{trace_id}",
            params={},
            tool_name=self.name,
            query=trace_id,
        )

        # Flatten the OTLP protobuf-JSON response into a usable structure
        if result.success and result.data:
            batches = result.data.get("batches", [])
            spans = _flatten_spans(batches)
            total_duration = max((s["duration_ms"] for s in spans), default=0)
            error_spans = [s for s in spans if "error" in s.get("status", "").lower()]
            result.data = {
                "trace_id":      trace_id,
                "span_count":    len(spans),
                "total_duration_ms": total_duration,
                "error_spans":   len(error_spans),
                "spans":         spans[:100],  # Cap to 100 spans for LLM context
            }

        return result


class TempoSlowTracesTool:
    """Find the slowest traces for a service in a time window."""

    name = "tempo_slow_traces"

    async def execute(
        self,
        service: str,
        threshold_ms: int = 2000,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 10,
    ) -> ToolResult:
        log.info("tempo_slow_traces", service=service, threshold_ms=threshold_ms)
        traceql = f'{{ .service.name = "{service}" && duration > {threshold_ms}ms }}'
        params: dict[str, Any] = {"q": traceql, "limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        result = await _get(
            "/api/search",
            params=params,
            tool_name=self.name,
            query=traceql,
        )

        if result.success and result.data:
            traces = result.data.get("traces", [])
            slow = sorted(
                [
                    {
                        "traceId":     t.get("traceID"),
                        "rootService": t.get("rootServiceName"),
                        "operation":   t.get("rootTraceName"),
                        "duration_ms": int(t.get("durationMs", 0)),
                        "startTime":   t.get("startTimeUnixNano"),
                    }
                    for t in traces
                ],
                key=lambda x: x["duration_ms"],
                reverse=True,
            )
            result.data = {
                "service":       service,
                "threshold_ms":  threshold_ms,
                "slow_traces":   slow,
                "count":         len(slow),
            }

        return result
