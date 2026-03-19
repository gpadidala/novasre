"""
NovaSRE Tool Layer

Exports all tool classes and the default tool registry.

Quick start
-----------
::

    from app.tools import get_default_registry

    registry = get_default_registry()
    tool = registry.get("mimir_query")
    result = await tool.safe_execute(query="up")

Or import individual tools directly::

    from app.tools import MimirQueryTool, LokiQueryTool
"""

# Base
from app.tools.base import BaseTool, CircuitBreaker, ToolResult

# Mimir
from app.tools.mimir import (
    MimirLabelValuesTool,
    MimirQueryTool,
    MimirRangeTool,
    get_error_rate,
    get_latency_p99,
    get_slo_burn_rate,
    get_throughput,
)

# Loki
from app.tools.loki import (
    LokiErrorExtractionTool,
    LokiInstantQueryTool,
    LokiQueryTool,
)

# Tempo
from app.tools.tempo import (
    TempoGetTraceTool,
    TempoSearchTool,
    TempoSlowTracesTool,
    build_waterfall,
)

# Pyroscope
from app.tools.pyroscope import PyroscopeDiffTool, PyroscopeQueryTool

# Faro
from app.tools.faro import FaroErrorsTool, FaroSessionsTool, FaroWebVitalsTool

# Grafana
from app.tools.grafana import (
    GrafanaAlertsTool,
    GrafanaAnnotationsTool,
    GrafanaDashboardTool,
)

# Kubernetes
from app.tools.kubernetes import (
    KubernetesEventsTool,
    KubernetesLogsTool,
    KubernetesPodsTool,
)

# Registry
from app.tools.registry import ToolRegistry, get_default_registry

__all__ = [
    # Base
    "BaseTool",
    "CircuitBreaker",
    "ToolResult",
    # Mimir
    "MimirQueryTool",
    "MimirRangeTool",
    "MimirLabelValuesTool",
    "get_error_rate",
    "get_latency_p99",
    "get_throughput",
    "get_slo_burn_rate",
    # Loki
    "LokiQueryTool",
    "LokiInstantQueryTool",
    "LokiErrorExtractionTool",
    # Tempo
    "TempoSearchTool",
    "TempoGetTraceTool",
    "TempoSlowTracesTool",
    "build_waterfall",
    # Pyroscope
    "PyroscopeQueryTool",
    "PyroscopeDiffTool",
    # Faro
    "FaroWebVitalsTool",
    "FaroErrorsTool",
    "FaroSessionsTool",
    # Grafana
    "GrafanaAlertsTool",
    "GrafanaAnnotationsTool",
    "GrafanaDashboardTool",
    # Kubernetes
    "KubernetesPodsTool",
    "KubernetesEventsTool",
    "KubernetesLogsTool",
    # Registry
    "ToolRegistry",
    "get_default_registry",
]
