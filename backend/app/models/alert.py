"""
Alert model — individual alert received from Alertmanager or Grafana.
Many alerts can be correlated into a single Incident.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.incident import Incident


class Alert(Base):
    """
    A single alert event from Alertmanager, Grafana, or a custom source.
    Alerts are correlated together and linked to an Incident.
    """

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Alert UUID",
    )
    name: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="Alert rule name"
    )
    fingerprint: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        comment="Alertmanager fingerprint (deduplication key)",
    )
    labels: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, comment="Alert labels (key-value pairs)"
    )
    annotations: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Alert annotations (summary, description, runbook, etc.)",
    )
    severity: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="warning",
        comment="Alert severity label (critical, warning, info)",
    )
    status: Mapped[str] = mapped_column(
        Enum("firing", "resolved", "suppressed", name="alert_status"),
        nullable=False,
        default="firing",
        comment="Current alert state",
    )
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="alertmanager",
        comment="Alert source system (alertmanager, grafana, custom)",
    )
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this alert started firing",
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this alert resolved",
    )
    incident_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incidents.id", ondelete="SET NULL"),
        nullable=True,
        comment="Associated incident (set after correlation)",
    )
    correlation_group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Correlation group UUID (set by correlation engine)",
    )

    # --- Relationships ---
    incident: Mapped[Optional["Incident"]] = relationship(
        "Incident",
        back_populates="alerts",
    )

    def __repr__(self) -> str:
        return f"<Alert id={self.id} name={self.name!r} status={self.status}>"
