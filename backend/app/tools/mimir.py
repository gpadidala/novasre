"""
NovaSRE — Mimir (Prometheus-compatible) Tool Implementations

Tools
-----
MimirQueryTool       — Instant PromQL query  (POST /prometheus/api/v1/query)
MimirRangeTool       — Range  PromQL query   (POST /prometheus/api/v1/query_range)
MimirLabelValuesTool — Label value discovery (GET  /prometheus/api/v1/label/{name}/values)

Module-level helper functions wrap the most common SRE queries so agents can
call them without needing to construct raw PromQL.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx
import structlog

from app.config import get_settings
from app.tools.base import BaseTool, ToolResult

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Shared HTTP client factory
# ---------------------------------------------------------------------------

def _build_mimir_client() -> httpx.AsyncClient:
    """
    Build an ``httpx.AsyncClient`` pre-configured for Mimir.

    Adds ``X-Scope-OrgID`` header for multi-tenant Mimir and optionally
    configures HTTP Basic Auth when credentials are present.
    """
    settings = get_settings()
    headers: dict[str, str] = {
        "X-Scope-OrgID": settings.mimir_tenant_id,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    auth: Optional[tuple[str, str]] = None
    if settings.mimir_basic_auth_user:
        auth = (settings.mimir_basic_auth_user, settings.mimir_basic_auth_password)

    return httpx.AsyncClient(
        base_url=settings.mimir_url,
        headers=headers,
        auth=auth,
        timeout=httpx.Timeout(30.0),
    )


# ---------------------------------------------------------------------------
# Helper: parse Prometheus-style vector/matrix result
# ---------------------------------------------------------------------------

def _parse_vector(result: list[dict]) -> list[dict[str, Any]]:
    """Convert a Prometheus vector result to a cleaner list of dicts."""
    parsed = []
    for item in result:
        metric = item.get("metric", {})
        ts, value = item.get("value", [None, None])
        parsed.append({"metric": metric, "timestamp": ts, "value": value})
    return parsed


def _parse_matrix(result: list[dict]) -> list[dict[str, Any]]:
    """Convert a Prometheus matrix result to a cleaner list of time series."""
    parsed = []
    for item in result:
        metric = item.get("metric", {})
        values = [
            {"timestamp": ts, "value": v} for ts, v in item.get("values", [])
        ]
        parsed.append({"metric": metric, "values": values})
    return parsed


# ---------------------------------------------------------------------------
# MimirQueryTool — Instant query
# ---------------------------------------------------------------------------

class MimirQueryTool(BaseTool):
    """
    Execute an instant PromQL query against Mimir.

    Returns the current value(s) of the queried time series.
    """

    name = "mimir_query"
    description = (
        "Execute an instant PromQL query against Mimir/Prometheus. "
        "Returns current metric values for the given expression. "
        "Use for point-in-time lookups (current error rate, current CPU, etc.)."
    )

    async def execute(  # type: ignore[override]
        self,
        query: str,
        time: Optional[str] = None,
    ) -> ToolResult:
        """
        Parameters
        ----------
        query:
            PromQL expression, e.g. ``rate(http_requests_total[5m])``.
        time:
            Optional RFC3339 or Unix timestamp.  Defaults to now.
        """
        start = time_start = time_module_time()
        settings = get_settings()

        log.info(
            "tool.execute",
            tool_name=self.name,
            query=query,
            time=time,
        )

        params: dict[str, str] = {"query": query}
        if time:
            params["time"] = time

        try:
            async with _build_mimir_client() as client:
                raw = await self._post(
                    client,
                    "/prometheus/api/v1/query",
                    data=params,
                )
        except httpx.HTTPStatusError as exc:
            elapsed = round((time_module_time() - time_start) * 1000, 2)
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
            elapsed = round((time_module_time() - time_start) * 1000, 2)
            self._record_failure()
            log.error(
                "tool.execute.error",
                tool_name=self.name,
                error=str(exc),
                query=query,
                duration_ms=elapsed,
            )
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(exc),
                duration_ms=elapsed,
                query=query,
            )

        elapsed = round((time_module_time() - time_start) * 1000, 2)
        self._record_success()

        data_section = raw.get("data", {})
        result_type = data_section.get("resultType", "unknown")
        raw_result = data_section.get("result", [])

        parsed = (
            _parse_vector(raw_result)
            if result_type == "vector"
            else raw_result
        )

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
# MimirRangeTool — Range query (time series)
# ---------------------------------------------------------------------------

class MimirRangeTool(BaseTool):
    """
    Execute a range PromQL query that returns a time series matrix.

    Use for plotting trends over a time window.
    """

    name = "mimir_query_range"
    description = (
        "Execute a range PromQL query against Mimir/Prometheus. "
        "Returns a time series (matrix) for the given time window. "
        "Use for trend analysis, sparklines, and comparing current vs baseline."
    )

    async def execute(  # type: ignore[override]
        self,
        query: str,
        start: str,
        end: str,
        step: str = "60s",
    ) -> ToolResult:
        """
        Parameters
        ----------
        query:
            PromQL expression.
        start:
            Start time (RFC3339, Unix timestamp, or relative e.g. ``now-1h``).
        end:
            End time (same formats as ``start``).
        step:
            Query resolution step, e.g. ``60s``, ``5m``.
        """
        time_start = time_module_time()
        log.info(
            "tool.execute",
            tool_name=self.name,
            query=query,
            start=start,
            end=end,
            step=step,
        )

        params = {"query": query, "start": start, "end": end, "step": step}

        try:
            async with _build_mimir_client() as client:
                raw = await self._post(
                    client,
                    "/prometheus/api/v1/query_range",
                    data=params,
                )
        except httpx.HTTPStatusError as exc:
            elapsed = round((time_module_time() - time_start) * 1000, 2)
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
            elapsed = round((time_module_time() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(exc),
                duration_ms=elapsed,
                query=query,
            )

        elapsed = round((time_module_time() - time_start) * 1000, 2)
        self._record_success()

        data_section = raw.get("data", {})
        result_type = data_section.get("resultType", "matrix")
        raw_result = data_section.get("result", [])
        parsed = _parse_matrix(raw_result)

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            query=query,
            series_count=len(parsed),
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
# MimirLabelValuesTool — Label value discovery
# ---------------------------------------------------------------------------

class MimirLabelValuesTool(BaseTool):
    """
    List all values for a given Prometheus label.

    Useful for service discovery (e.g. ``label_name="app"`` lists every app).
    """

    name = "mimir_label_values"
    description = (
        "List all values for a Prometheus label in Mimir. "
        "Use to discover available service names, namespaces, or other label values."
    )

    async def execute(  # type: ignore[override]
        self,
        label_name: str,
        match: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> ToolResult:
        """
        Parameters
        ----------
        label_name:
            The label whose values to enumerate, e.g. ``app``.
        match:
            Optional series selector to narrow results, e.g.
            ``{namespace="production"}``.
        start / end:
            Optional time bounds.
        """
        time_start = time_module_time()
        log.info(
            "tool.execute",
            tool_name=self.name,
            label_name=label_name,
            match=match,
        )

        params: dict[str, str] = {}
        if match:
            params["match[]"] = match
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        url = f"/prometheus/api/v1/label/{label_name}/values"

        try:
            async with _build_mimir_client() as client:
                raw = await self._get(client, url, params=params)
        except httpx.HTTPStatusError as exc:
            elapsed = round((time_module_time() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                duration_ms=elapsed,
                query=f"label/{label_name}/values",
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = round((time_module_time() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(exc),
                duration_ms=elapsed,
                query=f"label/{label_name}/values",
            )

        elapsed = round((time_module_time() - time_start) * 1000, 2)
        self._record_success()
        values = raw.get("data", [])

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            label_name=label_name,
            value_count=len(values),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"label": label_name, "values": values},
            duration_ms=elapsed,
            query=f"label/{label_name}/values",
        )


# ---------------------------------------------------------------------------
# Module-level helper functions used by agents
# ---------------------------------------------------------------------------
# These wrap common SRE queries.  Each returns a ToolResult so agents can
# treat them identically to raw tool calls.

async def get_error_rate(service: str, window: str = "5m") -> ToolResult:
    """HTTP 5xx error rate (requests/second) for a service."""
    query = (
        f'rate(http_requests_total{{app="{service}",status=~"5.."}}[{window}])'
    )
    tool = MimirQueryTool()
    result = await tool.safe_execute(query=query)
    result.query = query
    return result


async def get_latency_p99(service: str, window: str = "5m") -> ToolResult:
    """99th-percentile request latency (seconds) for a service."""
    query = (
        f"histogram_quantile(0.99, "
        f'rate(http_request_duration_seconds_bucket{{app="{service}"}}[{window}]))'
    )
    tool = MimirQueryTool()
    result = await tool.safe_execute(query=query)
    result.query = query
    return result


async def get_throughput(service: str, window: str = "5m") -> ToolResult:
    """Total request throughput (requests/second) for a service."""
    query = f'rate(http_requests_total{{app="{service}"}}[{window}])'
    tool = MimirQueryTool()
    result = await tool.safe_execute(query=query)
    result.query = query
    return result


async def get_slo_burn_rate(service: str, slo: float = 99.9) -> ToolResult:
    """
    Compute the SLO error-budget burn rate.

    Compares the 1-hour burn rate against the 5-minute burn rate.
    Returns both rates and whether the multi-window burn-rate alert would fire
    (1h > 14× and 5m > 14×, which is the standard "page-worthy" threshold).
    """
    error_budget = 1.0 - (slo / 100.0)
    # 1-hour burn rate
    query_1h = (
        f'rate(http_requests_total{{app="{service}",status=~"5.."}}[1h]) / '
        f'rate(http_requests_total{{app="{service}"}}[1h])'
    )
    # 5-minute burn rate
    query_5m = (
        f'rate(http_requests_total{{app="{service}",status=~"5.."}}[5m]) / '
        f'rate(http_requests_total{{app="{service}"}}[5m])'
    )
    tool = MimirQueryTool()
    result_1h = await tool.safe_execute(query=query_1h)
    result_5m = await tool.safe_execute(query=query_5m)

    # Extract scalar values (first series, if any)
    def _scalar(r: ToolResult) -> Optional[float]:
        try:
            return float(r.data["result"][0]["value"])  # type: ignore[index]
        except (TypeError, KeyError, IndexError, ValueError):
            return None

    burn_1h = _scalar(result_1h)
    burn_5m = _scalar(result_5m)
    threshold = 14.0 * error_budget

    firing = (
        burn_1h is not None
        and burn_5m is not None
        and burn_1h > threshold
        and burn_5m > threshold
    )

    return ToolResult(
        tool_name="mimir_slo_burn_rate",
        success=result_1h.success or result_5m.success,
        data={
            "service": service,
            "slo_target": slo,
            "error_budget": error_budget,
            "burn_rate_1h": burn_1h,
            "burn_rate_5m": burn_5m,
            "multi_window_alert_firing": firing,
            "threshold_multiplier": 14.0,
        },
        duration_ms=result_1h.duration_ms + result_5m.duration_ms,
        query=f"slo_burn_rate(service={service}, slo={slo})",
    )


# ---------------------------------------------------------------------------
# Alias for time.monotonic — avoids shadowing the ``time`` parameter
# ---------------------------------------------------------------------------
time_module_time = time.monotonic
