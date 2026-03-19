"""
NovaSRE — Tempo (Distributed Tracing) Tool Implementations

Tools
-----
TempoSearchTool    — Search traces using TraceQL  (GET /api/search)
TempoGetTraceTool  — Fetch a single trace by ID   (GET /api/traces/{id})
TempoSlowTracesTool — Find traces slower than a threshold

All tools return structured data suitable for rendering a waterfall chart
or passing to a downstream agent for analysis.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx
import structlog

from app.config import get_settings
from app.tools.base import BaseTool, ToolResult

log = structlog.get_logger()

_mono = time.monotonic


# ---------------------------------------------------------------------------
# Shared HTTP client
# ---------------------------------------------------------------------------

def _build_tempo_client() -> httpx.AsyncClient:
    settings = get_settings()
    headers: dict[str, str] = {
        "X-Scope-OrgID": settings.tempo_tenant_id,
        "Accept": "application/json",
    }
    return httpx.AsyncClient(
        base_url=settings.tempo_url,
        headers=headers,
        timeout=httpx.Timeout(30.0),
    )


# ---------------------------------------------------------------------------
# Waterfall builder
# ---------------------------------------------------------------------------

def build_waterfall(trace_data: dict) -> dict[str, Any]:
    """
    Convert a Tempo trace response into a hierarchical waterfall structure.

    The raw Tempo response contains a flat list of ``batches``, each with
    ``scopeSpans`` → ``spans``.  This function:

    1. Flattens all spans into a list with normalised fields.
    2. Builds a parent→children tree.
    3. Computes each span's offset from the trace root start.
    4. Returns ``{"root": ..., "spans": [...], "duration_ms": ...}``.
    """
    # Step 1: flatten all spans from the protobuf-JSON format
    spans_by_id: dict[str, dict[str, Any]] = {}

    for batch in trace_data.get("batches", []):
        resource = batch.get("resource", {})
        resource_attrs = {
            attr["key"]: _attr_value(attr.get("value", {}))
            for attr in resource.get("attributes", [])
        }
        service_name = resource_attrs.get("service.name", "unknown")

        for scope_spans in batch.get("scopeSpans", []):
            for span in scope_spans.get("spans", []):
                span_id = span.get("spanId", "")
                parent_id = span.get("parentSpanId", "")
                start_ns = int(span.get("startTimeUnixNano", "0") or "0")
                end_ns = int(span.get("endTimeUnixNano", "0") or "0")
                duration_ns = end_ns - start_ns

                span_attrs = {
                    attr["key"]: _attr_value(attr.get("value", {}))
                    for attr in span.get("attributes", [])
                }

                has_error = (
                    span.get("status", {}).get("code") == "STATUS_CODE_ERROR"
                    or span_attrs.get("error") == "true"
                    or span_attrs.get("otel.status_code") == "ERROR"
                )

                spans_by_id[span_id] = {
                    "span_id": span_id,
                    "parent_span_id": parent_id,
                    "trace_id": span.get("traceId", ""),
                    "name": span.get("name", ""),
                    "service": service_name,
                    "kind": span.get("kind", ""),
                    "start_ns": start_ns,
                    "end_ns": end_ns,
                    "duration_ms": round(duration_ns / 1_000_000, 3),
                    "attributes": span_attrs,
                    "status": span.get("status", {}),
                    "has_error": has_error,
                    "children": [],
                }

    # Step 2: build parent→children relationships
    root_spans: list[dict] = []
    for span in spans_by_id.values():
        parent_id = span["parent_span_id"]
        if parent_id and parent_id in spans_by_id:
            spans_by_id[parent_id]["children"].append(span)
        else:
            root_spans.append(span)

    # Sort children by start time
    def _sort_children(s: dict) -> None:
        s["children"].sort(key=lambda c: c["start_ns"])
        for child in s["children"]:
            _sort_children(child)

    for root in root_spans:
        _sort_children(root)

    # Step 3: compute root trace duration
    if spans_by_id:
        min_start = min(s["start_ns"] for s in spans_by_id.values())
        max_end = max(s["end_ns"] for s in spans_by_id.values())
        total_duration_ms = round((max_end - min_start) / 1_000_000, 3)
    else:
        total_duration_ms = 0.0

    # Step 4: add offset_ms to every span for waterfall rendering
    def _add_offset(s: dict, root_start: int) -> None:
        s["offset_ms"] = round((s["start_ns"] - root_start) / 1_000_000, 3)
        for child in s["children"]:
            _add_offset(child, root_start)

    root_start_ns = min((s["start_ns"] for s in root_spans), default=0)
    for root in root_spans:
        _add_offset(root, root_start_ns)

    return {
        "root_spans": root_spans,
        "span_count": len(spans_by_id),
        "duration_ms": total_duration_ms,
        "has_errors": any(s["has_error"] for s in spans_by_id.values()),
    }


def _attr_value(v: dict) -> Any:
    """Extract the concrete value from an OTLP attribute value union."""
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])
    if "boolValue" in v:
        return v["boolValue"]
    if "doubleValue" in v:
        return v["doubleValue"]
    return str(v)


# ---------------------------------------------------------------------------
# TempoSearchTool
# ---------------------------------------------------------------------------

class TempoSearchTool(BaseTool):
    """
    Search for traces using TraceQL or tag-based queries.

    Returns a list of trace summaries (root span info, duration, services).
    """

    name = "tempo_search"
    description = (
        "Search for distributed traces in Tempo using TraceQL. "
        "Returns trace summaries with root span name, total duration, and services. "
        "Use to find traces matching a service, error condition, or span attribute."
    )

    async def execute(  # type: ignore[override]
        self,
        query: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 20,
    ) -> ToolResult:
        """
        Parameters
        ----------
        query:
            TraceQL expression, e.g.
            ``{ .service.name = "checkout" && duration > 2s }``.
        start / end:
            Time bounds (Unix seconds or RFC3339).
        limit:
            Maximum number of traces to return.
        """
        time_start = _mono()
        log.info(
            "tool.execute",
            tool_name=self.name,
            query=query,
            start=start,
            end=end,
            limit=limit,
        )

        params: dict[str, Any] = {"q": query, "limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        try:
            async with _build_tempo_client() as client:
                raw = await self._get(client, "/api/search", params=params)
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

        traces = raw.get("traces", [])
        parsed = [
            {
                "trace_id": t.get("traceID", ""),
                "root_service": t.get("rootServiceName", ""),
                "root_trace_name": t.get("rootTraceName", ""),
                "duration_ms": round(
                    int(t.get("durationMs", 0)), 2
                ),
                "span_count": t.get("spanCount", 0),
                "error": t.get("rootSpanError", False),
                "start_time_unix_nano": t.get("startTimeUnixNano", ""),
            }
            for t in traces
        ]

        # Sort by duration descending
        parsed.sort(key=lambda t: t["duration_ms"], reverse=True)

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            query=query,
            trace_count=len(parsed),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"traces": parsed, "total": len(parsed)},
            duration_ms=elapsed,
            query=query,
        )


# ---------------------------------------------------------------------------
# TempoGetTraceTool
# ---------------------------------------------------------------------------

class TempoGetTraceTool(BaseTool):
    """
    Fetch a complete trace by ID and build a waterfall structure.
    """

    name = "tempo_get_trace"
    description = (
        "Fetch a complete distributed trace by trace ID from Tempo. "
        "Returns all spans with parent-child relationships, durations, "
        "attributes, and error status. Use to drill into a specific trace."
    )

    async def execute(  # type: ignore[override]
        self,
        trace_id: str,
    ) -> ToolResult:
        """
        Parameters
        ----------
        trace_id:
            Hex trace ID, e.g. ``"a1b2c3d4e5f60001"``.
        """
        time_start = _mono()
        log.info("tool.execute", tool_name=self.name, trace_id=trace_id)

        try:
            async with _build_tempo_client() as client:
                raw = await self._get(client, f"/api/traces/{trace_id}")
        except httpx.HTTPStatusError as exc:
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                duration_ms=elapsed,
                query=f"trace/{trace_id}",
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
                query=f"trace/{trace_id}",
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        waterfall = build_waterfall(raw)

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            trace_id=trace_id,
            span_count=waterfall["span_count"],
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "trace_id": trace_id,
                "waterfall": waterfall,
            },
            duration_ms=elapsed,
            query=f"trace/{trace_id}",
        )


# ---------------------------------------------------------------------------
# TempoSlowTracesTool
# ---------------------------------------------------------------------------

class TempoSlowTracesTool(BaseTool):
    """
    Find the slowest traces for a service above a latency threshold.
    """

    name = "tempo_slow_traces"
    description = (
        "Find distributed traces in Tempo that exceed a latency threshold. "
        "Returns traces sorted by duration descending. "
        "Use to identify which requests are contributing to P99 latency spikes."
    )

    async def execute(  # type: ignore[override]
        self,
        service: str,
        threshold_ms: int = 2000,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 20,
    ) -> ToolResult:
        """
        Parameters
        ----------
        service:
            Service name as in ``service.name`` span attribute.
        threshold_ms:
            Minimum trace duration in milliseconds.
        start / end:
            Time bounds.
        limit:
            Maximum number of slow traces to return.
        """
        time_start = _mono()

        # Build TraceQL query
        traceql = (
            f'{{ .service.name = "{service}" && duration > {threshold_ms}ms }}'
        )

        log.info(
            "tool.execute",
            tool_name=self.name,
            service=service,
            threshold_ms=threshold_ms,
            query=traceql,
        )

        params: dict[str, Any] = {"q": traceql, "limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        try:
            async with _build_tempo_client() as client:
                raw = await self._get(client, "/api/search", params=params)
        except httpx.HTTPStatusError as exc:
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                duration_ms=elapsed,
                query=traceql,
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
                query=traceql,
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        traces = raw.get("traces", [])
        parsed = [
            {
                "trace_id": t.get("traceID", ""),
                "root_service": t.get("rootServiceName", ""),
                "root_trace_name": t.get("rootTraceName", ""),
                "duration_ms": int(t.get("durationMs", 0)),
                "span_count": t.get("spanCount", 0),
                "error": t.get("rootSpanError", False),
            }
            for t in traces
        ]
        parsed.sort(key=lambda t: t["duration_ms"], reverse=True)

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            service=service,
            threshold_ms=threshold_ms,
            slow_trace_count=len(parsed),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "service": service,
                "threshold_ms": threshold_ms,
                "slow_traces": parsed,
                "total": len(parsed),
            },
            duration_ms=elapsed,
            query=traceql,
        )
