"""
RAPTORKnowledgeBase — Recursive Abstractive Processing for Tree-Organized Retrieval.

Implements the ICLR 2024 RAPTOR paper (https://arxiv.org/abs/2401.18059).

Tree structure:
  Layer 0 — Raw 512-token chunks with 50-token overlap
  Layer 1 — GPT-4o-mini summaries of semantic clusters of Layer-0 chunks
  Layer 2 — Summaries of clusters of Layer-1 summaries
  ... (recurse until only 1 root node remains)

Retrieval uses hybrid dense + sparse + reranking:
  1. Dense  — ChromaDB cosine similarity
  2. Sparse — BM25
  3. RRF    — Reciprocal Rank Fusion merge
  4. Rerank — CrossEncoderReranker for final ordering
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from app.config import settings
from app.knowledge.bm25 import BM25Retriever
from app.knowledge.embeddings import EmbeddingService
from app.knowledge.reranker import CrossEncoderReranker

log = structlog.get_logger(__name__)

# Chunk sizes (in approximate characters; 1 token ≈ 4 chars)
_CHUNK_SIZE_CHARS = 2048      # ≈ 512 tokens
_CHUNK_OVERLAP_CHARS = 200    # ≈ 50 tokens
_MAX_TREE_DEPTH = 5           # Safety cap on recursion
_MIN_CLUSTER_SIZE = 2         # Don't summarise single-document "clusters"
_RRF_K = 60                   # RRF constant


@dataclass
class TreeNode:
    """A single node in the RAPTOR tree."""

    node_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    text: str = ""
    layer: int = 0
    parent_id: Optional[str] = None
    child_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)


class RAPTORKnowledgeBase:
    """
    RAPTOR hierarchical RAG knowledge base backed by ChromaDB.

    Supports ingesting any text document and retrieving semantically
    relevant passages via hybrid dense + sparse + reranked retrieval.
    """

    def __init__(self) -> None:
        self.embedder = EmbeddingService()
        self.bm25 = BM25Retriever()
        self.reranker = CrossEncoderReranker()
        self._chroma_client: Optional[Any] = None
        self._collection: Optional[Any] = None
        # In-memory BM25 corpus (rebuilt on each ingest call)
        self._bm25_corpus: list[str] = []
        self._bm25_ids: list[str] = []

    # ------------------------------------------------------------------
    # ChromaDB helpers
    # ------------------------------------------------------------------

    async def _get_collection(self) -> Any:
        """Lazy-initialise the ChromaDB async client and collection."""
        if self._collection is not None:
            return self._collection

        try:
            import chromadb  # type: ignore[import]

            loop = asyncio.get_event_loop()
            client = await loop.run_in_executor(
                None,
                lambda: chromadb.HttpClient(
                    host=settings.chroma_host,
                    port=settings.chroma_port,
                ),
            )
            collection_name = settings.chroma_collection_runbooks
            self._collection = await loop.run_in_executor(
                None,
                lambda: client.get_or_create_collection(
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"},
                ),
            )
            log.info(
                "raptor.chroma_collection_ready",
                collection=collection_name,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("raptor.chroma_init_error", error=str(exc))
            raise

        return self._collection

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        """
        Split text into overlapping chunks of approx 512 tokens.

        Uses character-level splitting with 50-token overlap.
        """
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + _CHUNK_SIZE_CHARS
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = end - _CHUNK_OVERLAP_CHARS
        return chunks

    # ------------------------------------------------------------------
    # Clustering helpers (sklearn GMM — CPU bound, run in executor)
    # ------------------------------------------------------------------

    @staticmethod
    def _gmm_cluster_sync(
        embeddings: list[list[float]],
        n_components: int,
    ) -> list[int]:
        """
        Cluster embeddings with Gaussian Mixture Model (synchronous).
        Returns a list of integer cluster labels.
        """
        import numpy as np
        from sklearn.mixture import GaussianMixture  # type: ignore[import]

        X = np.array(embeddings)
        n_components = min(n_components, len(embeddings))
        if n_components < 2:
            return [0] * len(embeddings)

        gm = GaussianMixture(
            n_components=n_components,
            covariance_type="full",
            random_state=42,
        )
        labels: list[int] = gm.fit_predict(X).tolist()
        return labels

    async def _cluster(
        self,
        embeddings: list[list[float]],
        n_components: int,
    ) -> list[int]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._gmm_cluster_sync,
            embeddings,
            n_components,
        )

    # ------------------------------------------------------------------
    # LLM summarisation helper
    # ------------------------------------------------------------------

    async def _summarise(self, texts: list[str]) -> str:
        """Summarise a cluster of text chunks using GPT-4o-mini."""
        if not settings.openai_api_key:
            # Concatenate as fallback when no LLM available
            return " ".join(texts)[:_CHUNK_SIZE_CHARS]

        from openai import AsyncOpenAI  # lazy import

        combined = "\n\n---\n\n".join(texts)
        truncated = combined[:6000]  # stay within token budget

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.openai_model_fast,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a technical documentation summariser. "
                        "Produce a concise but complete summary that preserves "
                        "all key technical facts, error types, service names, "
                        "and remediation steps from the provided text."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Summarise the following:\n\n{truncated}",
                },
            ],
            temperature=0,
            max_tokens=512,
        )
        return response.choices[0].message.content or " ".join(texts)[:_CHUNK_SIZE_CHARS]

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    async def ingest(self, document: str, metadata: dict[str, Any]) -> None:
        """
        Ingest a document into the RAPTOR tree.

        Steps:
          1. Chunk document into overlapping 512-token chunks.
          2. Embed all chunks with text-embedding-3-large.
          3. Cluster chunks by GMM semantic similarity.
          4. Summarise each cluster with GPT-4o-mini.
          5. Recursively cluster & summarise until a single root remains.
          6. Store ALL nodes (chunks + summaries) in ChromaDB.

        Args:
            document: Raw document text.
            metadata: Arbitrary metadata stored with every node
                      (e.g., {"type": "runbook", "service": "checkout"}).
        """
        log.info("raptor.ingest_start", doc_length=len(document), metadata=metadata)

        collection = await self._get_collection()

        # Layer 0: raw chunks
        chunks = self._chunk_text(document)
        if not chunks:
            log.warning("raptor.ingest_empty_document")
            return

        embeddings = await self.embedder.embed_batch(chunks)

        layer0_nodes: list[TreeNode] = []
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            node = TreeNode(
                text=chunk,
                layer=0,
                metadata={**metadata, "chunk_index": i},
                embedding=emb,
            )
            layer0_nodes.append(node)

        # Store Layer-0 nodes in ChromaDB
        await self._store_nodes(collection, layer0_nodes)

        # Recursively build summary layers
        current_nodes = layer0_nodes
        current_layer = 1

        while len(current_nodes) >= _MIN_CLUSTER_SIZE and current_layer <= _MAX_TREE_DEPTH:
            # Determine number of GMM components (sqrt heuristic)
            n_components = max(2, int(len(current_nodes) ** 0.5))

            embeds = [n.embedding for n in current_nodes]
            labels = await self._cluster(embeds, n_components=n_components)

            # Group nodes by cluster label
            clusters: dict[int, list[TreeNode]] = {}
            for node, label in zip(current_nodes, labels):
                clusters.setdefault(label, []).append(node)

            summary_nodes: list[TreeNode] = []
            for cluster_label, cluster_nodes in clusters.items():
                if len(cluster_nodes) < _MIN_CLUSTER_SIZE:
                    # Too small to summarise — carry forward as-is
                    summary_nodes.extend(cluster_nodes)
                    continue

                # Summarise cluster
                texts = [n.text for n in cluster_nodes]
                summary_text = await self._summarise(texts)
                summary_emb = await self.embedder.embed_text(summary_text)

                parent_node = TreeNode(
                    text=summary_text,
                    layer=current_layer,
                    child_ids=[n.node_id for n in cluster_nodes],
                    metadata={
                        **metadata,
                        "cluster_label": cluster_label,
                        "child_count": len(cluster_nodes),
                    },
                    embedding=summary_emb,
                )
                summary_nodes.append(parent_node)

                # Back-fill parent_id on children
                for child in cluster_nodes:
                    child.parent_id = parent_node.node_id

            # Store new summary nodes
            await self._store_nodes(collection, summary_nodes)

            log.debug(
                "raptor.ingest_layer_complete",
                layer=current_layer,
                input_nodes=len(current_nodes),
                output_nodes=len(summary_nodes),
            )

            if len(summary_nodes) >= len(current_nodes):
                # No compression happened — stop to avoid infinite loop
                break

            current_nodes = summary_nodes
            current_layer += 1

        log.info(
            "raptor.ingest_complete",
            layers_built=current_layer,
            total_chunk_count=len(chunks),
        )

        # Rebuild BM25 index (in-memory, all-collection scan is acceptable for now)
        await self._rebuild_bm25(collection)

    async def _store_nodes(self, collection: Any, nodes: list[TreeNode]) -> None:
        """Upsert a batch of TreeNode objects into ChromaDB."""
        if not nodes:
            return

        ids = [n.node_id for n in nodes]
        documents = [n.text for n in nodes]
        embeddings = [n.embedding for n in nodes]
        metadatas = [
            {
                **n.metadata,
                "layer": n.layer,
                "parent_id": n.parent_id or "",
                "child_ids": ",".join(n.child_ids),
            }
            for n in nodes
        ]

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: collection.upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            ),
        )

    async def _rebuild_bm25(self, collection: Any) -> None:
        """Reload all documents from ChromaDB and rebuild the BM25 index."""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: collection.get(include=["documents"]),
            )
            docs: list[str] = result.get("documents") or []
            ids: list[str] = result.get("ids") or []
            if docs:
                self._bm25_corpus = docs
                self._bm25_ids = ids
                self.bm25.index(docs, ids)
        except Exception as exc:  # noqa: BLE001
            log.warning("raptor.bm25_rebuild_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Retrieve
    # ------------------------------------------------------------------

    async def retrieve(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """
        Hybrid retrieval: dense + sparse + RRF + reranking.

        Steps:
          1. Dense retrieval from ChromaDB (cosine similarity).
          2. BM25 sparse retrieval (keyword matching).
          3. Reciprocal Rank Fusion to merge both ranked lists.
          4. CrossEncoderReranker to produce final ranked top_k.

        Args:
            query:  Natural language query string.
            top_k:  Maximum number of documents to return.

        Returns:
            List of document dicts with keys: ``id``, ``text``, ``metadata``, ``score``.
        """
        collection = await self._get_collection()
        fetch_k = top_k * 4  # over-fetch before RRF

        # 1. Dense retrieval
        query_embedding = await self.embedder.embed_text(query)
        loop = asyncio.get_event_loop()

        # Resolve collection count before entering the executor (await is not
        # allowed inside a lambda / non-async callable).
        col_count = await self._collection_count(collection)
        n_results = min(fetch_k, max(1, col_count))

        try:
            dense_result = await loop.run_in_executor(
                None,
                lambda: collection.query(
                    query_embeddings=[query_embedding],
                    n_results=n_results,
                    include=["documents", "metadatas", "distances"],
                ),
            )
            dense_ids: list[str] = dense_result["ids"][0]
            dense_docs: list[str] = dense_result["documents"][0]
            dense_metas: list[dict] = dense_result["metadatas"][0]
        except Exception as exc:  # noqa: BLE001
            log.error("raptor.dense_retrieval_error", error=str(exc))
            dense_ids, dense_docs, dense_metas = [], [], []

        # 2. Sparse BM25 retrieval
        bm25_results: list[tuple[str, float]] = self.bm25.retrieve(query, k=fetch_k)
        bm25_id_set = {doc_id for doc_id, _ in bm25_results}

        # 3. RRF merge
        fused: dict[str, float] = {}

        for rank, doc_id in enumerate(dense_ids):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (_RRF_K + rank + 1)

        for rank, (doc_id, _score) in enumerate(bm25_results):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (_RRF_K + rank + 1)

        # Build a doc lookup from dense results
        doc_lookup: dict[str, dict[str, Any]] = {}
        for doc_id, text, meta in zip(dense_ids, dense_docs, dense_metas):
            doc_lookup[doc_id] = {"id": doc_id, "text": text, "metadata": meta}

        # Sort by RRF score
        sorted_ids = sorted(fused.keys(), key=lambda k: fused[k], reverse=True)

        # Build candidate list for reranking
        candidates: list[dict[str, Any]] = []
        for doc_id in sorted_ids[: fetch_k]:
            if doc_id in doc_lookup:
                doc = dict(doc_lookup[doc_id])
                doc["score"] = fused[doc_id]
                candidates.append(doc)

        # 4. Rerank
        if not candidates:
            return []

        # Pass text strings to the reranker
        reranked_texts = await self.reranker.rerank(
            query=query,
            candidates=[c["text"] for c in candidates],
            top_k=top_k,
        )

        # Re-associate reranked texts with their full doc dicts
        text_to_doc = {c["text"]: c for c in candidates}
        final: list[dict[str, Any]] = []
        for text in reranked_texts:
            if text in text_to_doc:
                final.append(text_to_doc[text])

        # If reranker returned fewer than top_k, pad with remaining RRF results
        seen_texts = {d["text"] for d in final}
        for candidate in candidates:
            if len(final) >= top_k:
                break
            if candidate["text"] not in seen_texts:
                final.append(candidate)
                seen_texts.add(candidate["text"])

        return final[:top_k]

    async def _collection_count(self, collection: Any) -> int:
        """Return the number of documents in the collection."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, collection.count)
        except Exception:  # noqa: BLE001
            return 0
