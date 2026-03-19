"""
KnowledgeDocument model — stores metadata for documents ingested into the
RAPTOR knowledge base (runbooks, post-mortems, incident reports).
The actual vector embeddings live in ChromaDB; this table stores relational
metadata for filtering and audit purposes.
"""
import uuid
from typing import Optional

from sqlalchemy import Enum, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KnowledgeDocument(Base):
    """
    Metadata record for a document stored in the RAPTOR knowledge base.
    `chroma_id` links this row to the ChromaDB document collection.
    """

    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Knowledge document UUID",
    )
    title: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="Document title (runbook name, incident title, etc.)",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Full raw document text (Markdown / plain text)",
    )
    document_type: Mapped[str] = mapped_column(
        Enum(
            "runbook",
            "incident",
            "postmortem",
            "wiki",
            "alert_rule",
            name="document_type",
        ),
        nullable=False,
        default="runbook",
        comment="Type of knowledge document",
    )
    doc_metadata: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment=(
            "Arbitrary metadata: services, team, severity, rca_pattern, "
            "source_url, tags, etc."
        ),
    )
    chroma_id: Mapped[Optional[str]] = mapped_column(
        String(256),
        nullable=True,
        comment="ChromaDB document ID (set after successful embedding ingestion)",
    )
    source_url: Mapped[Optional[str]] = mapped_column(
        String(2048),
        nullable=True,
        comment="Original source URL (Confluence, GitHub, PagerDuty, etc.)",
    )
    word_count: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
        comment="Approximate word count for display",
    )

    def __repr__(self) -> str:
        return (
            f"<KnowledgeDocument id={self.id} type={self.document_type!r} "
            f"title={self.title!r}>"
        )
