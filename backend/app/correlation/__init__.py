"""
Alert Correlation — 3-layer alert correlation engine.

Reduces alert noise by 85-95% through:
  - Layer 1: Temporal correlation (time-window grouping)
  - Layer 2: Topological correlation (service dependency graph)
  - Layer 3: Semantic correlation (embedding similarity)
"""

from app.correlation.engine import AlertCorrelationEngine
from app.correlation.semantic import SemanticCorrelator
from app.correlation.temporal import AlertGroup, TemporalCorrelator
from app.correlation.topological import TopologicalCorrelator

__all__ = [
    "AlertCorrelationEngine",
    "AlertGroup",
    "TemporalCorrelator",
    "TopologicalCorrelator",
    "SemanticCorrelator",
]
