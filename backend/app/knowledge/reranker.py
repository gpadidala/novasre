"""
CrossEncoderReranker — neural reranking using OpenAI relevance scoring.

Re-scores candidate documents using GPT-4o-mini's logprob for a yes/no
relevance token, then re-orders by descending relevance probability.
This is the "LLM-as-judge" reranking pattern commonly used in RAG pipelines.
"""

from typing import Any, Optional

import structlog

from app.config import settings

log = structlog.get_logger(__name__)


class CrossEncoderReranker:
    """
    Rerank candidate documents by query relevance using an LLM judge.

    Strategy:
      For each (query, document) pair, prompt GPT-4o-mini to answer
      "Is this document relevant to the query? Answer YES or NO."
      The log-probability of the YES token is used as the relevance score.

    Falls back to returning candidates in their input order when the
    OpenAI API is unavailable, ensuring the pipeline never hard-fails.

    Args:
        model: OpenAI model to use for scoring (default: settings.openai_model_fast).
        batch_size: Number of documents to score per API call round.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        batch_size: int = 10,
    ) -> None:
        self.model = model or settings.openai_model_fast
        self.batch_size = batch_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def rerank(
        self,
        query: str,
        candidates: list[Any],
        top_k: int = 10,
    ) -> list[Any]:
        """
        Rerank a list of candidate documents by relevance to ``query``.

        Args:
            query:      The user / agent query string.
            candidates: List of document objects.  Each must expose a
                        ``page_content`` or ``text`` attribute, or be a
                        plain string or dict with a ``text`` / ``content`` key.
            top_k:      Maximum number of documents to return after reranking.

        Returns:
            The ``top_k`` most relevant documents, sorted by descending score.
        """
        if not candidates:
            return []

        if not settings.openai_api_key:
            log.warning(
                "reranker.no_api_key",
                message="OpenAI API key not set; returning candidates in original order.",
            )
            return candidates[:top_k]

        scored = await self._score_all(query, candidates)
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [doc for doc, _ in scored[:top_k]]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _score_all(
        self,
        query: str,
        candidates: list[Any],
    ) -> list[tuple[Any, float]]:
        """Score each candidate and return (candidate, score) pairs."""
        import asyncio

        # Process in batches to avoid hitting rate limits
        tasks = []
        for candidate in candidates:
            tasks.append(self._score_one(query, candidate))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        scored: list[tuple[Any, float]] = []
        for candidate, result in zip(candidates, results):
            if isinstance(result, Exception):
                log.debug(
                    "reranker.score_error",
                    error=str(result),
                    candidate_repr=repr(candidate)[:80],
                )
                scored.append((candidate, 0.0))
            else:
                scored.append((candidate, float(result)))  # type: ignore[arg-type]

        return scored

    async def _score_one(self, query: str, candidate: Any) -> float:
        """
        Score a single (query, document) pair.

        Returns a probability-like float in [0, 1] representing relevance.
        """
        from openai import AsyncOpenAI  # lazy import

        doc_text = self._extract_text(candidate)
        if not doc_text.strip():
            return 0.0

        # Truncate to avoid exceeding context window
        truncated_text = doc_text[:2000]

        prompt = (
            f"Query: {query}\n\n"
            f"Document: {truncated_text}\n\n"
            "Is this document relevant to answering the query? "
            "Answer with exactly YES or NO."
        )

        client = AsyncOpenAI(api_key=settings.openai_api_key)

        response = await client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1,
            logprobs=True,
            top_logprobs=2,
            temperature=0,
        )

        # Extract log-probability of the first token
        choice = response.choices[0]
        if (
            choice.logprobs
            and choice.logprobs.content
            and choice.logprobs.content[0].top_logprobs
        ):
            import math

            for lp in choice.logprobs.content[0].top_logprobs:
                token = lp.token.strip().upper()
                if token in ("YES", "Y"):
                    return math.exp(lp.logprob)

        # Fallback: check if the text response starts with YES
        text_response = (choice.message.content or "").strip().upper()
        return 1.0 if text_response.startswith("YES") else 0.0

    @staticmethod
    def _extract_text(candidate: Any) -> str:
        """Extract plain text from various document representations."""
        if isinstance(candidate, str):
            return candidate
        if isinstance(candidate, dict):
            return (
                candidate.get("text")
                or candidate.get("content")
                or candidate.get("page_content")
                or ""
            )
        # LangChain Document or similar object
        for attr in ("page_content", "text", "content"):
            val = getattr(candidate, attr, None)
            if val:
                return str(val)
        return str(candidate)
