"""
KnowledgeIngestionPipeline — high-level ingestion interface.

Wraps RAPTORKnowledgeBase with domain-specific helpers for runbooks,
post-mortems, raw Markdown files, and completed incident investigations.

The self-learning loop:
  Every resolved incident's RCA is automatically ingested as institutional
  knowledge so the agent learns from past events.
"""

import re
import uuid
from datetime import datetime
from typing import Any, Optional

import structlog

from app.knowledge.raptor import RAPTORKnowledgeBase

log = structlog.get_logger(__name__)


class KnowledgeIngestionPipeline:
    """
    Ingestion pipeline for the RAPTOR knowledge base.

    Handles four document types:
      - ``ingest_runbook``   — standard runbook text with metadata
      - ``ingest_markdown``  — raw Markdown files (e.g., from a wiki/GitHub)
      - ``ingest_incident``  — completed incident + investigation records
      - ``ingest_text``      — arbitrary raw text with a custom metadata dict
    """

    def __init__(self, raptor: Optional[RAPTORKnowledgeBase] = None) -> None:
        self.raptor = raptor or RAPTORKnowledgeBase()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ingest_runbook(self, content: str, metadata: dict[str, Any]) -> str:
        """
        Ingest a runbook document.

        Args:
            content:  Raw runbook text (Markdown, plain text, etc.).
            metadata: Dict with keys such as ``service``, ``team``,
                      ``category``, ``title``.  Will be stored with every
                      node in ChromaDB.

        Returns:
            A document ID string that can be used for tracking.
        """
        doc_id = metadata.get("doc_id") or str(uuid.uuid4())
        enriched_meta = {
            "type": "runbook",
            "doc_id": doc_id,
            "ingested_at": datetime.utcnow().isoformat(),
            **metadata,
        }
        log.info(
            "ingestion.runbook_start",
            doc_id=doc_id,
            title=metadata.get("title", "untitled"),
        )
        await self.raptor.ingest(content, enriched_meta)
        log.info("ingestion.runbook_complete", doc_id=doc_id)
        return doc_id

    async def ingest_markdown(self, file_content: str, filename: str) -> str:
        """
        Ingest a raw Markdown file.

        Args:
            file_content: Raw Markdown string.
            filename:     Filename used to derive title and category.

        Returns:
            Document ID string.
        """
        doc_id = str(uuid.uuid4())
        title = re.sub(r"[-_]", " ", filename.removesuffix(".md")).strip().title()

        # Extract first H1 heading as title if present
        h1_match = re.search(r"^#\s+(.+)$", file_content, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1).strip()

        metadata: dict[str, Any] = {
            "type": "markdown",
            "doc_id": doc_id,
            "filename": filename,
            "title": title,
            "ingested_at": datetime.utcnow().isoformat(),
        }

        log.info("ingestion.markdown_start", filename=filename, doc_id=doc_id)
        await self.raptor.ingest(file_content, metadata)
        log.info("ingestion.markdown_complete", doc_id=doc_id)
        return doc_id

    async def ingest_incident(self, incident: Any, investigation: Any) -> str:
        """
        Ingest a completed incident + investigation as institutional knowledge.

        This is the self-learning loop.  Every resolved incident teaches the
        system about what patterns cause failures and how to fix them.

        Args:
            incident:      Incident ORM object or dict with fields:
                           id, title, severity, affected_services, start_time.
            investigation: Investigation ORM object or dict with fields:
                           findings, rca, confidence, tool_calls.

        Returns:
            Document ID string.
        """
        doc_id = str(uuid.uuid4())
        document = self._format_incident_for_kb(incident, investigation)
        rca_pattern = self._extract_rca_pattern(
            self._get_field(investigation, "rca") or ""
        )

        metadata: dict[str, Any] = {
            "type": "incident",
            "doc_id": doc_id,
            "incident_id": str(self._get_field(incident, "id") or ""),
            "severity": str(self._get_field(incident, "severity") or ""),
            "services": _json_safe(self._get_field(incident, "affected_services") or []),
            "rca_pattern": rca_pattern,
            "confidence": float(self._get_field(investigation, "confidence") or 0.0),
            "ingested_at": datetime.utcnow().isoformat(),
        }

        log.info(
            "ingestion.incident_start",
            incident_id=metadata["incident_id"],
            doc_id=doc_id,
        )
        await self.raptor.ingest(document, metadata)
        log.info("ingestion.incident_complete", doc_id=doc_id)
        return doc_id

    async def ingest_text(self, text: str, metadata: dict[str, Any]) -> str:
        """
        Ingest arbitrary raw text with a custom metadata dict.

        Args:
            text:     The document text.
            metadata: Metadata dict stored alongside all tree nodes.

        Returns:
            Document ID string.
        """
        doc_id = metadata.get("doc_id") or str(uuid.uuid4())
        enriched = {
            "type": "raw",
            "doc_id": doc_id,
            "ingested_at": datetime.utcnow().isoformat(),
            **metadata,
        }
        await self.raptor.ingest(text, enriched)
        return doc_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_incident_for_kb(self, incident: Any, investigation: Any) -> str:
        """
        Build a structured text document from an incident + investigation.

        The document is designed to be retrieved by future investigations
        asking questions like "have we seen this error before?".
        """
        title = self._get_field(incident, "title") or "Untitled Incident"
        severity = self._get_field(incident, "severity") or "unknown"
        services = self._get_field(incident, "affected_services") or []
        start_time = self._get_field(incident, "start_time") or ""
        rca = self._get_field(investigation, "rca") or "No RCA recorded."
        findings = self._get_field(investigation, "findings") or {}
        confidence = self._get_field(investigation, "confidence") or 0.0

        services_str = (
            ", ".join(services) if isinstance(services, list) else str(services)
        )

        # Format findings section
        findings_text = ""
        if isinstance(findings, dict):
            for signal, data in findings.items():
                if data:
                    findings_text += f"\n### {signal.title()} Signal\n{data}\n"

        document = f"""# Incident: {title}

## Incident Metadata
- **Severity**: {severity}
- **Affected Services**: {services_str}
- **Start Time**: {start_time}
- **Investigation Confidence**: {confidence:.0%}

## Signal Findings
{findings_text or "No findings recorded."}

## Root Cause Analysis
{rca}
"""
        return document.strip()

    def _extract_rca_pattern(self, rca: str) -> str:
        """
        Extract a short canonical pattern label from an RCA markdown string.

        Looks for the "Root Cause" section and returns the first sentence,
        normalised to lowercase.  Falls back to the first 100 characters.
        """
        if not rca:
            return "unknown"

        # Try to find the root cause section
        match = re.search(
            r"##\s*(?:🎯\s*)?root cause\s*\n+(.+?)(?:\n|$)",
            rca,
            re.IGNORECASE,
        )
        if match:
            raw = match.group(1).strip()
        else:
            raw = rca[:200]

        # Take the first sentence
        first_sentence = re.split(r"[.!?]", raw)[0].strip()
        # Normalise
        pattern = re.sub(r"[^a-z0-9 _-]", "", first_sentence.lower()).strip()
        return pattern[:100] or "unknown"

    @staticmethod
    def _get_field(obj: Any, field: str) -> Any:
        """Get a field from either an ORM object or a dict."""
        if isinstance(obj, dict):
            return obj.get(field)
        return getattr(obj, field, None)


def _json_safe(value: Any) -> str:
    """Convert a value to a JSON-serialisable string for ChromaDB metadata."""
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)
