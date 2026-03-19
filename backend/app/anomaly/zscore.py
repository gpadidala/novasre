"""
Z-Score Detector — rolling window Z-score anomaly detection.

This is the fastest detector in the ensemble.  It requires no model fitting
and produces results in O(n) time, making it suitable for high-cardinality
metric streams.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog

log = structlog.get_logger(__name__)


@dataclass
class Anomaly:
    """
    A single anomalous data point detected by any detector.

    Attributes:
        timestamp:  The time at which the anomaly occurred.
        value:      The observed metric value.
        zscore:     Z-score of the value relative to the local window
                    (NaN for detectors that don't compute Z-scores).
        severity:   "low" / "medium" / "high" based on |zscore| magnitude.
        detector:   Name of the detector that flagged this point.
        expected:   Expected value (from model), if available.
        upper:      Upper confidence bound, if available.
        lower:      Lower confidence bound, if available.
    """

    timestamp: datetime
    value: float
    zscore: float = float("nan")
    severity: str = "medium"
    detector: str = "unknown"
    expected: float | None = None
    upper: float | None = None
    lower: float | None = None


def _severity_from_zscore(z: float) -> str:
    abs_z = abs(z)
    if abs_z >= 5.0:
        return "high"
    if abs_z >= 4.0:
        return "medium"
    return "low"


class ZScoreDetector:
    """
    Rolling window Z-score detector.

    For each data point at index ``i``, a rolling window of the previous
    ``window`` points is used to compute the local mean and standard
    deviation.  The Z-score is then:

        z = (x_i - mean) / std

    Points where ``|z| > threshold`` are flagged as anomalies.

    The detector requires at least ``window + 1`` data points to produce
    any output; shorter series are returned as anomaly-free.
    """

    def __init__(self, window: int = 60, threshold: float = 3.0) -> None:
        self.window = window
        self.threshold = threshold

    async def detect(
        self,
        values: list[float],
        timestamps: list[Any],
        window: int | None = None,
        threshold: float | None = None,
    ) -> list[Anomaly]:
        """
        Run rolling Z-score detection.

        Args:
            values:     Metric values (floats), ordered chronologically.
            timestamps: Corresponding timestamps (datetime or ISO str).
                        Must be the same length as ``values``.
            window:     Override instance default window size.
            threshold:  Override instance default Z-score threshold.

        Returns:
            List of Anomaly dataclasses for flagged points.
        """
        win = window if window is not None else self.window
        thr = threshold if threshold is not None else self.threshold

        if len(values) != len(timestamps):
            raise ValueError(
                f"values ({len(values)}) and timestamps ({len(timestamps)}) "
                "must have the same length."
            )

        if len(values) <= win:
            log.debug(
                "zscore_detector.insufficient_data",
                n=len(values),
                window=win,
            )
            return []

        anomalies: list[Anomaly] = []

        for i in range(win, len(values)):
            window_vals = values[i - win : i]
            mean = sum(window_vals) / len(window_vals)
            variance = sum((v - mean) ** 2 for v in window_vals) / len(window_vals)
            std = variance ** 0.5

            if std == 0.0:
                continue  # Constant window — no deviation possible

            z = (values[i] - mean) / std
            if abs(z) > thr:
                ts = _parse_timestamp(timestamps[i])
                anomalies.append(
                    Anomaly(
                        timestamp=ts,
                        value=values[i],
                        zscore=round(z, 4),
                        severity=_severity_from_zscore(z),
                        detector="zscore",
                        expected=round(mean, 6),
                    )
                )

        log.info(
            "zscore_detector.complete",
            n=len(values),
            anomalies_found=len(anomalies),
            threshold=thr,
        )
        return anomalies


# ---------------------------------------------------------------------------
# Timestamp parsing helper (shared across anomaly detectors)
# ---------------------------------------------------------------------------

def _parse_timestamp(ts: Any) -> datetime:
    """Coerce various timestamp representations to a datetime object."""
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        return datetime.utcfromtimestamp(ts)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    # Fallback — return epoch to avoid crashing the pipeline
    return datetime.utcfromtimestamp(0)
