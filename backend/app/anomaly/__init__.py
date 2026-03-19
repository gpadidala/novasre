"""
Anomaly Detection Engine — multi-method anomaly detection for metric time-series.

Detectors:
  - ZScoreDetector:      Rolling window Z-score (fast, stateless)
  - ProphetDetector:     Meta Prophet seasonal decomposition (accurate, slower)
  - ChangepointDetector: PELT change-point detection (deployment regression)

The AnomalyDetectionEngine runs all three concurrently and uses a vote-based
ensemble: an anomaly is confirmed when >= 2 of 3 detectors agree.
"""

from app.anomaly.changepoint import ChangepointDetector
from app.anomaly.engine import AnomalyDetectionEngine, AnomalyResult
from app.anomaly.prophet_detector import ProphetDetector
from app.anomaly.zscore import Anomaly, ZScoreDetector

__all__ = [
    "Anomaly",
    "AnomalyResult",
    "AnomalyDetectionEngine",
    "ZScoreDetector",
    "ProphetDetector",
    "ChangepointDetector",
]
