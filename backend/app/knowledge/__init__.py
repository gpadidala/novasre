"""
RAPTOR Knowledge Base — Recursive Abstractive Processing for Tree-Organized Retrieval.

Based on the ICLR 2024 paper (https://arxiv.org/abs/2401.18059).

Components:
  - EmbeddingService:          OpenAI text-embedding-3-large wrapper
  - BM25Retriever:             Sparse keyword retrieval (rank_bm25)
  - CrossEncoderReranker:      Neural reranking via OpenAI scoring
  - RAPTORKnowledgeBase:       Hierarchical RAG over runbooks + incidents
  - KnowledgeIngestionPipeline: High-level ingestion for runbooks and incidents
"""

from app.knowledge.bm25 import BM25Retriever
from app.knowledge.embeddings import EmbeddingService
from app.knowledge.ingestion import KnowledgeIngestionPipeline
from app.knowledge.raptor import RAPTORKnowledgeBase
from app.knowledge.reranker import CrossEncoderReranker

__all__ = [
    "EmbeddingService",
    "BM25Retriever",
    "CrossEncoderReranker",
    "RAPTORKnowledgeBase",
    "KnowledgeIngestionPipeline",
]
