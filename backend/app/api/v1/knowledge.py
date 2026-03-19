"""
Knowledge base ingestion and search endpoints.
POST /knowledge/ingest  — Ingest a document into RAPTOR
GET  /knowledge/search  — Semantic + BM25 hybrid search
GET  /knowledge         — List knowledge documents
"""
import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.dependencies import DbSession

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class IngestRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., min_length=1)
    document_type: str = Field(
        default="runbook",
        pattern="^(runbook|incident|postmortem|wiki|alert_rule)$",
    )
    source_url: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    id: str
    title: str
    document_type: str
    word_count: int
    chroma_id: Optional[str] = None
    status: str = "ingested"


class SearchResult(BaseModel):
    id: str
    title: str
    document_type: str
    excerpt: str
    score: float
    source_url: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest document into knowledge base",
)
async def ingest_document(
    payload: IngestRequest,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> IngestResponse:
    """
    Ingest a runbook, post-mortem, or wiki page into the RAPTOR knowledge base.
    The document is persisted immediately; embedding / indexing happens in background.
    """
    from app.models.knowledge import KnowledgeDocument

    word_count = len(payload.content.split())
    doc = KnowledgeDocument(
        title=payload.title,
        content=payload.content,
        document_type=payload.document_type,
        doc_metadata=payload.metadata,
        source_url=payload.source_url,
        word_count=word_count,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)

    log.info(
        "knowledge.document_ingested",
        doc_id=str(doc.id),
        doc_type=doc.document_type,
        word_count=word_count,
    )

    # Background: embed and index into ChromaDB via RAPTOR pipeline
    background_tasks.add_task(_embed_document_background, str(doc.id))

    return IngestResponse(
        id=str(doc.id),
        title=doc.title,
        document_type=doc.document_type,
        word_count=doc.word_count,
        chroma_id=doc.chroma_id,
    )


async def _embed_document_background(doc_id: str) -> None:
    """
    Background task: embed document into ChromaDB via RAPTOR pipeline.
    Will be wired to RAPTORKnowledgeBase in Phase 5.
    """
    log.info("knowledge.embedding_scheduled", doc_id=doc_id)
    # Phase 5: await raptor_kb.ingest(document, metadata)


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Hybrid semantic + BM25 knowledge search",
)
async def search_knowledge(
    db: DbSession,
    q: str = Query(..., min_length=1, description="Search query"),
    document_type: Optional[str] = Query(
        default=None, description="Filter by document type"
    ),
    top_k: int = Query(default=10, ge=1, le=50, description="Number of results"),
) -> SearchResponse:
    """
    Hybrid search over the knowledge base.
    Combines ChromaDB dense retrieval with BM25 sparse retrieval and reranking.
    Phase 5 will wire this to the full RAPTOR retrieval pipeline.
    """
    from sqlalchemy import select
    from app.models.knowledge import KnowledgeDocument

    stmt = select(KnowledgeDocument)
    if document_type:
        stmt = stmt.where(KnowledgeDocument.document_type == document_type)
    stmt = stmt.limit(top_k)
    result = await db.execute(stmt)
    docs = result.scalars().all()

    # Simple text-match fallback (Phase 5 replaces with RAPTOR retrieval)
    query_lower = q.lower()
    results = []
    for doc in docs:
        if query_lower in doc.title.lower() or query_lower in doc.content.lower():
            excerpt = _extract_excerpt(doc.content, q)
            results.append(
                SearchResult(
                    id=str(doc.id),
                    title=doc.title,
                    document_type=doc.document_type,
                    excerpt=excerpt,
                    score=1.0,
                    source_url=doc.source_url,
                    metadata=doc.doc_metadata,
                )
            )

    return SearchResponse(query=q, results=results[:top_k], total=len(results))


def _extract_excerpt(content: str, query: str, window: int = 200) -> str:
    """Extract a relevant excerpt around the first occurrence of the query."""
    idx = content.lower().find(query.lower())
    if idx == -1:
        return content[:window] + "..."
    start = max(0, idx - window // 2)
    end = min(len(content), idx + window // 2)
    excerpt = content[start:end]
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(content):
        excerpt = excerpt + "..."
    return excerpt


@router.get(
    "",
    summary="List knowledge documents",
)
async def list_documents(
    db: DbSession,
    document_type: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List all knowledge documents with pagination."""
    from sqlalchemy import func, select
    from app.models.knowledge import KnowledgeDocument

    stmt = select(KnowledgeDocument)
    count_stmt = select(func.count()).select_from(KnowledgeDocument)

    if document_type:
        stmt = stmt.where(KnowledgeDocument.document_type == document_type)
        count_stmt = count_stmt.where(KnowledgeDocument.document_type == document_type)

    stmt = stmt.offset(offset).limit(limit).order_by(KnowledgeDocument.created_at.desc())

    result = await db.execute(stmt)
    count_result = await db.execute(count_stmt)
    docs = result.scalars().all()
    total = count_result.scalar() or 0

    return {
        "items": [
            {
                "id": str(d.id),
                "title": d.title,
                "document_type": d.document_type,
                "word_count": d.word_count,
                "source_url": d.source_url,
                "created_at": d.created_at.isoformat(),
            }
            for d in docs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
