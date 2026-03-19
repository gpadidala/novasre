"""
EmbeddingService — OpenAI text-embedding-3-large wrapper with batch support.

Provides async embedding for single texts and batches, plus a pure-Python
cosine similarity helper so callers don't need to import numpy.
"""

import math
from typing import Optional

import structlog

from app.config import settings

log = structlog.get_logger(__name__)

# OpenAI embedding batch size limit
_MAX_BATCH_SIZE = 2048


class EmbeddingService:
    """
    Async wrapper around the OpenAI Embeddings API.

    Uses ``text-embedding-3-large`` by default (configurable via
    ``settings.openai_embedding_model``).

    All methods raise ``RuntimeError`` when ``OPENAI_API_KEY`` is not
    configured so callers get a clear error rather than a cryptic 401.
    """

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or settings.openai_embedding_model
        self._client: Optional[object] = None  # lazy-initialised AsyncOpenAI

    def _get_client(self):  # type: ignore[return]
        """Return (and cache) an AsyncOpenAI client."""
        if self._client is None:
            if not settings.openai_api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY is not configured. "
                    "Set it in your .env file to enable embeddings."
                )
            from openai import AsyncOpenAI  # lazy import

            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def embed_text(self, text: str) -> list[float]:
        """
        Embed a single text string.

        Args:
            text: The string to embed.

        Returns:
            Dense embedding vector (list of floats).
        """
        if not text.strip():
            raise ValueError("Cannot embed an empty string.")

        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts in one or more API calls.

        Automatically batches requests to respect the OpenAI 2048-input limit.

        Args:
            texts: List of strings to embed.

        Returns:
            List of embedding vectors in the same order as the input.
        """
        if not texts:
            return []

        client = self._get_client()
        all_embeddings: list[list[float]] = []

        # Process in batches
        for batch_start in range(0, len(texts), _MAX_BATCH_SIZE):
            batch = texts[batch_start : batch_start + _MAX_BATCH_SIZE]
            # Replace empty strings with a placeholder to avoid API error
            safe_batch = [t if t.strip() else "[empty]" for t in batch]

            log.debug(
                "embedding_service.embed_batch",
                batch_size=len(safe_batch),
                model=self.model,
            )

            response = await client.embeddings.create(  # type: ignore[union-attr]
                model=self.model,
                input=safe_batch,
            )
            # Items come back indexed; sort to preserve input order
            sorted_data = sorted(response.data, key=lambda d: d.index)
            all_embeddings.extend(item.embedding for item in sorted_data)

        return all_embeddings

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """
        Compute cosine similarity between two dense vectors.

        Returns a value in [-1.0, 1.0].  Returns 0.0 for zero-norm vectors.
        """
        if len(a) != len(b):
            raise ValueError(
                f"Vector length mismatch: {len(a)} vs {len(b)}"
            )
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)
