"""
Mimir (Prometheus-compatible metrics) tool implementations.

All tools are read-only — they only query, never write.
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
class MimirSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mimir_url: str = "http://localhost:9090"
    mimir_tenant_id: str = "anonymous"
    mimir_basic_auth_user: str = ""
    mimir_basic_auth_password: str = ""


_settings = MimirSettings()


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
    headers = {"X-Scope-OrgID": _settings.mimir_tenant_id}
    auth = None
    if _settings.mimir_basic_auth_user:
        auth = (_settings.mimir_basic_auth_user, _settings.mimir_basic_auth_password)
    return httpx.AsyncClient(
        base_url=_settings.mimir_url,
        headers=headers,
        auth=auth,
        timeout=30.0,
    )


async def _post(
    path: str,
    data: dict[str, str],
    tool_name: str,
    query: Optional[str] = None,
) -> ToolResult:
    start = time.monotonic()
    try:
        async with _build_client() as client:
            resp = await client.post(path, data=data)
            resp.raise_for_status()
            return ToolResult(
                tool_name=tool_name,
                success=True,
                data=resp.json(),
                duration_ms=(time.monotonic() - start) * 1000,
                query=query,
            )
    except httpx.HTTPStatusError as exc:
        log.error("mimir_http_error", status=exc.response.status_code, tool=tool_name)
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
            duration_ms=(time.monotonic() - start) * 1000,
            query=query,
        )
    except Exception as exc:
        log.error("mimir_error", exc=str(exc), tool=tool_name)
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=str(exc),
            duration_ms=(time.monotonic() - start) * 1000,
            query=query,
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
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
            duration_ms=(time.monotonic() - start) * 1000,
            query=query,
        )
    except Exception as exc:
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=str(exc),
            duration_ms=(time.monotonic() - start) * 1000,
            query=query,
        )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
class MimirQueryTool:
    """Execute an instant PromQL query against Mimir."""

    name = "mimir_query"

    async def execute(
        self,
        query: str,
        time: Optional[str] = None,
    ) -> ToolResult:
        log.info("mimir_query", query=query, time=time)
        params: dict[str, str] = {"query": query}
        if time:
            params["time"] = time
        return await _post(
            "/prometheus/api/v1/query",
            data=params,
            tool_name=self.name,
            query=query,
        )

    async def get_error_rate(self, service: str, window: str = "5m") -> ToolResult:
        q = f'rate(http_requests_total{{app="{service}",status=~"5.."}}[{window}])'
        return await self.execute(query=q)

    async def get_latency_p99(self, service: str, window: str = "5m") -> ToolResult:
        q = (
            f'histogram_quantile(0.99, rate('
            f'http_request_duration_seconds_bucket{{app="{service}"}}[{window}]))'
        )
        return await self.execute(query=q)

    async def get_throughput(self, service: str, window: str = "5m") -> ToolResult:
        q = f'rate(http_requests_total{{app="{service}"}}[{window}])'
        return await self.execute(query=q)

    async def get_slo_burn_rate(self, service: str, slo: float = 99.9) -> ToolResult:
        """1-hour vs 5-minute SLO burn rate comparison."""
        error_budget = 1 - (slo / 100)
        q = (
            f'rate(http_requests_total{{app="{service}",status=~"5.."}}[1h]) / '
            f'rate(http_requests_total{{app="{service}"}}[1h]) / {error_budget}'
        )
        return await self.execute(query=q)


class MimirRangeTool:
    """Execute a PromQL range query (time series) against Mimir."""

    name = "mimir_query_range"

    async def execute(
        self,
        query: str,
        start: str,
        end: str,
        step: str = "60s",
    ) -> ToolResult:
        log.info("mimir_query_range", query=query, start=start, end=end, step=step)
        return await _post(
            "/prometheus/api/v1/query_range",
            data={"query": query, "start": start, "end": end, "step": step},
            tool_name=self.name,
            query=query,
        )


class MimirLabelValuesTool:
    """List distinct label values for service discovery."""

    name = "mimir_label_values"

    async def execute(
        self,
        label_name: str,
        match: Optional[str] = None,
    ) -> ToolResult:
        log.info("mimir_label_values", label_name=label_name)
        params: dict[str, Any] = {}
        if match:
            params["match[]"] = match
        return await _get(
            f"/prometheus/api/v1/label/{label_name}/values",
            params=params,
            tool_name=self.name,
        )
