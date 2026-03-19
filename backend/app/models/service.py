"""
Service model — represents a microservice in the topology graph.
Used for topological alert correlation and SLO tracking.
"""
import uuid

from sqlalchemy import Float, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Service(Base):
    """
    A microservice or infrastructure component.
    The dependency graph (service → list[dependency_names]) enables
    topological correlation: an alert on a downstream service can be
    automatically linked to alerts on its upstream callers.
    """

    __tablename__ = "services"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Service UUID",
    )
    name: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        unique=True,
        comment="Unique service name (must match Kubernetes app label)",
    )
    namespace: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        default="default",
        comment="Kubernetes namespace",
    )
    team: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        default="",
        comment="Owning team name",
    )
    dependencies: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="List of service names this service depends on (outbound calls)",
    )
    slo_target: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=99.9,
        comment="Availability SLO target percentage (e.g. 99.9)",
    )
    labels: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Arbitrary key-value labels for filtering / grouping",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="Human-readable service description",
    )

    def __repr__(self) -> str:
        return f"<Service name={self.name!r} namespace={self.namespace!r}>"
