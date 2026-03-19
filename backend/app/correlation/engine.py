"""
AlertCorrelationEngine — Orchestrates the full 3-layer alert correlation pipeline.

Usage::

    engine = AlertCorrelationEngine()
    groups = await engine.correlate(alerts, service_graph={"checkout": ["postgres"]})
    stats  = engine.get_noise_reduction_stats(len(alerts), len(groups))
"""

from typing import Any

import structlog

from app.config import settings
from app.correlation.semantic import SemanticCorrelator
from app.correlation.temporal import AlertGroup, TemporalCorrelator
from app.correlation.topological import TopologicalCorrelator

log = structlog.get_logger(__name__)


class AlertCorrelationEngine:
    """
    Orchestrates 3-layer alert correlation to reduce noise by 85-95%.

    Layer 1 — Temporal:    Alerts firing within a time window are grouped.
    Layer 2 — Topological: Groups whose services are connected in the
                           dependency graph are merged.
    Layer 3 — Semantic:    Groups with semantically similar alert text
                           (embedding cosine similarity) are merged.
    """

    def __init__(
        self,
        temporal_window_seconds: int | None = None,
        semantic_threshold: float | None = None,
        topological_depth: int | None = None,
    ) -> None:
        self.temporal = TemporalCorrelator(
            window_seconds=(
                temporal_window_seconds
                if temporal_window_seconds is not None
                else settings.correlation_temporal_window_seconds
            )
        )
        self.topological = TopologicalCorrelator(
            max_depth=(
                topological_depth
                if topological_depth is not None
                else settings.correlation_topological_depth
            )
        )
        self.semantic = SemanticCorrelator(
            threshold=(
                semantic_threshold
                if semantic_threshold is not None
                else settings.correlation_semantic_threshold
            )
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def correlate(
        self,
        alerts: list[Any],
        service_graph: dict[str, list[str]] | None = None,
    ) -> list[AlertGroup]:
        """
        Run the full 3-layer correlation pipeline.

        Args:
            alerts:        List of Alert ORM objects or plain dicts.
            service_graph: Directed adjacency list for topological merging.
                           Format: { "service-a": ["dep-1", "dep-2"], ... }
                           If None, topological merging is skipped.

        Returns:
            List of AlertGroup instances representing correlated clusters.
            Each group can be promoted to an Incident by the AlertService.
        """
        if not alerts:
            return []

        original_count = len(alerts)
        log.info(
            "correlation_engine.start",
            alert_count=original_count,
        )

        # Layer 1 — Temporal grouping
        temporal_groups = self.temporal.group(alerts)
        log.info(
            "correlation_engine.after_temporal",
            groups=len(temporal_groups),
        )

        # Layer 2 — Topological merging
        topo_groups = await self.topological.merge(
            temporal_groups, service_graph or {}
        )
        log.info(
            "correlation_engine.after_topological",
            groups=len(topo_groups),
        )

        # Layer 3 — Semantic merging
        final_groups = await self.semantic.merge(topo_groups)
        log.info(
            "correlation_engine.after_semantic",
            groups=len(final_groups),
        )

        stats = self.get_noise_reduction_stats(original_count, len(final_groups))
        log.info(
            "correlation_engine.complete",
            **stats,
        )

        return final_groups

    # ------------------------------------------------------------------

    def get_noise_reduction_stats(
        self, original_count: int, group_count: int
    ) -> dict[str, Any]:
        """
        Compute noise-reduction statistics.

        Args:
            original_count: Total number of raw alerts before correlation.
            group_count:    Number of AlertGroups after correlation.

        Returns:
            Dict with keys:
              - original_count     int   Raw alert count
              - groups_count       int   Correlated group count
              - noise_suppressed   int   Alerts "absorbed" into groups
              - reduction_pct      float Percentage noise reduction (0-100)
        """
        if original_count == 0:
            return {
                "original_count": 0,
                "groups_count": 0,
                "noise_suppressed": 0,
                "reduction_pct": 0.0,
            }

        noise_suppressed = max(0, original_count - group_count)
        reduction_pct = round((noise_suppressed / original_count) * 100, 2)

        return {
            "original_count": original_count,
            "groups_count": group_count,
            "noise_suppressed": noise_suppressed,
            "reduction_pct": reduction_pct,
        }
