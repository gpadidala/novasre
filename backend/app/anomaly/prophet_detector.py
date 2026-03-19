"""
Prophet Detector — Meta's Prophet seasonal decomposition for anomaly detection.

Prophet is a CPU-bound fitting operation and MUST be run in a thread pool
executor to avoid blocking the asyncio event loop.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

import structlog

from app.anomaly.zscore import Anomaly, _parse_timestamp

log = structlog.get_logger(__name__)

# Suppress verbose cmdstanpy / Prophet logs
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)


def _run_prophet_sync(
    values: list[float],
    timestamps: list[datetime],
) -> list[Anomaly]:
    """
    Synchronous Prophet fit + predict — called inside a thread executor.

    Returns a list of Anomaly objects for points outside the forecast band.
    """
    try:
        import pandas as pd
        from prophet import Prophet
    except ImportError as exc:
        log.warning(
            "prophet_detector.import_error",
            error=str(exc),
            message="Prophet not installed; detector returning no anomalies.",
        )
        return []

    if len(values) < 10:
        # Prophet needs at least a handful of data points to be meaningful
        return []

    df = pd.DataFrame({"ds": timestamps, "y": values})

    model = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=True,
        daily_seasonality=True,
        changepoint_prior_scale=0.05,
        interval_width=0.95,
        # Silence stdout progress bar
        stan_backend="CMDSTANPY",
    )

    try:
        model.fit(df, iter=300)
    except Exception as exc:  # noqa: BLE001
        log.error("prophet_detector.fit_error", error=str(exc))
        return []

    forecast = model.predict(df)

    anomalies: list[Anomaly] = []
    for i, row in forecast.iterrows():
        actual = values[i]
        yhat = row["yhat"]
        upper = row["yhat_upper"]
        lower = row["yhat_lower"]

        if actual > upper or actual < lower:
            deviation = actual - yhat
            # Approximate Z-score equivalent: deviation / half-interval
            half_interval = (upper - lower) / 2 if (upper - lower) > 0 else 1.0
            pseudo_z = deviation / half_interval

            severity: str
            abs_z = abs(pseudo_z)
            if abs_z >= 3.0:
                severity = "high"
            elif abs_z >= 1.5:
                severity = "medium"
            else:
                severity = "low"

            anomalies.append(
                Anomaly(
                    timestamp=_parse_timestamp(timestamps[i]),
                    value=actual,
                    zscore=round(pseudo_z, 4),
                    severity=severity,
                    detector="prophet",
                    expected=round(float(yhat), 6),
                    upper=round(float(upper), 6),
                    lower=round(float(lower), 6),
                )
            )

    return anomalies


class ProphetDetector:
    """
    Seasonal anomaly detection using Meta's Prophet library.

    Prophet builds a Bayesian structural time-series model with trend,
    weekly seasonality, and daily seasonality components.  Data points
    outside the ``yhat_upper`` / ``yhat_lower`` 95% confidence bands are
    flagged as anomalies.

    The heavy fit/predict work is dispatched to a thread pool to keep the
    asyncio event loop free.
    """

    async def detect(
        self,
        values: list[float],
        timestamps: list[Any],
    ) -> list[Anomaly]:
        """
        Detect seasonal anomalies using Prophet.

        Args:
            values:     Metric values ordered chronologically.
            timestamps: Corresponding timestamps (datetime, Unix float, or
                        ISO-8601 string).

        Returns:
            List of Anomaly objects for points outside the forecast band.
        """
        if len(values) != len(timestamps):
            raise ValueError(
                f"values ({len(values)}) and timestamps ({len(timestamps)}) "
                "must have the same length."
            )

        if len(values) < 10:
            log.debug("prophet_detector.insufficient_data", n=len(values))
            return []

        # Parse all timestamps upfront before handing to thread
        parsed_ts = [_parse_timestamp(t) for t in timestamps]

        loop = asyncio.get_event_loop()
        try:
            anomalies: list[Anomaly] = await loop.run_in_executor(
                None,
                _run_prophet_sync,
                values,
                parsed_ts,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("prophet_detector.executor_error", error=str(exc))
            return []

        log.info(
            "prophet_detector.complete",
            n=len(values),
            anomalies_found=len(anomalies),
        )
        return anomalies
