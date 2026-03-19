"""
NovaSRE Tool Registry

Central registry that holds all available tools.  Agents pull tools from here
rather than importing individual modules directly, which keeps agent code
decoupled from implementation details and makes adding new tools trivial.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.tools.base import BaseTool

if TYPE_CHECKING:
    from langchain_core.tools import StructuredTool

log = structlog.get_logger()


class ToolRegistry:
    """
    Registry that stores tool instances keyed by their ``name`` attribute.

    Usage
    -----
    ::

        registry = ToolRegistry()
        registry.register(MimirQueryTool())
        tool = registry.get("mimir_query")
        result = await tool.safe_execute(query="up")
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, tool: BaseTool) -> None:
        """Register a single tool instance."""
        if tool.name in self._tools:
            log.warning("tool_registry.overwrite", tool_name=tool.name)
        self._tools[tool.name] = tool
        log.debug("tool_registry.registered", tool_name=tool.name)

    def register_many(self, tools: list[BaseTool]) -> None:
        """Register multiple tool instances at once."""
        for tool in tools:
            self.register(tool)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, name: str) -> BaseTool:
        """
        Return the tool with the given name.

        Raises ``KeyError`` if not found so callers get a clear error rather
        than a silent ``None``.
        """
        try:
            return self._tools[name]
        except KeyError:
            available = ", ".join(sorted(self._tools))
            raise KeyError(
                f"Tool '{name}' not found in registry. "
                f"Available tools: {available}"
            ) from None

    def get_optional(self, name: str) -> BaseTool | None:
        """Return the tool or ``None`` if not registered."""
        return self._tools.get(name)

    def list_all(self) -> list[BaseTool]:
        """Return all registered tool instances."""
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        """Return all registered tool names."""
        return sorted(self._tools)

    # ------------------------------------------------------------------
    # LangChain helpers
    # ------------------------------------------------------------------

    def to_langchain_tools(self) -> list["StructuredTool"]:
        """
        Return a list of LangChain ``StructuredTool`` objects.

        Pass this list to ``llm.bind_tools(registry.to_langchain_tools())``.
        """
        return [tool.to_langchain_tool() for tool in self._tools.values()]

    def to_langchain_tools_by_names(self, names: list[str]) -> list["StructuredTool"]:
        """Return LangChain tools for a subset of tool names."""
        return [self._tools[n].to_langchain_tool() for n in names if n in self._tools]

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        return f"<ToolRegistry tools={self.list_names()}>"


# ---------------------------------------------------------------------------
# Default registry — populated lazily on first access
# ---------------------------------------------------------------------------

_default_registry: ToolRegistry | None = None


def get_default_registry() -> ToolRegistry:
    """
    Return (and lazily build) the default global registry containing all
    production tools.

    Import is deferred inside this function so that individual tool modules
    can import from ``registry`` without creating circular imports.
    """
    global _default_registry  # noqa: PLW0603

    if _default_registry is not None:
        return _default_registry

    # Import all tool classes here to avoid circular imports at module level
    from app.tools.faro import FaroErrorsTool, FaroSessionsTool, FaroWebVitalsTool
    from app.tools.grafana import (
        GrafanaAlertsTool,
        GrafanaAnnotationsTool,
        GrafanaDashboardTool,
    )
    from app.tools.kubernetes import (
        KubernetesEventsTool,
        KubernetesLogsTool,
        KubernetesPodsTool,
    )
    from app.tools.loki import LokiErrorExtractionTool, LokiInstantQueryTool, LokiQueryTool
    from app.tools.mimir import MimirLabelValuesTool, MimirQueryTool, MimirRangeTool
    from app.tools.pyroscope import PyroscopeDiffTool, PyroscopeQueryTool
    from app.tools.tempo import TempoGetTraceTool, TempoSearchTool, TempoSlowTracesTool

    registry = ToolRegistry()
    registry.register_many(
        [
            # Mimir / Prometheus
            MimirQueryTool(),
            MimirRangeTool(),
            MimirLabelValuesTool(),
            # Loki
            LokiQueryTool(),
            LokiErrorExtractionTool(),
            LokiInstantQueryTool(),
            # Tempo
            TempoSearchTool(),
            TempoGetTraceTool(),
            TempoSlowTracesTool(),
            # Pyroscope
            PyroscopeQueryTool(),
            PyroscopeDiffTool(),
            # Faro
            FaroWebVitalsTool(),
            FaroErrorsTool(),
            FaroSessionsTool(),
            # Grafana
            GrafanaAlertsTool(),
            GrafanaAnnotationsTool(),
            GrafanaDashboardTool(),
            # Kubernetes
            KubernetesPodsTool(),
            KubernetesEventsTool(),
            KubernetesLogsTool(),
        ]
    )

    _default_registry = registry
    log.info("tool_registry.initialized", tool_count=len(registry))
    return registry
