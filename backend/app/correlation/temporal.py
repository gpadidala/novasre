"""
Temporal Correlator — Layer 1 of the 3-layer alert correlation engine.

Groups alerts that fire within a configurable time window of each other.
Uses a sliding-window sweep-line algorithm for O(n log n) performance.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

log = structlog.get_logger(__name__)


@dataclass
class AlertGroup:
    """
    A cluster of temporally (and later topologically/semantically) correlated alerts.

    Attributes:
        group_id:            UUID identifying this correlation group.
        alerts:              The alert dicts/objects in this group.
        start_time:          Earliest fired_at among all alerts in the group.
        end_time:            Latest fired_at among all alerts in the group.
        representative_alert: The first alert (anchor) that started the group.
        services:            Set of service names extracted from alert labels.
        merged_from:         UUIDs of groups that were merged into this one (traceability).
    """

    group_id: uuid.UUID = field(default_factory=uuid.uuid4)
    alerts: list[Any] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    representative_alert: Optional[Any] = None
    services: set[str] = field(default_factory=set)
    merged_from: list[uuid.UUID] = field(default_factory=list)

    def add_alert(self, alert: Any) -> None:
        """Add an alert and update time boundaries and service set."""
        self.alerts.append(alert)
        fired_at = _get_fired_at(alert)
        if fired_at is not None:
            if self.start_time is None or fired_at < self.start_time:
                self.start_time = fired_at
            if self.end_time is None or fired_at > self.end_time:
                self.end_time = fired_at
        service = _get_service(alert)
        if service:
            self.services.add(service)

    def merge_from(self, other: "AlertGroup") -> None:
        """Absorb another group into this one."""
        self.merged_from.append(other.group_id)
        for alert in other.alerts:
            self.add_alert(alert)
        # Also union the services set directly so that groups whose services
        # were set without going through add_alert() are still propagated.
        self.services.update(other.services)


# ---------------------------------------------------------------------------
# Helpers to extract fields from both ORM Alert objects and plain dicts
# ---------------------------------------------------------------------------

def _get_fired_at(alert: Any) -> Optional[datetime]:
    """Return fired_at as a timezone-aware datetime, regardless of alert type."""
    if hasattr(alert, "fired_at"):
        val = alert.fired_at
    elif isinstance(alert, dict):
        val = alert.get("fired_at") or alert.get("startsAt")
    else:
        return None

    if val is None:
        return None
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return None
    elif isinstance(val, datetime):
        dt = val
    else:
        return None

    # Ensure timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _get_service(alert: Any) -> Optional[str]:
    """Extract a canonical service/app name from alert labels."""
    if hasattr(alert, "labels") and isinstance(alert.labels, dict):
        labels = alert.labels
    elif isinstance(alert, dict):
        labels = alert.get("labels", {})
    else:
        return None

    for key in ("app", "service", "job", "service_name", "namespace"):
        val = labels.get(key)
        if val:
            return str(val)
    return None


def _get_alert_text(alert: Any) -> str:
    """Build a single text string from alert name + annotations for hashing/logging."""
    name = ""
    annotations: dict = {}

    if hasattr(alert, "name"):
        name = alert.name or ""
    elif isinstance(alert, dict):
        name = alert.get("name") or alert.get("alertname") or ""

    if hasattr(alert, "annotations") and isinstance(alert.annotations, dict):
        annotations = alert.annotations
    elif isinstance(alert, dict):
        annotations = alert.get("annotations", {})

    summary = annotations.get("summary") or annotations.get("description") or ""
    return f"{name} {summary}".strip()


# ---------------------------------------------------------------------------
# TemporalCorrelator
# ---------------------------------------------------------------------------

class TemporalCorrelator:
    """
    Layer 1: Group alerts firing within ``window_seconds`` of each other.

    Algorithm:
      1. Sort alerts by fired_at ascending.
      2. Sweep through the sorted list. Start a new group whenever the
         current alert is more than ``window_seconds`` after the latest
         alert in the current group.
      3. Return one AlertGroup per cluster.

    Complexity: O(n log n) for the sort, O(n) for the sweep.
    """

    def __init__(self, window_seconds: int = 300) -> None:
        self.window_seconds = window_seconds

    def group(self, alerts: list[Any]) -> list[AlertGroup]:
        """
        Group alerts by time proximity.

        Args:
            alerts: List of Alert ORM objects or plain dicts.  Each must
                    expose a ``fired_at`` field (datetime or ISO-8601 str).

        Returns:
            List of AlertGroup instances, each containing temporally
            co-occurring alerts.
        """
        if not alerts:
            return []

        # Filter out alerts with no parseable fired_at and sort the rest
        dated: list[tuple[datetime, Any]] = []
        undated: list[Any] = []
        for alert in alerts:
            fired_at = _get_fired_at(alert)
            if fired_at is not None:
                dated.append((fired_at, alert))
            else:
                undated.append(alert)
                log.warning(
                    "temporal_correlator.missing_fired_at",
                    alert_repr=repr(alert)[:120],
                )

        dated.sort(key=lambda t: t[0])

        groups: list[AlertGroup] = []
        current_group: Optional[AlertGroup] = None
        window = timedelta(seconds=self.window_seconds)

        for fired_at, alert in dated:
            if current_group is None or (
                current_group.end_time is not None
                and fired_at - current_group.end_time > window
            ):
                # Start a new group
                current_group = AlertGroup()
                current_group.representative_alert = alert
                groups.append(current_group)

            current_group.add_alert(alert)

        # Undated alerts fall into a single catch-all group (if any)
        if undated:
            undated_group = AlertGroup()
            undated_group.representative_alert = undated[0]
            for alert in undated:
                undated_group.add_alert(alert)
            groups.append(undated_group)

        log.info(
            "temporal_correlator.grouped",
            total_alerts=len(alerts),
            total_groups=len(groups),
            window_seconds=self.window_seconds,
        )
        return groups
