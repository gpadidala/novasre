"""
Pyroscope (continuous profiling) tool implementations.

Pyroscope's HTTP API:
  GET /pyroscope/render   — rendered profile (flamebearer JSON or pprof)
  GET /pyroscope/merge    — merge two profiles (used for diff)

All tools are read-only.
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
class PyroscopeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    pyroscope_url: str = "http://localhost:4040"
    pyroscope_api_key: str = ""


_settings = PyroscopeSettings()


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
    headers: dict[str, str] = {}
    if _settings.pyroscope_api_key:
        headers["Authorization"] = f"Bearer {_settings.pyroscope_api_key}"
    return httpx.AsyncClient(
        base_url=_settings.pyroscope_url,
        headers=headers,
        timeout=60.0,  # profiles can be large
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
        log.error("pyroscope_http_error", status=exc.response.status_code, tool=tool_name)
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
            duration_ms=(time.monotonic() - start) * 1000,
            query=query,
        )
    except Exception as exc:
        log.error("pyroscope_error", exc=str(exc), tool=tool_name)
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=str(exc),
            duration_ms=(time.monotonic() - start) * 1000,
            query=query,
        )


def _extract_top_frames(flamebearer: dict[str, Any], top_n: int = 20) -> list[dict[str, Any]]:
    """Extract top-N functions by self time from flamebearer JSON."""
    names: list[str] = flamebearer.get("names", [])
    levels: list[list[int]] = flamebearer.get("levels", [])
    max_self: list[tuple[int, str]] = []

    for level in levels:
        # Each level: [x, total, self, name_idx, x, total, self, name_idx, ...]
        i = 0
        while i + 3 < len(level):
            self_time = level[i + 2]
            name_idx  = level[i + 3]
            if name_idx < len(names) and self_time > 0:
                max_self.append((self_time, names[name_idx]))
            i += 4

    top = sorted(max_self, key=lambda x: x[0], reverse=True)[:top_n]
    total_samples = flamebearer.get("numTicks", 1) or 1
    return [
        {
            "function": fn,
            "self_samples": samples,
            "self_pct": round(samples / total_samples * 100, 2),
        }
        for samples, fn in top
    ]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
class PyroscopeQueryTool:
    """Query Pyroscope for CPU/memory/goroutine profiles."""

    name = "pyroscope_query"

    async def execute(
        self,
        app_name: str,
        profile_type: str = "cpu",
        from_time: Optional[str] = None,
        until_time: Optional[str] = None,
    ) -> ToolResult:
        log.info("pyroscope_query", app=app_name, profile_type=profile_type)

        query_str = f"{app_name}.{profile_type}"
        params: dict[str, Any] = {
            "query":  query_str,
            "format": "json",
        }
        if from_time:
            params["from"]  = from_time
        if until_time:
            params["until"] = until_time

        result = await _get(
            "/pyroscope/render",
            params=params,
            tool_name=self.name,
            query=query_str,
        )

        if result.success and result.data:
            flamebearer = result.data.get("flamebearer", result.data)
            top_frames  = _extract_top_frames(flamebearer)
            result.data = {
                "app_name":     app_name,
                "profile_type": profile_type,
                "total_samples": flamebearer.get("numTicks", 0),
                "top_functions": top_frames,
                "flamebearer":  flamebearer,  # Full data for frontend flame graph
            }

        return result


class PyroscopeDiffTool:
    """Compare two profiling windows to detect regressions."""

    name = "pyroscope_diff"

    async def execute(
        self,
        app_name: str,
        baseline_start: str,
        baseline_end: str,
        comparison_start: str,
        comparison_end: str,
        profile_type: str = "cpu",
        top_n: int = 20,
    ) -> ToolResult:
        log.info(
            "pyroscope_diff",
            app=app_name,
            baseline_start=baseline_start,
            comparison_start=comparison_start,
        )
        t0 = time.monotonic()

        query_str = f"{app_name}.{profile_type}"

        # Fetch baseline and comparison profiles concurrently
        import asyncio
        baseline_task    = _get("/pyroscope/render", {"query": query_str, "from": baseline_start,    "until": baseline_end,    "format": "json"}, self.name, query_str)
        comparison_task  = _get("/pyroscope/render", {"query": query_str, "from": comparison_start,  "until": comparison_end,  "format": "json"}, self.name, query_str)

        baseline_result, comparison_result = await asyncio.gather(
            baseline_task, comparison_task
        )

        if not baseline_result.success:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"Baseline fetch failed: {baseline_result.error}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )
        if not comparison_result.success:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"Comparison fetch failed: {comparison_result.error}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # Build function self-time maps
        def _fn_map(data: dict[str, Any]) -> dict[str, int]:
            fb     = data.get("flamebearer", data)
            names  = fb.get("names", [])
            levels = fb.get("levels", [])
            m: dict[str, int] = {}
            for level in levels:
                i = 0
                while i + 3 < len(level):
                    self_time = level[i + 2]
                    name_idx  = level[i + 3]
                    if name_idx < len(names):
                        fn = names[name_idx]
                        m[fn] = m.get(fn, 0) + self_time
                    i += 4
            return m

        base_map = _fn_map(baseline_result.data or {})
        cmp_map  = _fn_map(comparison_result.data or {})

        base_total = sum(base_map.values()) or 1
        cmp_total  = sum(cmp_map.values()) or 1

        all_fns = set(base_map) | set(cmp_map)
        diffs = []
        for fn in all_fns:
            base_pct = base_map.get(fn, 0) / base_total * 100
            cmp_pct  = cmp_map.get(fn,  0) / cmp_total  * 100
            delta    = cmp_pct - base_pct
            if abs(delta) > 0.1:  # Only report meaningful changes
                diffs.append({
                    "function":    fn,
                    "baseline_pct": round(base_pct, 2),
                    "comparison_pct": round(cmp_pct, 2),
                    "delta_pct":   round(delta, 2),
                    "regression":  delta > 0,
                })

        top_regressions = sorted(diffs, key=lambda x: x["delta_pct"], reverse=True)[:top_n]
        top_improvements = sorted(diffs, key=lambda x: x["delta_pct"])[:top_n]

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "app_name":        app_name,
                "profile_type":    profile_type,
                "baseline_period": {"start": baseline_start, "end": baseline_end},
                "comparison_period": {"start": comparison_start, "end": comparison_end},
                "top_regressions":  top_regressions,
                "top_improvements": top_improvements,
            },
            duration_ms=(time.monotonic() - t0) * 1000,
            query=query_str,
        )
