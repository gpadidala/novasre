"""
BM25Retriever — sparse keyword retrieval using the rank_bm25 library.

Falls back to a simple TF-IDF-style term frequency implementation when
``rank_bm25`` is not installed so the knowledge pipeline never hard-crashes.
"""

import math
import re
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


def _tokenize(text: str) -> list[str]:
    """Lowercase and split on non-alphanumeric characters."""
    return [tok for tok in re.split(r"[^a-z0-9]+", text.lower()) if tok]


# ---------------------------------------------------------------------------
# Fallback: minimal BM25-style implementation (no external dependency)
# ---------------------------------------------------------------------------

class _FallbackBM25:
    """
    Minimal BM25 implementation (k1=1.5, b=0.75) for when rank_bm25 is absent.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._corpus: list[list[str]] = []
        self._doc_ids: list[str] = []
        self._avgdl: float = 0.0
        self._df: dict[str, int] = {}
        self._n: int = 0

    def index(self, tokenized_corpus: list[list[str]], doc_ids: list[str]) -> None:
        self._corpus = tokenized_corpus
        self._doc_ids = doc_ids
        self._n = len(tokenized_corpus)
        self._avgdl = (
            sum(len(d) for d in tokenized_corpus) / self._n if self._n else 0.0
        )
        # Document frequency
        self._df = {}
        for tokens in tokenized_corpus:
            for term in set(tokens):
                self._df[term] = self._df.get(term, 0) + 1

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        scores = [0.0] * self._n
        for term in query_tokens:
            if term not in self._df:
                continue
            idf = math.log(
                (self._n - self._df[term] + 0.5) / (self._df[term] + 0.5) + 1
            )
            for i, tokens in enumerate(self._corpus):
                tf = tokens.count(term)
                dl = len(tokens)
                denom = tf + self.k1 * (
                    1 - self.b + self.b * dl / self._avgdl if self._avgdl else 1
                )
                scores[i] += idf * (tf * (self.k1 + 1)) / denom
        return scores


# ---------------------------------------------------------------------------
# BM25Retriever
# ---------------------------------------------------------------------------

class BM25Retriever:
    """
    Sparse keyword retrieval over an indexed document corpus.

    Tries to use ``rank_bm25.BM25Okapi`` for performance; silently falls
    back to the built-in implementation when the library is not installed.

    Usage::

        retriever = BM25Retriever()
        retriever.index(documents=["doc text 1", "doc text 2"],
                        doc_ids=["id-1", "id-2"])
        results = retriever.retrieve("error timeout", k=5)
        # → [("id-1", 3.42), ("id-2", 1.18)]
    """

    def __init__(self) -> None:
        self._bm25: Optional[object] = None
        self._fallback: Optional[_FallbackBM25] = None
        self._doc_ids: list[str] = []
        self._indexed = False

    # ------------------------------------------------------------------
    # Build index
    # ------------------------------------------------------------------

    def index(self, documents: list[str], doc_ids: list[str]) -> None:
        """
        Build the BM25 index from a list of documents.

        Args:
            documents: Raw text strings (one per document).
            doc_ids:   Corresponding document identifiers.
        """
        if len(documents) != len(doc_ids):
            raise ValueError(
                f"documents ({len(documents)}) and doc_ids ({len(doc_ids)}) "
                "must have the same length."
            )

        self._doc_ids = list(doc_ids)
        tokenized = [_tokenize(doc) for doc in documents]

        try:
            from rank_bm25 import BM25Okapi  # type: ignore[import]

            self._bm25 = BM25Okapi(tokenized)
            self._fallback = None
            log.info("bm25_retriever.indexed", n=len(documents), backend="rank_bm25")
        except ImportError:
            log.warning(
                "bm25_retriever.rank_bm25_missing",
                message="rank_bm25 not installed; using built-in BM25.",
            )
            fb = _FallbackBM25()
            fb.index(tokenized, list(doc_ids))
            self._fallback = fb
            self._bm25 = None
            log.info("bm25_retriever.indexed", n=len(documents), backend="fallback")

        self._indexed = True

    # ------------------------------------------------------------------
    # Retrieve
    # ------------------------------------------------------------------

    def retrieve(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """
        Retrieve the top-k most relevant document IDs for a query.

        Args:
            query: The search query string.
            k:     Number of results to return.

        Returns:
            List of ``(doc_id, score)`` tuples sorted by descending score.
        """
        if not self._indexed:
            log.warning("bm25_retriever.not_indexed")
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        if self._bm25 is not None:
            scores: list[float] = self._bm25.get_scores(query_tokens)  # type: ignore[union-attr]
        elif self._fallback is not None:
            scores = self._fallback.get_scores(query_tokens)
        else:
            return []

        # Pair with doc_ids and sort descending
        paired = list(zip(self._doc_ids, scores))
        paired.sort(key=lambda t: t[1], reverse=True)
        return paired[:k]
