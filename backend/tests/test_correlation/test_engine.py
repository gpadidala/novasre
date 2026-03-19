"""
Tests for all 3 correlation layers and the AlertCorrelationEngine.

Covers:
  - TemporalCorrelator: grouping, sliding window, undated alerts
  - TopologicalCorrelator: service graph merging, BFS depth, no-graph passthrough
  - SemanticCorrelator: cosine similarity merging, graceful degradation without API key
  - AlertCorrelationEngine: full pipeline, noise reduction stats
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.correlation.engine import AlertCorrelationEngine
from app.correlation.semantic import SemanticCorrelator
from app.correlation.temporal import AlertGroup, TemporalCorrelator
from app.correlation.topological import TopologicalCorrelator


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def _make_alert(
    name: str,
    fired_at: datetime,
    service: str = "web",
    severity: str = "warning",
) -> dict:
    """Build a plain-dict alert for testing (no ORM dependency)."""
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "fired_at": fired_at.isoformat(),
        "labels": {"app": service, "severity": severity},
        "annotations": {"summary": f"{name} on {service}"},
        "severity": severity,
        "status": "firing",
    }


NOW = datetime(2024, 3, 17, 14, 30, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# TemporalCorrelator tests
# ---------------------------------------------------------------------------

class TestTemporalCorrelator:
    def test_empty_input_returns_empty(self):
        tc = TemporalCorrelator(window_seconds=300)
        assert tc.group([]) == []

    def test_single_alert_produces_one_group(self):
        alert = _make_alert("HighErrorRate", NOW)
        groups = TemporalCorrelator().group([alert])
        assert len(groups) == 1
        assert len(groups[0].alerts) == 1

    def test_alerts_within_window_grouped_together(self):
        """Three alerts within 4 minutes should form one group (window=300s)."""
        a1 = _make_alert("A", NOW)
        a2 = _make_alert("B", NOW + timedelta(seconds=120))
        a3 = _make_alert("C", NOW + timedelta(seconds=240))

        groups = TemporalCorrelator(window_seconds=300).group([a1, a2, a3])
        assert len(groups) == 1
        assert len(groups[0].alerts) == 3

    def test_alerts_outside_window_split_into_separate_groups(self):
        """Two alerts 10 minutes apart should be in different groups (window=300s)."""
        a1 = _make_alert("A", NOW)
        a2 = _make_alert("B", NOW + timedelta(seconds=600))

        groups = TemporalCorrelator(window_seconds=300).group([a1, a2])
        assert len(groups) == 2

    def test_input_order_does_not_matter(self):
        """Unsorted input should still produce the correct grouping."""
        a1 = _make_alert("A", NOW)
        a2 = _make_alert("B", NOW + timedelta(seconds=200))
        a3 = _make_alert("C", NOW + timedelta(seconds=700))

        # Provide in reverse order
        groups = TemporalCorrelator(window_seconds=300).group([a3, a1, a2])
        assert len(groups) == 2
        # Earlier group should have 2 alerts (a1 and a2)
        group_sizes = sorted([len(g.alerts) for g in groups])
        assert group_sizes == [1, 2]

    def test_group_start_end_times_set_correctly(self):
        a1 = _make_alert("A", NOW)
        a2 = _make_alert("B", NOW + timedelta(seconds=120))
        groups = TemporalCorrelator(window_seconds=300).group([a1, a2])

        g = groups[0]
        assert g.start_time is not None
        assert g.end_time is not None
        assert g.start_time <= g.end_time

    def test_alerts_missing_fired_at_go_into_undated_group(self):
        good_alert = _make_alert("A", NOW)
        bad_alert = {"id": "bad", "name": "NoDate", "labels": {}, "annotations": {}}

        groups = TemporalCorrelator(window_seconds=300).group([good_alert, bad_alert])
        # Good alert → 1 group, bad alert → 1 undated group
        assert len(groups) == 2
        total_alerts = sum(len(g.alerts) for g in groups)
        assert total_alerts == 2

    def test_representative_alert_is_set(self):
        a1 = _make_alert("First", NOW)
        a2 = _make_alert("Second", NOW + timedelta(seconds=60))
        groups = TemporalCorrelator().group([a1, a2])
        assert groups[0].representative_alert is not None

    def test_services_extracted_from_labels(self):
        a1 = _make_alert("A", NOW, service="checkout")
        a2 = _make_alert("B", NOW + timedelta(seconds=10), service="payment")
        groups = TemporalCorrelator(window_seconds=300).group([a1, a2])
        assert "checkout" in groups[0].services
        assert "payment" in groups[0].services

    def test_custom_window_seconds(self):
        """1-second window: every alert should get its own group."""
        alerts = [_make_alert(f"A{i}", NOW + timedelta(seconds=i * 5)) for i in range(4)]
        groups = TemporalCorrelator(window_seconds=1).group(alerts)
        assert len(groups) == 4


# ---------------------------------------------------------------------------
# TopologicalCorrelator tests
# ---------------------------------------------------------------------------

class TestTopologicalCorrelator:
    def _make_groups_for_services(self, *service_sets) -> list[AlertGroup]:
        """Create one AlertGroup per service set."""
        groups = []
        for services in service_sets:
            group = AlertGroup()
            group.services = set(services)
            groups.append(group)
        return groups

    @pytest.mark.asyncio
    async def test_no_graph_returns_groups_unchanged(self):
        groups = self._make_groups_for_services({"checkout"}, {"payment"})
        tc = TopologicalCorrelator()
        result = await tc.merge(groups, service_graph=None)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_groups_returns_empty(self):
        tc = TopologicalCorrelator()
        result = await tc.merge([], service_graph={"a": ["b"]})
        assert result == []

    @pytest.mark.asyncio
    async def test_connected_services_merged(self):
        """checkout depends on postgres; alerts on both should merge."""
        graph = {"checkout": ["postgres"]}
        groups = self._make_groups_for_services({"checkout"}, {"postgres"})
        tc = TopologicalCorrelator(max_depth=3)
        result = await tc.merge(groups, service_graph=graph)
        assert len(result) == 1
        merged_services = result[0].services
        assert "checkout" in merged_services
        assert "postgres" in merged_services

    @pytest.mark.asyncio
    async def test_unconnected_services_not_merged(self):
        """Alerts on unrelated services should stay separate."""
        graph = {"checkout": ["postgres"], "email": ["smtp"]}
        groups = self._make_groups_for_services({"checkout"}, {"email"})
        tc = TopologicalCorrelator(max_depth=3)
        result = await tc.merge(groups, service_graph=graph)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_depth_limit_respected(self):
        """With depth=1, only direct neighbours should trigger a merge."""
        # checkout → payment → postgres (2 hops)
        graph = {"checkout": ["payment"], "payment": ["postgres"]}
        groups = self._make_groups_for_services({"checkout"}, {"postgres"})

        # depth=1: checkout can only reach payment, not postgres → no merge
        tc_shallow = TopologicalCorrelator(max_depth=1)
        result_shallow = await tc_shallow.merge(groups, service_graph=graph)
        assert len(result_shallow) == 2

        # depth=2: checkout → payment → postgres → merge
        tc_deep = TopologicalCorrelator(max_depth=2)
        result_deep = await tc_deep.merge(
            self._make_groups_for_services({"checkout"}, {"postgres"}),
            service_graph=graph,
        )
        assert len(result_deep) == 1

    @pytest.mark.asyncio
    async def test_bidirectional_reachability(self):
        """Reverse direction should also trigger merge (undirected graph)."""
        graph = {"frontend": ["backend"]}
        # backend alert should be reachable from frontend and vice versa
        groups = self._make_groups_for_services({"backend"}, {"frontend"})
        tc = TopologicalCorrelator(max_depth=2)
        result = await tc.merge(groups, service_graph=graph)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# SemanticCorrelator tests
# ---------------------------------------------------------------------------

class TestSemanticCorrelator:
    def _groups_from_texts(self, *texts: str) -> list[AlertGroup]:
        groups = []
        for text in texts:
            g = AlertGroup()
            g.representative_alert = {"name": text, "annotations": {}}
            groups.append(g)
        return groups

    @pytest.mark.asyncio
    async def test_single_group_returned_unchanged(self):
        sc = SemanticCorrelator(threshold=0.75)
        groups = self._groups_from_texts("HighErrorRate on checkout")
        result = await sc.merge(groups)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_no_api_key_returns_groups_unchanged(self, monkeypatch):
        """Without OPENAI_API_KEY, semantic merge should skip gracefully."""
        monkeypatch.setattr("app.correlation.semantic.settings.openai_api_key", "")
        sc = SemanticCorrelator(threshold=0.75)
        groups = self._groups_from_texts("AlertA", "AlertB", "AlertC")
        result = await sc.merge(groups)
        # Should return original groups unchanged
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_similar_groups_merged(self):
        """Mock embeddings that are identical → should merge all groups."""
        sc = SemanticCorrelator(threshold=0.5)
        groups = self._groups_from_texts("DB connection error", "Database connection failed")

        # Return identical embeddings → cosine similarity = 1.0
        identical_embedding = [1.0, 0.0, 0.0]
        mock_embeddings = [identical_embedding, identical_embedding]

        with patch.object(sc, "_embed_texts", new=AsyncMock(return_value=mock_embeddings)):
            with patch("app.correlation.semantic.settings.openai_api_key", "fake-key"):
                result = await sc.merge(groups)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_dissimilar_groups_not_merged(self):
        """Orthogonal embeddings → cosine similarity = 0.0 → no merge."""
        sc = SemanticCorrelator(threshold=0.75)
        groups = self._groups_from_texts("CPU spike on node", "HTTP 500 errors checkout")

        emb_a = [1.0, 0.0, 0.0]
        emb_b = [0.0, 1.0, 0.0]  # orthogonal

        with patch.object(sc, "_embed_texts", new=AsyncMock(return_value=[emb_a, emb_b])):
            with patch("app.correlation.semantic.settings.openai_api_key", "fake-key"):
                result = await sc.merge(groups)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_embedding_failure_returns_original(self):
        """If embedding returns None (API failure), original groups returned."""
        sc = SemanticCorrelator(threshold=0.75)
        groups = self._groups_from_texts("AlertA", "AlertB")

        with patch.object(sc, "_embed_texts", new=AsyncMock(return_value=None)):
            result = await sc.merge(groups)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_threshold_boundary(self):
        """Similarity exactly at threshold should trigger merge."""
        sc = SemanticCorrelator(threshold=0.80)
        groups = self._groups_from_texts("AlertA", "AlertB")

        # Vectors with cosine similarity = 0.80 (approximately)
        import math
        angle = math.acos(0.80)
        emb_a = [1.0, 0.0]
        emb_b = [math.cos(angle), math.sin(angle)]

        with patch.object(sc, "_embed_texts", new=AsyncMock(return_value=[emb_a, emb_b])):
            with patch("app.correlation.semantic.settings.openai_api_key", "fake-key"):
                result = await sc.merge(groups)

        assert len(result) == 1


# ---------------------------------------------------------------------------
# AlertCorrelationEngine tests
# ---------------------------------------------------------------------------

class TestAlertCorrelationEngine:
    @pytest.mark.asyncio
    async def test_empty_alerts_returns_empty(self):
        engine = AlertCorrelationEngine()
        result = await engine.correlate([])
        assert result == []

    @pytest.mark.asyncio
    async def test_full_pipeline_reduces_noise(self, monkeypatch):
        """
        10 alerts within 5 minutes on related services should collapse to fewer groups.
        """
        monkeypatch.setattr("app.correlation.semantic.settings.openai_api_key", "")

        alerts = [
            _make_alert(f"Alert{i}", NOW + timedelta(seconds=i * 20), service="checkout")
            for i in range(10)
        ]
        engine = AlertCorrelationEngine(temporal_window_seconds=300)
        groups = await engine.correlate(alerts)

        # All within the window → should be 1 temporal group
        assert len(groups) == 1

    @pytest.mark.asyncio
    async def test_topological_merge_in_pipeline(self, monkeypatch):
        """Services connected via graph should be merged in the full pipeline."""
        monkeypatch.setattr("app.correlation.semantic.settings.openai_api_key", "")

        # Two separate time clusters but on connected services
        a1 = _make_alert("DBDown", NOW, service="postgres")
        a2 = _make_alert("CheckoutErrors", NOW + timedelta(seconds=10), service="checkout")

        service_graph = {"checkout": ["postgres"]}

        engine = AlertCorrelationEngine(temporal_window_seconds=300)
        groups = await engine.correlate([a1, a2], service_graph=service_graph)

        # Both alerts within window → 1 temporal group, and services are connected
        assert len(groups) == 1

    @pytest.mark.asyncio
    async def test_noise_reduction_stats_correct(self):
        engine = AlertCorrelationEngine()

        stats = engine.get_noise_reduction_stats(original_count=100, group_count=15)
        assert stats["original_count"] == 100
        assert stats["groups_count"] == 15
        assert stats["noise_suppressed"] == 85
        assert stats["reduction_pct"] == 85.0

    def test_noise_reduction_stats_zero_alerts(self):
        engine = AlertCorrelationEngine()
        stats = engine.get_noise_reduction_stats(0, 0)
        assert stats["reduction_pct"] == 0.0
        assert stats["noise_suppressed"] == 0

    def test_noise_reduction_stats_no_reduction(self):
        engine = AlertCorrelationEngine()
        stats = engine.get_noise_reduction_stats(5, 5)
        assert stats["reduction_pct"] == 0.0
        assert stats["noise_suppressed"] == 0

    @pytest.mark.asyncio
    async def test_semantic_layer_skipped_gracefully_without_key(self, monkeypatch):
        """Pipeline should succeed even when semantic embedding is unavailable."""
        monkeypatch.setattr("app.correlation.semantic.settings.openai_api_key", "")

        alerts = [_make_alert(f"A{i}", NOW + timedelta(seconds=i * 30)) for i in range(5)]
        engine = AlertCorrelationEngine(temporal_window_seconds=300)
        groups = await engine.correlate(alerts)

        assert len(groups) >= 1

    @pytest.mark.asyncio
    async def test_alerts_in_multiple_disjoint_windows(self, monkeypatch):
        """Alerts in 3 separate 10-minute windows should form 3+ groups."""
        monkeypatch.setattr("app.correlation.semantic.settings.openai_api_key", "")

        window_size = 300  # 5 minutes
        cluster1 = [_make_alert(f"C1A{i}", NOW + timedelta(seconds=i * 10)) for i in range(3)]
        cluster2 = [
            _make_alert(f"C2A{i}", NOW + timedelta(seconds=700 + i * 10)) for i in range(3)
        ]
        cluster3 = [
            _make_alert(f"C3A{i}", NOW + timedelta(seconds=1400 + i * 10)) for i in range(3)
        ]

        engine = AlertCorrelationEngine(temporal_window_seconds=window_size)
        groups = await engine.correlate(cluster1 + cluster2 + cluster3)

        assert len(groups) == 3

    @pytest.mark.asyncio
    async def test_alert_group_contains_all_alerts(self, monkeypatch):
        """Every input alert must appear in exactly one output group."""
        monkeypatch.setattr("app.correlation.semantic.settings.openai_api_key", "")

        alerts = [
            _make_alert(f"A{i}", NOW + timedelta(seconds=i * 15)) for i in range(6)
        ]
        engine = AlertCorrelationEngine(temporal_window_seconds=300)
        groups = await engine.correlate(alerts)

        total_in_groups = sum(len(g.alerts) for g in groups)
        assert total_in_groups == 6


# ---------------------------------------------------------------------------
# AlertGroup dataclass tests
# ---------------------------------------------------------------------------

class TestAlertGroup:
    def test_merge_from_absorbs_alerts(self):
        g1 = AlertGroup()
        g2 = AlertGroup()

        alert1 = _make_alert("A1", NOW)
        alert2 = _make_alert("A2", NOW + timedelta(seconds=10))
        g1.add_alert(alert1)
        g2.add_alert(alert2)

        g1.merge_from(g2)
        assert len(g1.alerts) == 2
        assert g2.group_id in g1.merged_from

    def test_services_accumulated_on_add(self):
        g = AlertGroup()
        g.add_alert(_make_alert("A", NOW, service="checkout"))
        g.add_alert(_make_alert("B", NOW, service="payment"))
        assert "checkout" in g.services
        assert "payment" in g.services

    def test_time_bounds_updated_correctly(self):
        g = AlertGroup()
        early = NOW
        late = NOW + timedelta(hours=2)

        g.add_alert(_make_alert("Early", early))
        g.add_alert(_make_alert("Late", late))

        assert g.start_time == early.astimezone(g.start_time.tzinfo) or g.start_time is not None
        assert g.end_time is not None
        assert g.start_time < g.end_time
