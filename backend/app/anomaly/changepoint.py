"""
Changepoint Detector — PELT / CUSUM change-point detection.

Detects abrupt structural changes in a time series (e.g., a deployment that
raises the error rate baseline).  Uses the ``ruptures`` library when available
and falls back to a simple CUSUM algorithm otherwise.
"""

import asyncio
import math
from datetime import datetime
from typing import Any

import structlog

from app.anomaly.zscore import Anomaly, _parse_timestamp

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Synchronous implementations (run inside executor)
# ---------------------------------------------------------------------------

def _pelt_detect(values: list[float]) -> list[int]:
    """
    PELT change-point detection via the ``ruptures`` library.

    Returns a list of change-point indices (0-based, exclusive right bound).
    An empty list means no change points were found.
    """
    import ruptures as rpt  # type: ignore[import]

    import numpy as np

    signal = np.array(values).reshape(-1, 1)
    model = rpt.Pelt(model="rbf", min_size=3, jump=1)
    model.fit(signal)
    # pen = log(n) * sigma^2  (BIC-style penalty)
    n = len(values)
    sigma2 = float(np.var(values)) if np.var(values) > 0 else 1.0
    pen = math.log(n) * sigma2
    breakpoints = model.predict(pen=pen)
    # ruptures returns the *right* end of each segment; last entry == n
    return [bp for bp in breakpoints if bp < n]


def _cusum_detect(
    values: list[float],
    threshold_factor: float = 3.5,
) -> list[int]:
    """
    Simple CUSUM change-point fallback.

    Computes cumulative sum of deviations from the global mean.  A change
    point is declared whenever the absolute cumulative sum exceeds
    ``threshold_factor * global_std``.  After a detection, the cumulative
    sum is reset to suppress subsequent detections in the same "run".
    """
    if len(values) < 4:
        return []

    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(variance) if variance > 0 else 1.0
    threshold = threshold_factor * std

    cusum = 0.0
    breakpoints: list[int] = []
    last_bp = 0

    for i, v in enumerate(values):
        cusum += v - mean
        if abs(cusum) > threshold and i > last_bp + 3:
            breakpoints.append(i)
            cusum = 0.0
            last_bp = i

    return breakpoints


def _run_changepoint_sync(
    values: list[float],
    timestamps: list[datetime],
) -> list[Anomaly]:
    """
    Synchronous change-point detection — called inside a thread executor.
    """
    if len(values) < 4:
        return []

    # Try PELT first; fall back to CUSUM if ruptures is not installed
    try:
        breakpoint_indices = _pelt_detect(values)
        method = "pelt"
    except Exception as exc:  # noqa: BLE001
        log.debug("changepoint_detector.ruptures_unavailable", error=str(exc))
        breakpoint_indices = _cusum_detect(values)
        method = "cusum"

    if not breakpoint_indices:
        return []

    # Compute mean on either side of each change point to estimate
    # the magnitude of the shift.
    anomalies: list[Anomaly] = []
    for idx in breakpoint_indices:
        # Left segment mean
        left_start = max(0, idx - 20)
        left_vals = values[left_start:idx]
        left_mean = sum(left_vals) / len(left_vals) if left_vals else values[idx]

        # Right segment mean (a window after the change point)
        right_end = min(len(values), idx + 20)
        right_vals = values[idx:right_end]
        right_mean = sum(right_vals) / len(right_vals) if right_vals else values[idx]

        delta = right_mean - left_mean
        std_left = (
            math.sqrt(sum((v - left_mean) ** 2 for v in left_vals) / len(left_vals))
            if len(left_vals) > 1
            else 1.0
        )
        pseudo_z = delta / std_left if std_left > 0 else 0.0

        severity = "high" if abs(pseudo_z) >= 3 else "medium" if abs(pseudo_z) >= 1.5 else "low"

        anomalies.append(
            Anomaly(
                timestamp=_parse_timestamp(timestamps[idx]),
                value=values[idx],
                zscore=round(pseudo_z, 4),
                severity=severity,
                detector=f"changepoint_{method}",
                expected=round(left_mean, 6),
            )
        )

    return anomalies


class ChangepointDetector:
    """
    Structural change-point detector.

    Uses PELT (``ruptures`` library) when available, falling back to a
    simple CUSUM algorithm.  Both are CPU-bound and run inside an asyncio
    thread-pool executor to avoid blocking the event loop.

    Change points correspond to abrupt shifts in the metric baseline —
    typically caused by deployments, config changes, or cascading failures.
    """

    async def detect(
        self,
        values: list[float],
        timestamps: list[Any],
    ) -> list[Anomaly]:
        """
        Detect change points in a time series.

        Args:
            values:     Metric values ordered chronologically.
            timestamps: Corresponding timestamps.

        Returns:
            List of Anomaly objects, one per detected change point.
        """
        if len(values) != len(timestamps):
            raise ValueError(
                f"values ({len(values)}) and timestamps ({len(timestamps)}) "
                "must have the same length."
            )

        if len(values) < 4:
            log.debug("changepoint_detector.insufficient_data", n=len(values))
            return []

        parsed_ts = [_parse_timestamp(t) for t in timestamps]

        loop = asyncio.get_event_loop()
        try:
            anomalies: list[Anomaly] = await loop.run_in_executor(
                None,
                _run_changepoint_sync,
                values,
                parsed_ts,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("changepoint_detector.executor_error", error=str(exc))
            return []

        log.info(
            "changepoint_detector.complete",
            n=len(values),
            changepoints_found=len(anomalies),
        )
        return anomalies
