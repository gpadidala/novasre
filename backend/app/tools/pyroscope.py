"""
NovaSRE — Pyroscope (Continuous Profiling) Tool Implementations

Tools
-----
PyroscopeQueryTool — Fetch CPU/memory/goroutine profile (GET /pyroscope/render)
PyroscopeDiffTool  — Compare two profiles and return the top-N changed functions

Pyroscope returns profiles in "flamebearer" JSON format which the frontend
FlameGraph component can render directly.  The diff tool parses two flamebearer
payloads and computes per-function delta percentages.
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

# Valid Pyroscope profile types
PROFILE_TYPES = {
    "cpu": "cpu",
    "memory": "alloc_objects",
    "inuse_objects": "inuse_objects",
    "inuse_space": "inuse_space",
    "alloc_space": "alloc_space",
    "goroutines": "goroutine",
    "mutex": "mutex",
    "block": "block",
}


# ---------------------------------------------------------------------------
# Shared HTTP client
# ---------------------------------------------------------------------------

def _build_pyroscope_client() -> httpx.AsyncClient:
    settings = get_settings()
    headers: dict[str, str] = {"Accept": "application/json"}
    if settings.pyroscope_api_key:
        headers["Authorization"] = f"Bearer {settings.pyroscope_api_key}"
    return httpx.AsyncClient(
        base_url=settings.pyroscope_url,
        headers=headers,
        timeout=httpx.Timeout(60.0),  # Profiles can be large
    )


# ---------------------------------------------------------------------------
# Flamebearer parsing helpers
# ---------------------------------------------------------------------------

def _extract_function_totals(flamebearer: dict) -> dict[str, float]:
    """
    Build a mapping of ``function_name -> total_samples`` from a flamebearer.

    The flamebearer format stores names in ``names`` list and call-tree data
    in ``levels`` with format ``[x, total, self, name_index, ...]``.
    """
    names: list[str] = flamebearer.get("names", [])
    levels: list[list[int]] = flamebearer.get("levels", [])

    totals: dict[str, float] = {}

    for level in levels:
        i = 0
        while i + 3 < len(level):
            # Each node: [x_offset, total, self, name_index]
            total = level[i + 1]
            name_idx = level[i + 3]
            if 0 <= name_idx < len(names):
                name = names[name_idx]
                # Accumulate (a name can appear at multiple tree nodes)
                totals[name] = totals.get(name, 0) + total
            i += 4

    return totals


def _compute_diff(
    baseline_totals: dict[str, float],
    comparison_totals: dict[str, float],
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """
    Compute per-function sample deltas between two profiles.

    Returns top-N changed functions sorted by absolute delta descending.
    """
    # Normalise to percentages so different sample counts are comparable
    baseline_sum = sum(baseline_totals.values()) or 1.0
    comparison_sum = sum(comparison_totals.values()) or 1.0

    all_functions = set(baseline_totals) | set(comparison_totals)
    deltas: list[dict[str, Any]] = []

    for fn in all_functions:
        b_pct = (baseline_totals.get(fn, 0) / baseline_sum) * 100
        c_pct = (comparison_totals.get(fn, 0) / comparison_sum) * 100
        delta_pct = c_pct - b_pct

        if abs(delta_pct) < 0.01:  # Skip negligible changes
            continue

        deltas.append(
            {
                "function": fn,
                "baseline_pct": round(b_pct, 3),
                "comparison_pct": round(c_pct, 3),
                "delta_pct": round(delta_pct, 3),
                "direction": "increased" if delta_pct > 0 else "decreased",
            }
        )

    deltas.sort(key=lambda d: abs(d["delta_pct"]), reverse=True)
    return deltas[:top_n]


# ---------------------------------------------------------------------------
# PyroscopeQueryTool
# ---------------------------------------------------------------------------

class PyroscopeQueryTool(BaseTool):
    """
    Fetch a CPU/memory/goroutine profile from Pyroscope in flamebearer format.
    """

    name = "pyroscope_query"
    description = (
        "Fetch a continuous profiling snapshot from Pyroscope. "
        "Returns flamebearer JSON suitable for rendering a flame graph. "
        "Profile types: cpu, memory, goroutines, mutex, block. "
        "Use to identify hot functions, memory allocations, or goroutine leaks."
    )

    async def execute(  # type: ignore[override]
        self,
        app_name: str,
        profile_type: str = "cpu",
        from_time: Optional[str] = None,
        until_time: Optional[str] = None,
        max_nodes: int = 1024,
    ) -> ToolResult:
        """
        Parameters
        ----------
        app_name:
            Pyroscope application name, e.g. ``"checkout.cpu"``.
            If ``profile_type`` is provided separately, it will be appended.
        profile_type:
            One of ``cpu``, ``memory``, ``goroutines``, ``mutex``, ``block``.
        from_time:
            Start time as Unix timestamp or relative like ``now-30m``.
        until_time:
            End time (same format as ``from_time``).
        max_nodes:
            Maximum number of flame graph nodes (controls response size).
        """
        time_start = _mono()

        # Normalise profile type
        canonical_type = PROFILE_TYPES.get(profile_type, profile_type)

        # Build query string: Pyroscope uses format "app.type{labels}"
        if "." not in app_name:
            query = f"{app_name}.{canonical_type}"
        else:
            query = app_name  # already fully qualified

        log.info(
            "tool.execute",
            tool_name=self.name,
            app_name=app_name,
            profile_type=canonical_type,
            query=query,
        )

        params: dict[str, Any] = {
            "query": query,
            "format": "json",
            "maxNodes": max_nodes,
        }
        if from_time:
            params["from"] = from_time
        if until_time:
            params["until"] = until_time

        try:
            async with _build_pyroscope_client() as client:
                raw = await self._get(client, "/pyroscope/render", params=params)
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

        flamebearer = raw.get("flamebearer", raw)  # Handle both response shapes

        # Extract top-10 functions by sample count for a quick summary
        totals = _extract_function_totals(flamebearer)
        total_samples = sum(totals.values()) or 1
        top_functions = [
            {
                "function": fn,
                "samples": int(count),
                "pct": round((count / total_samples) * 100, 2),
            }
            for fn, count in sorted(totals.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            app_name=app_name,
            profile_type=canonical_type,
            total_samples=total_samples,
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "app": app_name,
                "profile_type": canonical_type,
                "flamebearer": flamebearer,
                "total_samples": total_samples,
                "top_functions": top_functions,
            },
            duration_ms=elapsed,
            query=query,
        )


# ---------------------------------------------------------------------------
# PyroscopeDiffTool
# ---------------------------------------------------------------------------

class PyroscopeDiffTool(BaseTool):
    """
    Compare two Pyroscope profiles and surface functions that changed the most.

    Typically used to detect CPU/memory regressions introduced by a deployment.
    """

    name = "pyroscope_diff"
    description = (
        "Compare two Pyroscope profiles (before/after) to find functions "
        "that increased or decreased in CPU/memory usage. "
        "Returns top-N changed functions with delta percentages. "
        "Use for deployment regression analysis."
    )

    async def execute(  # type: ignore[override]
        self,
        app_name: str,
        baseline_start: str,
        baseline_end: str,
        comparison_start: str,
        comparison_end: str,
        profile_type: str = "cpu",
        top_n: int = 20,
    ) -> ToolResult:
        """
        Parameters
        ----------
        app_name:
            Pyroscope application name.
        baseline_start / baseline_end:
            Time range for the baseline (pre-deployment) profile.
        comparison_start / comparison_end:
            Time range for the comparison (post-deployment) profile.
        profile_type:
            Profile type to compare.
        top_n:
            Number of top changed functions to return.
        """
        time_start = _mono()

        canonical_type = PROFILE_TYPES.get(profile_type, profile_type)
        if "." not in app_name:
            query = f"{app_name}.{canonical_type}"
        else:
            query = app_name

        log.info(
            "tool.execute",
            tool_name=self.name,
            app_name=app_name,
            profile_type=canonical_type,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            comparison_start=comparison_start,
            comparison_end=comparison_end,
        )

        # Fetch both profiles concurrently
        import asyncio

        async def _fetch(from_t: str, until_t: str) -> dict:
            params: dict[str, Any] = {
                "query": query,
                "format": "json",
                "from": from_t,
                "until": until_t,
            }
            async with _build_pyroscope_client() as client:
                return await self._get(client, "/pyroscope/render", params=params)

        try:
            baseline_raw, comparison_raw = await asyncio.gather(
                _fetch(baseline_start, baseline_end),
                _fetch(comparison_start, comparison_end),
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

        baseline_fb = baseline_raw.get("flamebearer", baseline_raw)
        comparison_fb = comparison_raw.get("flamebearer", comparison_raw)

        baseline_totals = _extract_function_totals(baseline_fb)
        comparison_totals = _extract_function_totals(comparison_fb)

        diff = _compute_diff(baseline_totals, comparison_totals, top_n=top_n)

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            app_name=app_name,
            changed_functions=len(diff),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "app": app_name,
                "profile_type": canonical_type,
                "baseline": {"start": baseline_start, "end": baseline_end},
                "comparison": {"start": comparison_start, "end": comparison_end},
                "changed_functions": diff,
                "total_functions_compared": len(
                    set(baseline_totals) | set(comparison_totals)
                ),
            },
            duration_ms=elapsed,
            query=f"diff({query})",
        )
