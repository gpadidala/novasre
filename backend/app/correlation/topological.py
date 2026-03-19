"""
Topological Correlator — Layer 2 of the 3-layer alert correlation engine.

Merges alert groups whose services are connected via the service dependency
graph up to a configurable BFS depth.
"""

from collections import deque

import structlog

from app.correlation.temporal import AlertGroup, _get_service
from app.config import settings

log = structlog.get_logger(__name__)


class TopologicalCorrelator:
    """
    Layer 2: Merge AlertGroups whose services share a dependency relationship.

    The service graph is supplied as a plain dict:
        { "service-a": ["service-b", "service-c"], ... }

    An undirected reachability check is performed up to
    ``settings.correlation_topological_depth`` BFS hops.  Two groups are
    merged when any service in group A can reach any service in group B
    within the depth limit.

    This captures cascade failures:  if the database goes down and triggers
    alerts in both the auth-service and the checkout-service, those groups
    are merged because both depend on the database.
    """

    def __init__(self, max_depth: int | None = None) -> None:
        self.max_depth: int = (
            max_depth
            if max_depth is not None
            else settings.correlation_topological_depth
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def merge(
        self,
        groups: list[AlertGroup],
        service_graph: dict[str, list[str]] | None = None,
    ) -> list[AlertGroup]:
        """
        Merge groups connected through the service dependency graph.

        Args:
            groups:        AlertGroups produced by TemporalCorrelator.
            service_graph: Adjacency list { service: [dependency, ...] }.
                           If None or empty, groups are returned unchanged.

        Returns:
            Merged list of AlertGroups (length <= input length).
        """
        if not groups:
            return []

        if not service_graph:
            log.debug("topological_correlator.no_graph_skipping")
            return groups

        # Build an undirected adjacency set for O(1) neighbour lookup
        undirected = self._build_undirected(service_graph)

        # Resolve which groups to merge using Union-Find
        n = len(groups)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]  # path compression
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        # Pre-compute reachable sets per group (cached)
        reachable_cache: dict[int, set[str]] = {}
        for i, group in enumerate(groups):
            reachable_cache[i] = self._reachable(group.services, undirected)

        # Compare every pair of groups
        for i in range(n):
            for j in range(i + 1, n):
                if find(i) == find(j):
                    continue  # already in same component
                # Check if any service in group i can reach any in group j
                if reachable_cache[i] & groups[j].services:
                    union(i, j)
                elif reachable_cache[j] & groups[i].services:
                    union(i, j)

        # Collect components
        component_map: dict[int, AlertGroup] = {}
        for i, group in enumerate(groups):
            root = find(i)
            if root not in component_map:
                component_map[root] = AlertGroup()
                component_map[root].group_id = group.group_id
                component_map[root].representative_alert = group.representative_alert
            component_map[root].merge_from(group)

        merged = list(component_map.values())

        log.info(
            "topological_correlator.merged",
            input_groups=n,
            output_groups=len(merged),
        )
        return merged

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_undirected(
        self, graph: dict[str, list[str]]
    ) -> dict[str, set[str]]:
        """Convert directed adjacency list to undirected adjacency sets."""
        undirected: dict[str, set[str]] = {}
        for node, neighbours in graph.items():
            undirected.setdefault(node, set()).update(neighbours)
            for nbr in neighbours:
                undirected.setdefault(nbr, set()).add(node)
        return undirected

    def _reachable(
        self, sources: set[str], graph: dict[str, set[str]]
    ) -> set[str]:
        """BFS from all source nodes, returning visited set within max_depth."""
        visited: set[str] = set()
        # Queue entries: (node, depth)
        queue: deque[tuple[str, int]] = deque()
        for s in sources:
            if s in graph:
                queue.append((s, 0))
                visited.add(s)

        while queue:
            node, depth = queue.popleft()
            if depth >= self.max_depth:
                continue
            for neighbour in graph.get(node, set()):
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append((neighbour, depth + 1))

        return visited
