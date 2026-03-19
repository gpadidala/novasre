"""
Incident model — the top-level entity representing a production incident.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.investigation import Investigation


class SeverityEnum(str):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class StatusEnum(str):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Incident(Base):
    """
    Production incident.  One incident can aggregate many correlated alerts
    and can have multiple investigation runs.
    """

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Incident UUID",
    )
    title: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="Short incident title"
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="Full incident description"
    )
    severity: Mapped[str] = mapped_column(
        Enum("P1", "P2", "P3", "P4", name="incident_severity"),
        nullable=False,
        default="P3",
        comment="Incident severity (P1=critical, P4=low)",
    )
    status: Mapped[str] = mapped_column(
        Enum("open", "investigating", "resolved", "closed", name="incident_status"),
        nullable=False,
        default="open",
        comment="Current incident status",
    )
    affected_services: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="List of service names affected by this incident",
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the incident started (first signal)",
    )
    resolved_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the incident was resolved",
    )

    # --- Relationships ---
    investigations: Mapped[list["Investigation"]] = relationship(
        "Investigation",
        back_populates="incident",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    alerts: Mapped[list["Alert"]] = relationship(
        "Alert",
        back_populates="incident",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Incident id={self.id} severity={self.severity} status={self.status}>"
