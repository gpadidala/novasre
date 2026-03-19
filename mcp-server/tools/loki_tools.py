"""
Loki (LogQL) tool implementations.

All tools are read-only.
Tenant isolation is enforced via the X-Scope-OrgID header.
"""

from __future__ import annotations

import re
import time
from collections import Counter
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
class LokiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    loki_url: str = "http://localhost:3100"
    loki_tenant_id: str = "anonymous"


_settings = LokiSettings()


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
        base_url=_settings.loki_url,
        headers={"X-Scope-OrgID": _settings.loki_tenant_id},
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
        log.error("loki_http_error", status=exc.response.status_code, tool=tool_name)
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
            duration_ms=(time.monotonic() - start) * 1000,
            query=query,
        )
    except Exception as exc:
        log.error("loki_error", exc=str(exc), tool=tool_name)
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
class LokiQueryTool:
    """Execute a LogQL range query against Loki."""

    name = "loki_query_range"

    async def execute(
        self,
        query: str,
        start: str,
        end: str,
        limit: int = 100,
        direction: str = "backward",
    ) -> ToolResult:
        log.info("loki_query_range", query=query, start=start, end=end, limit=limit)
        params: dict[str, Any] = {
            "query":     query,
            "start":     start,
            "end":       end,
            "limit":     limit,
            "direction": direction,
        }
        result = await _get(
            "/loki/api/v1/query_range",
            params=params,
            tool_name=self.name,
            query=query,
        )

        # Flatten stream results into a simpler list of {ts, labels, line} dicts
        if result.success and result.data:
            try:
                streams = result.data.get("data", {}).get("result", [])
                lines = []
                for stream in streams:
                    labels = stream.get("stream", {})
                    for ts, line in stream.get("values", []):
                        lines.append({"timestamp": ts, "labels": labels, "line": line})
                result.data = {"lines": lines, "total": len(lines)}
            except Exception:
                pass  # Return raw data if flattening fails

        return result


class LokiErrorExtractionTool:
    """Extract and deduplicate error patterns from application logs."""

    name = "loki_extract_errors"

    async def execute(
        self,
        app: str,
        start: str,
        end: str,
        error_pattern: str = "ERROR|FATAL|panic|Exception",
        namespace: Optional[str] = None,
    ) -> ToolResult:
        log.info("loki_extract_errors", app=app, start=start, end=end)
        t0 = time.monotonic()

        # Build LogQL selector
        selector = f'{{app="{app}"}}'
        if namespace:
            selector = f'{{app="{app}", namespace="{namespace}"}}'

        logql_query = f'{selector} |~ `{error_pattern}` | line_format `{{{{.line}}}}`'

        raw = await _get(
            "/loki/api/v1/query_range",
            params={
                "query":     logql_query,
                "start":     start,
                "end":       end,
                "limit":     500,
                "direction": "backward",
            },
            tool_name=self.name,
            query=logql_query,
        )

        if not raw.success:
            return raw

        # Deduplicate: strip timestamps, UUIDs, IPs, and numbers to normalise messages
        error_counter: Counter[str] = Counter()
        raw_examples: dict[str, str] = {}

        _noise_pattern = re.compile(
            r"(\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^\s]*\b"  # timestamps
            r"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"  # UUIDs
            r"|\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"  # IPs
            r"|\b\d+\b)",  # bare numbers
            re.IGNORECASE,
        )

        streams = raw.data.get("data", {}).get("result", [])
        for stream in streams:
            for _ts, line in stream.get("values", []):
                normalised = _noise_pattern.sub("N", line).strip()
                # Truncate to first 200 chars for grouping key
                key = normalised[:200]
                error_counter[key] += 1
                if key not in raw_examples:
                    raw_examples[key] = line  # Keep original for display

        top_errors = [
            {"count": count, "pattern": pattern, "example": raw_examples[pattern]}
            for pattern, count in error_counter.most_common(10)
        ]

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "app":        app,
                "total_lines_scanned": sum(
                    len(s.get("values", [])) for s in streams
                ),
                "unique_patterns": len(error_counter),
                "top_errors": top_errors,
            },
            duration_ms=(time.monotonic() - t0) * 1000,
            query=logql_query,
        )
