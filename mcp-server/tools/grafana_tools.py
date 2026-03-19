"""
Grafana Enterprise tool implementations.

Covers:
  - Grafana Alerting (alert rules and their firing state)
  - Grafana Annotations (deployments, changes, incidents)

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
class GrafanaSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    grafana_url: str = "http://localhost:3000"
    grafana_api_key: str = ""
    grafana_org_id: int = 1


_settings = GrafanaSettings()


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
    headers = {
        "Authorization": f"Bearer {_settings.grafana_api_key}",
        "X-Grafana-Org-Id": str(_settings.grafana_org_id),
        "Content-Type": "application/json",
    }
    return httpx.AsyncClient(
        base_url=_settings.grafana_url,
        headers=headers,
        timeout=20.0,
    )


async def _get(
    path: str,
    params: dict[str, Any],
    tool_name: str,
    query: Optional[str] = None,
) -> ToolResult:
    t0 = time.monotonic()
    try:
        async with _build_client() as client:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            return ToolResult(
                tool_name=tool_name,
                success=True,
                data=resp.json(),
                duration_ms=(time.monotonic() - t0) * 1000,
                query=query,
            )
    except httpx.HTTPStatusError as exc:
        log.error("grafana_http_error", status=exc.response.status_code, path=path)
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
            duration_ms=(time.monotonic() - t0) * 1000,
            query=query,
        )
    except Exception as exc:
        log.error("grafana_error", exc=str(exc))
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=str(exc),
            duration_ms=(time.monotonic() - t0) * 1000,
            query=query,
        )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
class GrafanaAlertsTool:
    """Fetch active Grafana Alerting rules and their state."""

    name = "grafana_alerts"

    async def execute(
        self,
        state: str = "firing",
        labels: Optional[dict[str, str]] = None,
    ) -> ToolResult:
        log.info("grafana_alerts", state=state, labels=labels)

        # Grafana Alertmanager-compatible alerts endpoint
        params: dict[str, Any] = {}
        if state != "all":
            params["state"] = state

        result = await _get(
            "/api/alertmanager/grafana/api/v2/alerts",
            params=params,
            tool_name=self.name,
            query=f"state={state}",
        )

        if not result.success:
            # Fallback to unified alerting rules endpoint
            result = await _get(
                "/api/ruler/grafana/api/v1/rules",
                params={},
                tool_name=self.name,
                query=f"state={state} (rules fallback)",
            )

        if result.success and result.data:
            raw = result.data if isinstance(result.data, list) else []

            # Filter by labels if provided
            if labels:
                filtered = []
                for alert in raw:
                    alert_labels = alert.get("labels", {})
                    if all(alert_labels.get(k) == v for k, v in labels.items()):
                        filtered.append(alert)
                raw = filtered

            # Summarise each alert for LLM context
            summary = []
            for alert in raw:
                alert_labels = alert.get("labels", {})
                summary.append({
                    "alertname":  alert_labels.get("alertname", alert.get("name", "unknown")),
                    "severity":   alert_labels.get("severity", "unknown"),
                    "service":    alert_labels.get("app") or alert_labels.get("service") or alert_labels.get("job", "unknown"),
                    "namespace":  alert_labels.get("namespace", ""),
                    "state":      alert.get("status", {}).get("state", state),
                    "starts_at":  alert.get("startsAt"),
                    "ends_at":    alert.get("endsAt"),
                    "summary":    alert.get("annotations", {}).get("summary", ""),
                    "description": alert.get("annotations", {}).get("description", ""),
                    "labels":     alert_labels,
                    "generator_url": alert.get("generatorURL"),
                })

            result.data = {
                "state":  state,
                "count":  len(summary),
                "alerts": summary,
            }

        return result


class GrafanaAnnotationsTool:
    """
    Fetch Grafana annotations (deployments, config changes, incidents).

    This is one of the most important tools for RCA: a deployment annotation
    near the incident start time is often the root cause.
    """

    name = "grafana_annotations"

    async def execute(
        self,
        from_time: str,
        to_time: str,
        tags: Optional[list[str]] = None,
        limit: int = 100,
    ) -> ToolResult:
        log.info("grafana_annotations", from_time=from_time, to_time=to_time, tags=tags)

        params: dict[str, Any] = {
            "from":  from_time,
            "to":    to_time,
            "limit": limit,
            "type":  "annotation",
        }
        if tags:
            params["tags"] = tags  # httpx will repeat the key for list values

        result = await _get(
            "/api/annotations",
            params=params,
            tool_name=self.name,
            query=f"from={from_time} to={to_time} tags={tags}",
        )

        if result.success and result.data:
            raw = result.data if isinstance(result.data, list) else []
            annotations = []
            for ann in raw:
                annotations.append({
                    "id":          ann.get("id"),
                    "time":        ann.get("time"),
                    "time_end":    ann.get("timeEnd"),
                    "title":       ann.get("text") or ann.get("title", ""),
                    "tags":        ann.get("tags", []),
                    "login":       ann.get("login", ""),
                    "dashboard_id": ann.get("dashboardId"),
                    "panel_id":    ann.get("panelId"),
                })

            # Separate deployment-related annotations (common tag patterns)
            deployment_tags = {"deployment", "deploy", "release", "rollout", "cd"}
            deployments = [
                a for a in annotations
                if any(t.lower() in deployment_tags for t in a.get("tags", []))
            ]

            result.data = {
                "total":       len(annotations),
                "annotations": annotations,
                "deployments": deployments,  # Highlight likely root-cause events
            }

        return result
