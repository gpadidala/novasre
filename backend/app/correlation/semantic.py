"""
Semantic Correlator — Layer 3 of the 3-layer alert correlation engine.

Merges alert groups whose representative alert text is semantically similar
(cosine similarity above a configurable threshold) using OpenAI embeddings.
"""

import asyncio
import math
from typing import Any

import structlog

from app.correlation.temporal import AlertGroup, _get_alert_text
from app.config import settings

log = structlog.get_logger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity — avoids numpy import at module level."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticCorrelator:
    """
    Layer 3: Merge alert groups with semantically similar alert text.

    For each group the representative alert's name + annotations are
    concatenated and embedded using OpenAI ``text-embedding-3-large``.
    Groups whose representative embeddings exceed ``threshold`` cosine
    similarity are merged using Union-Find, same as the topological layer.

    If the OpenAI client is unavailable (e.g., no API key configured), the
    correlator logs a warning and returns groups unchanged so the pipeline
    degrades gracefully.
    """

    def __init__(self, threshold: float | None = None) -> None:
        self.threshold: float = (
            threshold
            if threshold is not None
            else settings.correlation_semantic_threshold
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def merge(self, groups: list[AlertGroup]) -> list[AlertGroup]:
        """
        Merge groups with similar representative alert text.

        Args:
            groups: AlertGroups from the topological layer.

        Returns:
            Merged list of AlertGroups (length <= input length).
        """
        if len(groups) <= 1:
            return groups

        texts = [self._group_text(g) for g in groups]
        embeddings = await self._embed_texts(texts)

        if embeddings is None:
            log.warning(
                "semantic_correlator.embedding_unavailable",
                message="Skipping semantic merge — OpenAI embeddings failed.",
            )
            return groups

        n = len(groups)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        for i in range(n):
            for j in range(i + 1, n):
                if find(i) == find(j):
                    continue
                sim = _cosine_similarity(embeddings[i], embeddings[j])
                if sim >= self.threshold:
                    log.debug(
                        "semantic_correlator.merging",
                        group_i=str(groups[i].group_id),
                        group_j=str(groups[j].group_id),
                        similarity=round(sim, 4),
                    )
                    union(i, j)

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
            "semantic_correlator.merged",
            input_groups=n,
            output_groups=len(merged),
            threshold=self.threshold,
        )
        return merged

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _group_text(self, group: AlertGroup) -> str:
        """Build a short text representation of a group for embedding."""
        if group.representative_alert is not None:
            base = _get_alert_text(group.representative_alert)
        else:
            base = ""
        # Append service context
        if group.services:
            base = f"{base} services:{','.join(sorted(group.services))}"
        return base.strip() or "unknown alert"

    async def _embed_texts(
        self, texts: list[str]
    ) -> list[list[float]] | None:
        """
        Embed a list of texts using OpenAI embeddings API.

        Returns None if the API call fails so callers can degrade gracefully.
        """
        if not settings.openai_api_key:
            log.warning(
                "semantic_correlator.no_api_key",
                message="OPENAI_API_KEY not set; semantic merge disabled.",
            )
            return None

        try:
            from openai import AsyncOpenAI  # lazy import

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.embeddings.create(
                model=settings.openai_embedding_model,
                input=texts,
            )
            # Response items are ordered by index
            sorted_data = sorted(response.data, key=lambda d: d.index)
            return [item.embedding for item in sorted_data]

        except Exception as exc:  # noqa: BLE001
            log.error(
                "semantic_correlator.embedding_error",
                error=str(exc),
                texts_count=len(texts),
            )
            return None
