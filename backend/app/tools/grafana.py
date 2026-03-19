"""
NovaSRE — Grafana Tool Implementations

Tools
-----
GrafanaAlertsTool      — Fetch active/firing alerts via Grafana Alerting API
GrafanaAnnotationsTool — Fetch change/deployment annotations near incident time
GrafanaDashboardTool   — Fetch dashboard JSON by UID

All tools authenticate with a Bearer token (``GRAFANA_API_KEY``).
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

def _build_grafana_client() -> httpx.AsyncClient:
    settings = get_settings()
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if settings.grafana_api_key:
        headers["Authorization"] = f"Bearer {settings.grafana_api_key}"
    return httpx.AsyncClient(
        base_url=settings.grafana_url,
        headers=headers,
        timeout=httpx.Timeout(30.0),
    )


# ---------------------------------------------------------------------------
# GrafanaAlertsTool
# ---------------------------------------------------------------------------

class GrafanaAlertsTool(BaseTool):
    """
    Fetch active Grafana Alerting alerts.

    Supports filtering by state (``firing``, ``pending``, ``normal``) and by
    label key/value pairs.
    """

    name = "grafana_alerts"
    description = (
        "Fetch active Grafana alerts. "
        "Returns alert name, state, labels, annotations, and last evaluation time. "
        "Use to see which alerts are currently firing and correlate with incidents."
    )

    async def execute(  # type: ignore[override]
        self,
        state: str = "firing",
        labels: Optional[dict[str, str]] = None,
        limit: int = 100,
    ) -> ToolResult:
        """
        Parameters
        ----------
        state:
            Alert state filter: ``"firing"``, ``"pending"``, ``"normal"``,
            or ``"all"`` to skip state filtering.
        labels:
            Optional dict of label matchers, e.g. ``{"app": "checkout"}``.
        limit:
            Maximum number of alerts to return.
        """
        time_start = _mono()
        log.info(
            "tool.execute",
            tool_name=self.name,
            state=state,
            labels=labels,
        )

        params: dict[str, Any] = {}
        if state and state != "all":
            params["state"] = state

        # Grafana alert API supports label matchers via ``?label=key=value``
        if labels:
            params["label"] = [f"{k}={v}" for k, v in labels.items()]

        try:
            async with _build_grafana_client() as client:
                raw = await self._get(client, "/api/alerting/alerts", params=params)
        except httpx.HTTPStatusError as exc:
            # Try the Grafana 9+ unified alerting endpoint as fallback
            try:
                async with _build_grafana_client() as client:
                    raw = await self._get(
                        client, "/api/v1/provisioning/alert-rules", params={}
                    )
            except Exception:
                elapsed = round((_mono() - time_start) * 1000, 2)
                self._record_failure()
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    data=None,
                    error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                    duration_ms=elapsed,
                    query=f"grafana_alerts?state={state}",
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
                query=f"grafana_alerts?state={state}",
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        # Normalise the Grafana response format
        # Grafana can return either a list or {"data": [...]} or {"alerts": [...]}
        if isinstance(raw, list):
            raw_alerts = raw
        else:
            raw_alerts = (
                raw.get("alerts")
                or raw.get("data")
                or []
            )

        parsed = [
            {
                "id": alert.get("id") or alert.get("uid"),
                "name": alert.get("name") or alert.get("title"),
                "state": alert.get("state") or alert.get("status", {}).get("state"),
                "labels": alert.get("labels", {}),
                "annotations": alert.get("annotations", {}),
                "starts_at": alert.get("activeAt") or alert.get("startsAt"),
                "evaluated_at": alert.get("evaluatedAt"),
                "url": alert.get("url") or alert.get("generatorURL"),
                "severity": (
                    alert.get("labels", {}).get("severity")
                    or alert.get("severity")
                    or "unknown"
                ),
            }
            for alert in raw_alerts[:limit]
        ]

        # Apply label filters post-fetch if the API didn't honour them
        if labels:
            filtered = []
            for a in parsed:
                if all(a["labels"].get(k) == v for k, v in labels.items()):
                    filtered.append(a)
            parsed = filtered

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            state=state,
            alert_count=len(parsed),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"alerts": parsed, "total": len(parsed)},
            duration_ms=elapsed,
            query=f"grafana_alerts?state={state}",
        )


# ---------------------------------------------------------------------------
# GrafanaAnnotationsTool
# ---------------------------------------------------------------------------

class GrafanaAnnotationsTool(BaseTool):
    """
    Fetch Grafana annotations (deployments, changes) in a time window.

    Annotations are critical for correlating metric changes with deployments.
    This tool surfaces events like ``deploy: checkout v2.3.1`` that might
    explain a sudden latency or error-rate change.
    """

    name = "grafana_annotations"
    description = (
        "Fetch Grafana annotations (deployments, config changes, incidents) "
        "in a time window. Use to find deployments that coincide with metric "
        "anomalies — a deployment annotation 5 minutes before an error spike "
        "is strong evidence of a regression."
    )

    async def execute(  # type: ignore[override]
        self,
        from_time: str,
        to_time: str,
        tags: Optional[list[str]] = None,
        dashboard_id: Optional[int] = None,
        limit: int = 100,
    ) -> ToolResult:
        """
        Parameters
        ----------
        from_time:
            Start time as Unix milliseconds or RFC3339.
        to_time:
            End time (same format).
        tags:
            Optional list of annotation tags to filter by (e.g. ``["deploy"]``).
        dashboard_id:
            Optional Grafana dashboard ID to scope annotations.
        limit:
            Maximum number of annotations to return.
        """
        time_start = _mono()
        log.info(
            "tool.execute",
            tool_name=self.name,
            from_time=from_time,
            to_time=to_time,
            tags=tags,
        )

        params: dict[str, Any] = {
            "from": from_time,
            "to": to_time,
            "limit": limit,
            "type": "annotation",
        }
        if tags:
            params["tags"] = tags
        if dashboard_id is not None:
            params["dashboardId"] = dashboard_id

        try:
            async with _build_grafana_client() as client:
                raw = await self._get(client, "/api/annotations", params=params)
        except httpx.HTTPStatusError as exc:
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                duration_ms=elapsed,
                query=f"grafana_annotations?from={from_time}&to={to_time}",
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
                query=f"grafana_annotations?from={from_time}&to={to_time}",
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        annotations_raw = raw if isinstance(raw, list) else raw.get("result", [])

        parsed = [
            {
                "id": ann.get("id"),
                "dashboard_id": ann.get("dashboardId"),
                "panel_id": ann.get("panelId"),
                "time": ann.get("time"),  # Unix milliseconds
                "time_end": ann.get("timeEnd"),
                "text": ann.get("text", ""),
                "tags": ann.get("tags", []),
                "login": ann.get("login") or ann.get("email"),
                "is_region": ann.get("isRegion", False),
            }
            for ann in annotations_raw
        ]

        # Separate deployment annotations (tagged "deploy") from others
        deploy_annotations = [
            a for a in parsed
            if "deploy" in a["tags"] or "deployment" in a["tags"]
            or "deploy" in a["text"].lower()
        ]

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            total_annotations=len(parsed),
            deploy_annotations=len(deploy_annotations),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "annotations": parsed,
                "deployment_annotations": deploy_annotations,
                "total": len(parsed),
            },
            duration_ms=elapsed,
            query=f"grafana_annotations?from={from_time}&to={to_time}",
        )


# ---------------------------------------------------------------------------
# GrafanaDashboardTool
# ---------------------------------------------------------------------------

class GrafanaDashboardTool(BaseTool):
    """
    Fetch a Grafana dashboard definition by its UID.

    Useful for understanding what panels and metrics are tracked for a service,
    and for extracting panel titles to guide investigation questions.
    """

    name = "grafana_dashboard"
    description = (
        "Fetch a Grafana dashboard JSON by UID. "
        "Returns panel titles, data sources, and target queries. "
        "Use to understand what metrics are tracked for a service and "
        "extract useful PromQL/LogQL queries."
    )

    async def execute(  # type: ignore[override]
        self,
        uid: str,
    ) -> ToolResult:
        """
        Parameters
        ----------
        uid:
            Dashboard UID (e.g. ``"rYdddlPWk"``), visible in the dashboard URL.
        """
        time_start = _mono()
        log.info("tool.execute", tool_name=self.name, uid=uid)

        try:
            async with _build_grafana_client() as client:
                raw = await self._get(client, f"/api/dashboards/uid/{uid}")
        except httpx.HTTPStatusError as exc:
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                duration_ms=elapsed,
                query=f"dashboard/{uid}",
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
                query=f"dashboard/{uid}",
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        dashboard = raw.get("dashboard", {})
        meta = raw.get("meta", {})

        # Extract panel summaries without returning the full JSON (can be huge)
        panels: list[dict[str, Any]] = []
        for panel in dashboard.get("panels", []):
            targets = [
                {
                    "datasource": t.get("datasource"),
                    "expr": t.get("expr") or t.get("query") or t.get("rawSql"),
                    "legend": t.get("legendFormat") or t.get("alias"),
                }
                for t in panel.get("targets", [])
            ]
            panels.append(
                {
                    "id": panel.get("id"),
                    "title": panel.get("title", ""),
                    "type": panel.get("type", ""),
                    "description": panel.get("description", ""),
                    "targets": targets,
                }
            )

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            uid=uid,
            panel_count=len(panels),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "uid": uid,
                "title": dashboard.get("title", ""),
                "tags": dashboard.get("tags", []),
                "url": meta.get("url", ""),
                "panels": panels,
                "panel_count": len(panels),
            },
            duration_ms=elapsed,
            query=f"dashboard/{uid}",
        )
