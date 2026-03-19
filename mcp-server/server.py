"""
NovaSRE MCP Server
==================
Exposes all observability tools (Mimir, Loki, Tempo, Pyroscope, Faro, Grafana)
via the Model Context Protocol (MCP).  External agents (Claude, GPT-4o, etc.)
can call these tools to interrogate the Grafana stack in read-only mode.

Start:
    python server.py          # stdio transport (default, for agent SDK)
    python server.py --http   # HTTP SSE transport on :8001

Environment variables are loaded from ../.env (or from the process environment).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    TextContent,
    Tool,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from tools.grafana_tools import GrafanaAlertsTool, GrafanaAnnotationsTool
from tools.faro_tools import FaroErrorsTool, FaroSessionsTool, FaroWebVitalsTool
from tools.loki_tools import LokiErrorExtractionTool, LokiQueryTool
from tools.mimir_tools import MimirLabelValuesTool, MimirQueryTool, MimirRangeTool
from tools.pyroscope_tools import PyroscopeDiffTool, PyroscopeQueryTool
from tools.tempo_tools import TempoGetTraceTool, TempoSearchTool, TempoSlowTracesTool

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer() if os.getenv("APP_ENV") == "development"
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
)
log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mcp_server_api_key: str = ""
    app_env: str = "development"


settings = MCPSettings()


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------
_TOOL_INSTANCES: dict[str, Any] = {
    "mimir_query":           MimirQueryTool(),
    "mimir_query_range":     MimirRangeTool(),
    "mimir_label_values":    MimirLabelValuesTool(),
    "loki_query_range":      LokiQueryTool(),
    "loki_extract_errors":   LokiErrorExtractionTool(),
    "tempo_search":          TempoSearchTool(),
    "tempo_get_trace":       TempoGetTraceTool(),
    "tempo_slow_traces":     TempoSlowTracesTool(),
    "pyroscope_query":       PyroscopeQueryTool(),
    "pyroscope_diff":        PyroscopeDiffTool(),
    "faro_web_vitals":       FaroWebVitalsTool(),
    "faro_errors":           FaroErrorsTool(),
    "faro_sessions":         FaroSessionsTool(),
    "grafana_alerts":        GrafanaAlertsTool(),
    "grafana_annotations":   GrafanaAnnotationsTool(),
}


# ---------------------------------------------------------------------------
# MCP Server definition
# ---------------------------------------------------------------------------
server: Server = Server("novasre-tools")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # ---------------------------------------------------------------
        # Mimir (PromQL)
        # ---------------------------------------------------------------
        Tool(
            name="mimir_query",
            description=(
                "Execute an instant PromQL query against Mimir/Prometheus. "
                "Returns a vector result at the specified time (or 'now')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "PromQL expression, e.g. rate(http_requests_total[5m])",
                    },
                    "time": {
                        "type": "string",
                        "description": "RFC3339 timestamp or Unix epoch. Defaults to now.",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="mimir_query_range",
            description=(
                "Execute a PromQL range query against Mimir to get a time series. "
                "Returns matrix results suitable for charting."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "PromQL expression"},
                    "start": {"type": "string", "description": "Start time (RFC3339 or relative like 'now-1h')"},
                    "end":   {"type": "string", "description": "End time (RFC3339 or 'now')"},
                    "step":  {"type": "string", "description": "Query resolution step, e.g. '60s' or '5m'. Defaults to '60s'."},
                },
                "required": ["query", "start", "end"],
            },
        ),
        Tool(
            name="mimir_label_values",
            description="List distinct values for a Prometheus label (e.g., list all 'app' values for service discovery).",
            inputSchema={
                "type": "object",
                "properties": {
                    "label_name": {"type": "string", "description": "Label name, e.g. 'app' or 'namespace'"},
                    "match":      {"type": "string", "description": "Optional series selector to filter, e.g. '{namespace=\"prod\"}'"},
                },
                "required": ["label_name"],
            },
        ),
        # ---------------------------------------------------------------
        # Loki (LogQL)
        # ---------------------------------------------------------------
        Tool(
            name="loki_query_range",
            description=(
                "Execute a LogQL query against Loki and return log lines "
                "within a time range. Supports filter expressions and JSON parsing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":     {"type": "string", "description": "LogQL expression, e.g. '{app=\"checkout\"} |= \"ERROR\"'"},
                    "start":     {"type": "string", "description": "Start time (RFC3339 or relative like 'now-30m')"},
                    "end":       {"type": "string", "description": "End time (RFC3339 or 'now')"},
                    "limit":     {"type": "integer", "description": "Max log lines to return. Defaults to 100.", "default": 100},
                    "direction": {"type": "string", "enum": ["backward", "forward"], "description": "Log sort order. Defaults to backward.", "default": "backward"},
                },
                "required": ["query", "start", "end"],
            },
        ),
        Tool(
            name="loki_extract_errors",
            description=(
                "Extract, deduplicate, and rank the top error patterns from "
                "application logs in Loki. Returns top-10 unique error messages with counts."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app":           {"type": "string", "description": "Application label value, e.g. 'checkout'"},
                    "start":         {"type": "string", "description": "Start time"},
                    "end":           {"type": "string", "description": "End time"},
                    "error_pattern": {"type": "string", "description": "Regex pattern to match errors. Defaults to 'ERROR|FATAL|panic|Exception'.", "default": "ERROR|FATAL|panic|Exception"},
                    "namespace":     {"type": "string", "description": "Optional Kubernetes namespace filter"},
                },
                "required": ["app", "start", "end"],
            },
        ),
        # ---------------------------------------------------------------
        # Tempo (TraceQL)
        # ---------------------------------------------------------------
        Tool(
            name="tempo_search",
            description=(
                "Search for distributed traces using TraceQL. Returns a list of "
                "trace summaries with root span service, operation, duration, and status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "TraceQL expression, e.g. '{ .service.name = \"checkout\" && status = error }'"},
                    "start": {"type": "string", "description": "Start time"},
                    "end":   {"type": "string", "description": "End time"},
                    "limit": {"type": "integer", "description": "Max traces to return. Defaults to 20.", "default": 20},
                },
                "required": ["query", "start", "end"],
            },
        ),
        Tool(
            name="tempo_get_trace",
            description=(
                "Fetch the full trace by trace ID, including all spans, "
                "their tags, logs, and parent/child relationships."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "trace_id": {"type": "string", "description": "Trace ID (hex string)"},
                },
                "required": ["trace_id"],
            },
        ),
        Tool(
            name="tempo_slow_traces",
            description=(
                "Find the slowest traces for a service within a time window. "
                "Useful for identifying tail-latency hotspots."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "service":      {"type": "string", "description": "Service name"},
                    "threshold_ms": {"type": "integer", "description": "Minimum duration in ms to consider a trace 'slow'. Defaults to 2000.", "default": 2000},
                    "start":        {"type": "string", "description": "Start time"},
                    "end":          {"type": "string", "description": "End time"},
                    "limit":        {"type": "integer", "description": "Max results. Defaults to 10.", "default": 10},
                },
                "required": ["service"],
            },
        ),
        # ---------------------------------------------------------------
        # Pyroscope (Continuous Profiling)
        # ---------------------------------------------------------------
        Tool(
            name="pyroscope_query",
            description=(
                "Query Pyroscope for CPU, memory, goroutine, or mutex profiles "
                "for an application. Returns flamebearer JSON for flame graph rendering."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_name":    {"type": "string", "description": "Application name as configured in Pyroscope"},
                    "profile_type": {
                        "type": "string",
                        "enum": ["cpu", "inuse_objects", "inuse_space", "alloc_objects", "alloc_space", "goroutine", "mutex_count", "mutex_duration"],
                        "description": "Profile type. Defaults to 'cpu'.",
                        "default": "cpu",
                    },
                    "from_time":  {"type": "string", "description": "Start time (Unix timestamp or relative like 'now-1h')"},
                    "until_time": {"type": "string", "description": "End time (Unix timestamp or 'now')"},
                },
                "required": ["app_name"],
            },
        ),
        Tool(
            name="pyroscope_diff",
            description=(
                "Compare two profiling time windows (baseline vs comparison) to detect "
                "performance regressions after a deployment. Returns top-N changed functions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_name":         {"type": "string"},
                    "profile_type":     {"type": "string", "default": "cpu"},
                    "baseline_start":   {"type": "string", "description": "Baseline window start"},
                    "baseline_end":     {"type": "string", "description": "Baseline window end"},
                    "comparison_start": {"type": "string", "description": "Comparison window start"},
                    "comparison_end":   {"type": "string", "description": "Comparison window end"},
                    "top_n":            {"type": "integer", "description": "Number of top changed functions to return. Defaults to 20.", "default": 20},
                },
                "required": ["app_name", "baseline_start", "baseline_end", "comparison_start", "comparison_end"],
            },
        ),
        # ---------------------------------------------------------------
        # Faro (Real User Monitoring)
        # ---------------------------------------------------------------
        Tool(
            name="faro_web_vitals",
            description=(
                "Query Faro for Core Web Vitals (LCP, INP, CLS, TTFB, FCP) "
                "for a frontend application. Returns P75 values per metric."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app":   {"type": "string", "description": "Faro application name"},
                    "page":  {"type": "string", "description": "Optional page URL filter, e.g. '/checkout'"},
                    "start": {"type": "string", "description": "Start time"},
                    "end":   {"type": "string", "description": "End time"},
                },
                "required": ["app"],
            },
        ),
        Tool(
            name="faro_errors",
            description=(
                "Query Faro for frontend JavaScript exceptions. "
                "Returns deduplicated error types with counts and representative stack traces."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app":   {"type": "string"},
                    "start": {"type": "string"},
                    "end":   {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["app"],
            },
        ),
        Tool(
            name="faro_sessions",
            description="Count the number of unique user sessions in Faro for impact assessment.",
            inputSchema={
                "type": "object",
                "properties": {
                    "app":   {"type": "string"},
                    "start": {"type": "string"},
                    "end":   {"type": "string"},
                },
                "required": ["app"],
            },
        ),
        # ---------------------------------------------------------------
        # Grafana
        # ---------------------------------------------------------------
        Tool(
            name="grafana_alerts",
            description=(
                "Fetch active alert rules from Grafana Alerting. "
                "Returns firing/pending alerts with their labels, annotations, and state."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "state":  {"type": "string", "enum": ["firing", "pending", "inactive", "all"], "default": "firing"},
                    "labels": {
                        "type": "object",
                        "description": "Optional label filters, e.g. {\"app\": \"checkout\"}",
                        "additionalProperties": {"type": "string"},
                    },
                },
            },
        ),
        Tool(
            name="grafana_annotations",
            description=(
                "Fetch Grafana annotations (deployments, config changes, incidents) "
                "within a time window. Critical for correlating incidents with deployments."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "from_time": {"type": "string", "description": "Start time (Unix ms or RFC3339)"},
                    "to_time":   {"type": "string", "description": "End time (Unix ms or RFC3339)"},
                    "tags":      {"type": "array", "items": {"type": "string"}, "description": "Optional tag filters, e.g. [\"deployment\", \"checkout\"]"},
                    "limit":     {"type": "integer", "default": 100},
                },
                "required": ["from_time", "to_time"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    log.info("mcp_tool_call", tool=name, arguments=arguments)

    tool = _TOOL_INSTANCES.get(name)
    if tool is None:
        raise ValueError(f"Unknown tool: {name!r}. Available: {list(_TOOL_INSTANCES)}")

    result = await tool.execute(**arguments)

    log.info(
        "mcp_tool_result",
        tool=name,
        success=result.success,
        duration_ms=result.duration_ms,
        error=result.error,
    )

    return [TextContent(type="text", text=result.model_dump_json(indent=2))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def _run_stdio() -> None:
    """Run MCP server over stdio (used by Claude agent SDK and similar)."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="novasre-tools",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=None,
                    experimental_capabilities={},
                ),
            ),
        )


# ---------------------------------------------------------------------------
# FastAPI HTTP app (for Docker health checks + REST tool calls)
# ---------------------------------------------------------------------------
app = FastAPI(title="NovaSRE MCP Server", version="0.1.0")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "tools": len(_TOOL_INSTANCES)})


@app.get("/tools")
async def list_tools_http() -> JSONResponse:
    return JSONResponse({"tools": list(_TOOL_INSTANCES.keys())})


@app.post("/call/{tool_name}")
async def call_tool_http(tool_name: str, body: dict[str, Any]) -> JSONResponse:
    tool = _TOOL_INSTANCES.get(tool_name)
    if tool is None:
        return JSONResponse({"error": f"Unknown tool: {tool_name}"}, status_code=404)
    result = await tool.execute(**body)
    return JSONResponse(result.model_dump())


def main() -> None:
    http_mode = "--http" in sys.argv
    if http_mode:
        log.info("novasre_mcp_server_starting", transport="http", port=8001)
        uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
    else:
        log.info("novasre_mcp_server_starting", transport="stdio")
        asyncio.run(_run_stdio())


if __name__ == "__main__":
    main()
