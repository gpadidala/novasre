"""
AnomalyDetectionEngine — vote-based ensemble of 3 anomaly detectors.

Runs ZScoreDetector, ProphetDetector, and ChangepointDetector concurrently
and confirms anomalies where at least 2 of 3 detectors agree within a
configurable time tolerance.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from app.anomaly.changepoint import ChangepointDetector
from app.anomaly.prophet_detector import ProphetDetector
from app.anomaly.zscore import Anomaly, ZScoreDetector, _parse_timestamp

log = structlog.get_logger(__name__)

# Two anomalies are considered "co-located" if they are within this many
# seconds of each other.
_TEMPORAL_TOLERANCE_SECONDS = 60


@dataclass
class AnomalyResult:
    """
    Output of the ensemble anomaly detection.

    Attributes:
        metric_name:         The metric being analysed.
        anomalies:           Confirmed anomalies (voted by >= 2 detectors).
        all_detections:      Raw detections from every individual detector.
        ensemble_method:     Description of the voting strategy used.
        detector_agreement:  Per-detector summary: { name: count_detected }.
        total_input_points:  Number of data points in the input series.
    """

    metric_name: str
    anomalies: list[Anomaly] = field(default_factory=list)
    all_detections: dict[str, list[Anomaly]] = field(default_factory=dict)
    ensemble_method: str = "majority_vote_2_of_3"
    detector_agreement: dict[str, int] = field(default_factory=dict)
    total_input_points: int = 0


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _timestamps_close(a: datetime, b: datetime, tolerance_s: int) -> bool:
    a = _ensure_aware(a)
    b = _ensure_aware(b)
    return abs((a - b).total_seconds()) <= tolerance_s


def _vote_ensemble(
    results: dict[str, list[Anomaly]],
    tolerance_s: int = _TEMPORAL_TOLERANCE_SECONDS,
) -> list[Anomaly]:
    """
    Majority-vote ensemble.

    For each anomaly from any detector, check whether at least one other
    detector also flagged a point within ``tolerance_s`` seconds.  If so,
    include it in the confirmed list with the highest severity reported.
    """
    all_anomalies: list[tuple[str, Anomaly]] = []
    for detector_name, anoms in results.items():
        for a in anoms:
            all_anomalies.append((detector_name, a))

    if not all_anomalies:
        return []

    confirmed: list[Anomaly] = []
    used: set[int] = set()

    for i, (det_i, anom_i) in enumerate(all_anomalies):
        if i in used:
            continue

        # Find all anomalies from other detectors within tolerance
        agreeing: list[tuple[int, str, Anomaly]] = []
        for j, (det_j, anom_j) in enumerate(all_anomalies):
            if j == i or j in used:
                continue
            if det_j != det_i and _timestamps_close(
                anom_i.timestamp, anom_j.timestamp, tolerance_s
            ):
                agreeing.append((j, det_j, anom_j))

        if agreeing:
            # Mark all participants as used
            used.add(i)
            for j, _, _ in agreeing:
                used.add(j)

            # Pick the highest-severity representative
            all_candidates = [anom_i] + [a for _, _, a in agreeing]
            sev_order = {"high": 3, "medium": 2, "low": 1}
            representative = max(
                all_candidates, key=lambda a: sev_order.get(a.severity, 0)
            )
            confirmed.append(representative)

    return confirmed


class AnomalyDetectionEngine:
    """
    Unified anomaly detection API.

    Runs three detectors concurrently:
      1. ZScoreDetector  — fast rolling Z-score
      2. ProphetDetector — seasonal decomposition
      3. ChangepointDetector — structural change points

    Returns only anomalies confirmed by >= 2 of the 3 detectors
    (majority vote), reducing false positives significantly.
    """

    def __init__(self) -> None:
        self.zscore = ZScoreDetector()
        self.prophet = ProphetDetector()
        self.changepoint = ChangepointDetector()

    async def detect(
        self,
        metric_name: str,
        values: list[float],
        timestamps: list[Any],
    ) -> AnomalyResult:
        """
        Run ensemble anomaly detection on a metric time series.

        Args:
            metric_name: Human-readable metric label (for logging/reporting).
            values:      Ordered list of float metric values.
            timestamps:  Corresponding timestamps (datetime, Unix float, ISO str).

        Returns:
            AnomalyResult with confirmed anomalies and per-detector statistics.
        """
        if len(values) != len(timestamps):
            raise ValueError(
                f"values ({len(values)}) and timestamps ({len(timestamps)}) "
                "must have the same length."
            )

        result = AnomalyResult(
            metric_name=metric_name,
            total_input_points=len(values),
        )

        if not values:
            return result

        log.info(
            "anomaly_engine.start",
            metric=metric_name,
            n=len(values),
        )

        # Run all three detectors concurrently
        zscore_task = self.zscore.detect(values, timestamps)
        prophet_task = self.prophet.detect(values, timestamps)
        changepoint_task = self.changepoint.detect(values, timestamps)

        zscore_results, prophet_results, changepoint_results = await asyncio.gather(
            zscore_task,
            prophet_task,
            changepoint_task,
            return_exceptions=True,
        )

        # Handle exceptions from individual detectors gracefully
        all_detections: dict[str, list[Anomaly]] = {}

        for name, res in [
            ("zscore", zscore_results),
            ("prophet", prophet_results),
            ("changepoint", changepoint_results),
        ]:
            if isinstance(res, Exception):
                log.warning(
                    "anomaly_engine.detector_failed",
                    detector=name,
                    error=str(res),
                )
                all_detections[name] = []
            else:
                all_detections[name] = res  # type: ignore[assignment]

        result.all_detections = all_detections
        result.detector_agreement = {
            name: len(anoms) for name, anoms in all_detections.items()
        }

        # Majority vote ensemble
        result.anomalies = _vote_ensemble(all_detections)

        log.info(
            "anomaly_engine.complete",
            metric=metric_name,
            n=len(values),
            confirmed_anomalies=len(result.anomalies),
            zscore_detections=result.detector_agreement.get("zscore", 0),
            prophet_detections=result.detector_agreement.get("prophet", 0),
            changepoint_detections=result.detector_agreement.get("changepoint", 0),
        )

        return result
