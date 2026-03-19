#!/usr/bin/env python3
"""
NovaSRE — Development Seed Data Script
=======================================
Creates realistic sample data in the database for local development and testing.

Creates:
  - 5 services (checkout, payment, inventory, api-gateway, user-service)
  - 12 alerts (mix of firing and resolved, various severities)
  - 3 incidents (P1, P2, P3 with different statuses)
  - 2 investigations (one completed with RCA, one in progress)

Usage:
    docker compose exec backend python scripts/seed_data.py
    # or directly:
    python scripts/seed_data.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure the project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog
from sqlalchemy import text

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
)
log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ago(**kwargs: int) -> datetime:
    return utcnow() - timedelta(**kwargs)


def uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Seed definitions
# ---------------------------------------------------------------------------
SERVICES = [
    {
        "id":           uid(),
        "name":         "checkout",
        "namespace":    "prod",
        "team":         "platform",
        "dependencies": json.dumps(["payment", "inventory", "user-service"]),
        "slo_target":   99.9,
        "labels":       json.dumps({"tier": "critical", "language": "go"}),
    },
    {
        "id":           uid(),
        "name":         "payment",
        "namespace":    "prod",
        "team":         "payments",
        "dependencies": json.dumps(["api-gateway"]),
        "slo_target":   99.95,
        "labels":       json.dumps({"tier": "critical", "language": "java", "pci": "true"}),
    },
    {
        "id":           uid(),
        "name":         "inventory",
        "namespace":    "prod",
        "team":         "catalog",
        "dependencies": json.dumps([]),
        "slo_target":   99.5,
        "labels":       json.dumps({"tier": "high", "language": "python"}),
    },
    {
        "id":           uid(),
        "name":         "api-gateway",
        "namespace":    "prod",
        "team":         "platform",
        "dependencies": json.dumps([]),
        "slo_target":   99.99,
        "labels":       json.dumps({"tier": "critical", "language": "go", "edge": "true"}),
    },
    {
        "id":           uid(),
        "name":         "user-service",
        "namespace":    "prod",
        "team":         "identity",
        "dependencies": json.dumps([]),
        "slo_target":   99.9,
        "labels":       json.dumps({"tier": "high", "language": "nodejs"}),
    },
]

# We'll resolve incident IDs after creating incidents
INCIDENT_IDS = {
    "p1_checkout": uid(),
    "p2_payment":  uid(),
    "p3_inventory": uid(),
}

ALERTS = [
    # P1 incident alerts — checkout high error rate cascade
    {
        "id":                   uid(),
        "name":                 "CheckoutHighErrorRate",
        "fingerprint":          "abc001checkout",
        "labels":               json.dumps({"app": "checkout", "severity": "critical", "alertname": "CheckoutHighErrorRate"}),
        "annotations":          json.dumps({"summary": "Checkout service error rate > 10%", "description": "Error rate is 12.3%, 40x above baseline. P99 latency is 8.2s."}),
        "severity":             "critical",
        "status":               "firing",
        "source":               "alertmanager",
        "fired_at":             ago(hours=2),
        "resolved_at":          None,
        "incident_id":          INCIDENT_IDS["p1_checkout"],
        "correlation_group_id": uid(),
    },
    {
        "id":                   uid(),
        "name":                 "CheckoutHighLatency",
        "fingerprint":          "abc002checkout",
        "labels":               json.dumps({"app": "checkout", "severity": "critical", "alertname": "CheckoutHighLatency"}),
        "annotations":          json.dumps({"summary": "Checkout P99 latency > 5s", "description": "P99 latency is 8.2s, SLO threshold is 500ms."}),
        "severity":             "critical",
        "status":               "firing",
        "source":               "alertmanager",
        "fired_at":             ago(hours=2, minutes=1),
        "resolved_at":          None,
        "incident_id":          INCIDENT_IDS["p1_checkout"],
        "correlation_group_id": uid(),
    },
    {
        "id":                   uid(),
        "name":                 "DBConnectionPoolExhausted",
        "fingerprint":          "abc003db",
        "labels":               json.dumps({"app": "checkout", "component": "postgres", "severity": "critical", "alertname": "DBConnectionPoolExhausted"}),
        "annotations":          json.dumps({"summary": "DB connection pool at 100% capacity", "description": "checkout-db connection pool exhausted. New connections are being refused."}),
        "severity":             "critical",
        "status":               "firing",
        "source":               "alertmanager",
        "fired_at":             ago(hours=2, minutes=3),
        "resolved_at":          None,
        "incident_id":          INCIDENT_IDS["p1_checkout"],
        "correlation_group_id": uid(),
    },
    {
        "id":                   uid(),
        "name":                 "CheckoutSLOBurnRateHigh",
        "fingerprint":          "abc004slo",
        "labels":               json.dumps({"app": "checkout", "severity": "warning", "alertname": "CheckoutSLOBurnRateHigh"}),
        "annotations":          json.dumps({"summary": "Checkout SLO burn rate 15x", "description": "At current burn rate, monthly error budget will be exhausted in 2 hours."}),
        "severity":             "warning",
        "status":               "firing",
        "source":               "grafana",
        "fired_at":             ago(hours=1, minutes=55),
        "resolved_at":          None,
        "incident_id":          INCIDENT_IDS["p1_checkout"],
        "correlation_group_id": uid(),
    },
    # P2 incident alerts — payment latency
    {
        "id":                   uid(),
        "name":                 "PaymentGatewayHighLatency",
        "fingerprint":          "def001payment",
        "labels":               json.dumps({"app": "payment", "severity": "high", "alertname": "PaymentGatewayHighLatency"}),
        "annotations":          json.dumps({"summary": "Payment gateway P99 latency > 2s", "description": "Stripe API calls showing elevated latency. P99 is 3.1s vs baseline of 200ms."}),
        "severity":             "high",
        "status":               "firing",
        "source":               "alertmanager",
        "fired_at":             ago(hours=4),
        "resolved_at":          None,
        "incident_id":          INCIDENT_IDS["p2_payment"],
        "correlation_group_id": uid(),
    },
    {
        "id":                   uid(),
        "name":                 "PaymentTransactionTimeouts",
        "fingerprint":          "def002payment",
        "labels":               json.dumps({"app": "payment", "severity": "high", "alertname": "PaymentTransactionTimeouts"}),
        "annotations":          json.dumps({"summary": "Payment transaction timeout rate elevated", "description": "2.3% of payment transactions are timing out after 30s."}),
        "severity":             "high",
        "status":               "firing",
        "source":               "alertmanager",
        "fired_at":             ago(hours=3, minutes=55),
        "resolved_at":          None,
        "incident_id":          INCIDENT_IDS["p2_payment"],
        "correlation_group_id": uid(),
    },
    # P3 incident alerts — inventory pod restarts
    {
        "id":                   uid(),
        "name":                 "InventoryPodCrashLooping",
        "fingerprint":          "ghi001inv",
        "labels":               json.dumps({"app": "inventory", "severity": "warning", "alertname": "InventoryPodCrashLooping"}),
        "annotations":          json.dumps({"summary": "inventory pod restarted 5 times in 10 minutes", "description": "OOMKilled — memory limit 512Mi exceeded. Peak RSS was 620Mi."}),
        "severity":             "warning",
        "status":               "firing",
        "source":               "alertmanager",
        "fired_at":             ago(hours=6),
        "resolved_at":          None,
        "incident_id":          INCIDENT_IDS["p3_inventory"],
        "correlation_group_id": uid(),
    },
    # Resolved alerts (noise)
    {
        "id":                   uid(),
        "name":                 "UserServiceHighCPU",
        "fingerprint":          "jkl001user",
        "labels":               json.dumps({"app": "user-service", "severity": "warning", "alertname": "UserServiceHighCPU"}),
        "annotations":          json.dumps({"summary": "user-service CPU > 80%", "description": "CPU usage has been > 80% for 5 minutes."}),
        "severity":             "warning",
        "status":               "resolved",
        "source":               "alertmanager",
        "fired_at":             ago(days=1, hours=3),
        "resolved_at":          ago(days=1, hours=2, minutes=30),
        "incident_id":          None,
        "correlation_group_id": None,
    },
    {
        "id":                   uid(),
        "name":                 "APIGatewayHTTP5xxSpike",
        "fingerprint":          "mno001gw",
        "labels":               json.dumps({"app": "api-gateway", "severity": "high", "alertname": "APIGatewayHTTP5xxSpike"}),
        "annotations":          json.dumps({"summary": "API gateway 5xx rate > 1%", "description": "HTTP 5xx errors spiked to 3.2% for 2 minutes due to downstream checkout errors."}),
        "severity":             "high",
        "status":               "resolved",
        "source":               "grafana",
        "fired_at":             ago(hours=2, minutes=5),
        "resolved_at":          ago(hours=1, minutes=50),
        "incident_id":          INCIDENT_IDS["p1_checkout"],
        "correlation_group_id": None,
    },
]

INVESTIGATIONS = [
    {
        "id":           uid(),
        "incident_id":  INCIDENT_IDS["p1_checkout"],
        "status":       "completed",
        "plan":         json.dumps([
            "1. Query Mimir for checkout error rate and P99 latency (last 3h)",
            "2. Extract error patterns from checkout Loki logs",
            "3. Find slow traces in Tempo for checkout service",
            "4. Query Pyroscope for checkout CPU profile during incident",
            "5. Check Grafana annotations for recent deployments",
            "6. Assess Faro user impact (session count, Web Vitals)",
        ]),
        "findings":     json.dumps({
            "metrics": {
                "error_rate":  "12.3% (baseline: 0.3%)",
                "p99_latency": "8200ms (baseline: 180ms)",
                "throughput":  "430 rps (baseline: 450 rps — slightly reduced due to errors)",
                "slo_burn_rate": "15x",
            },
            "logs": {
                "top_errors": [
                    {"count": 4821, "pattern": "ERROR: connection pool exhausted (checkout-db)"},
                    {"count": 1203, "pattern": "ERROR: context deadline exceeded after 30s"},
                    {"count":  342, "pattern": "WARN: retry attempt 3/3 for DB connection"},
                ],
                "total_error_lines": 6366,
            },
            "traces": {
                "slowest_trace_id": "a1b2c3d4e5f6",
                "db_span_avg_ms":   7800,
                "db_span_pct":      "95% of total trace duration",
                "root_span":        "checkout.PlaceOrder",
                "bottleneck_span":  "postgres.AcquireConnection",
            },
            "profiles": {
                "top_function": "database/sql.(*DB).conn",
                "top_pct":      "67.2% of CPU time in connection wait",
                "goroutines_blocked": 847,
            },
            "frontend": {
                "affected_sessions": 2412,
                "lcp_p75_ms":        9200,
                "lcp_rating":        "poor",
                "js_errors": [
                    {"count": 1892, "type": "NetworkError", "value": "Failed to fetch /api/checkout"},
                ],
            },
        }),
        "rca": """## Incident Summary

P1 — Checkout service complete degradation. Error rate 40x above baseline, P99 latency 45x above baseline. ~2,412 user sessions impacted.

## Signal Evidence

### Metrics (Mimir)
- **Error rate:** 12.3% (baseline 0.3%) — 40x increase starting at 14:28 UTC
- **P99 latency:** 8,200ms (baseline 180ms) — 45x increase
- **SLO burn rate:** 15x — error budget exhausted within 2 hours at current rate
- **Throughput:** 430 rps (minimal change — service accepting requests but failing them)

### Logs (Loki)
- **4,821 occurrences** of `ERROR: connection pool exhausted (checkout-db)` starting at 14:27 UTC
- **1,203 occurrences** of `context deadline exceeded after 30s` — cascading timeouts
- **Correlation:** Error count closely tracks spike in traffic at 14:25 UTC (+18% above daily average)

### Traces (Tempo)
- Slowest trace: `a1b2c3d4e5f6` — 12.4s total duration
- **DB span `postgres.AcquireConnection`: avg 7,800ms** = 95% of total trace time
- All slow traces share the same bottleneck: waiting for a DB connection from the pool
- No DB query slowness once connection is acquired — the query itself is fast

### Profiles (Pyroscope)
- **67.2% of CPU time** in `database/sql.(*DB).conn` (connection acquisition)
- **847 goroutines blocked** waiting for a DB connection
- CPU profile confirms the bottleneck is pool contention, not query execution

### Frontend (Faro)
- **2,412 unique user sessions** impacted
- LCP P75: 9,200ms (good threshold: 2,500ms) — rated "poor"
- **1,892 NetworkError** exceptions: `Failed to fetch /api/checkout`

## Root Cause

**Database connection pool exhaustion caused by a traffic spike.**

The checkout service's PostgreSQL connection pool (max 50 connections) was exhausted when traffic increased 18% above daily average at 14:25 UTC. Once all connections were in use, new requests had to wait — causing cascading timeouts, goroutine pile-up, and visible error rate spike.

**Contributing factor:** Grafana annotations show a checkout-service deployment at 14:20 UTC that increased the default query timeout from 5s to 30s. This kept connections held longer under high load, accelerating pool exhaustion.

**Distinguishing root cause from symptoms:**
- Root cause: insufficient connection pool size + increased query timeout in deployment
- Symptoms: high error rate, high latency, goroutine pile-up, frontend errors

## User Impact

- **~2,412 user sessions** experienced checkout failures or severe degradation
- **~100% of users** attempting checkout during 14:27–16:15 UTC window were affected
- Estimated conversion impact: ~$48,000 in lost GMV (based on 2,412 sessions × avg order value)

## Recommended Actions

| Priority | Action | Owner | ETA |
|---|---|---|---|
| **Immediate** | Increase connection pool from 50 → 200 connections | Platform team | 1h |
| **Immediate** | Roll back timeout change from 30s → 5s | Checkout team | 30m |
| **Short-term** | Add connection pool saturation alert (threshold: 80%) | Platform team | 1 day |
| **Short-term** | Implement connection pool autoscaling via PgBouncer | Platform team | 1 week |
| **Long-term** | Add load shedding / circuit breaker at API gateway for DB pressure | Architecture | 2 weeks |

## Investigation Timeline

| Time (UTC) | Event |
|---|---|
| 14:20 | Checkout deployment v2.4.1 (increased query timeout 5s → 30s) |
| 14:25 | Traffic +18% above daily average |
| 14:27 | DB connection pool reaches 100% saturation |
| 14:28 | Error rate crosses 5% threshold — alert fires |
| 14:29 | CheckoutHighLatency alert fires |
| 14:30 | P1 incident opened |
| 14:45 | NovaSRE investigation started |
| 14:52 | Root cause identified (DB pool + timeout regression) |
| 15:10 | Timeout rolled back — partial recovery |
| 16:15 | Connection pool increased — full recovery |
""",
        "confidence":    0.94,
        "tool_calls":    json.dumps([
            {"tool": "mimir_query_range", "query": "rate(http_requests_total{app=\"checkout\",status=~\"5..\"}[5m])", "duration_ms": 120},
            {"tool": "mimir_query",       "query": "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{app=\"checkout\"}[5m]))", "duration_ms": 98},
            {"tool": "loki_extract_errors", "app": "checkout", "duration_ms": 340},
            {"tool": "tempo_search",       "query": "{ .service.name = \"checkout\" && status = error }", "duration_ms": 210},
            {"tool": "tempo_slow_traces",  "service": "checkout", "threshold_ms": 5000, "duration_ms": 185},
            {"tool": "pyroscope_query",    "app_name": "checkout", "profile_type": "cpu", "duration_ms": 560},
            {"tool": "grafana_annotations", "from_time": "14:00", "to_time": "14:30", "duration_ms": 88},
            {"tool": "faro_sessions",       "app": "checkout-web", "duration_ms": 145},
        ]),
        "started_at":    ago(hours=1, minutes=45),
        "completed_at":  ago(hours=1, minutes=30),
        "created_by":    "system:auto",
    },
    {
        "id":           uid(),
        "incident_id":  INCIDENT_IDS["p2_payment"],
        "status":       "running",
        "plan":         json.dumps([
            "1. Query Mimir for payment service error rate, latency, and throughput",
            "2. Check Tempo for slow payment traces — identify which downstream is slow",
            "3. Extract payment service error logs from Loki",
            "4. Check Grafana annotations for recent payment service or Stripe changes",
        ]),
        "findings":     json.dumps({
            "metrics": {
                "error_rate":  "0.8% (baseline: 0.05%)",
                "p99_latency": "3100ms (baseline: 200ms)",
                "throughput":  "85 rps (baseline: 88 rps)",
            },
            "traces": None,
            "logs":   None,
        }),
        "rca":           None,
        "confidence":    None,
        "tool_calls":    json.dumps([
            {"tool": "mimir_query_range", "query": "rate(http_requests_total{app=\"payment\",status=~\"5..\"}[5m])", "duration_ms": 115},
        ]),
        "started_at":    ago(hours=3, minutes=50),
        "completed_at":  None,
        "created_by":    "user:alice@your-org.com",
    },
]

INCIDENTS = [
    {
        "id":               INCIDENT_IDS["p1_checkout"],
        "title":            "P1: Checkout service — high error rate and latency",
        "description":      "Checkout service experiencing 12.3% error rate (40x baseline) and P99 latency of 8.2s (45x baseline). Root cause identified as DB connection pool exhaustion triggered by traffic spike + deployment that increased query timeout.",
        "severity":         "P1",
        "status":           "investigating",
        "affected_services": json.dumps(["checkout", "api-gateway"]),
        "start_time":       ago(hours=2),
        "resolved_time":    None,
    },
    {
        "id":               INCIDENT_IDS["p2_payment"],
        "title":            "P2: Payment service — elevated latency and timeouts",
        "description":      "Payment service P99 latency elevated to 3.1s, 2.3% of transactions timing out. Stripe API appears to be the upstream source of latency.",
        "severity":         "P2",
        "status":           "investigating",
        "affected_services": json.dumps(["payment"]),
        "start_time":       ago(hours=4),
        "resolved_time":    None,
    },
    {
        "id":               INCIDENT_IDS["p3_inventory"],
        "title":            "P3: Inventory service — OOMKilled pod restarts",
        "description":      "inventory-service pods are crash-looping (OOMKilled). Memory limit of 512Mi is being exceeded (peak 620Mi). Low user impact — read replicas handling traffic.",
        "severity":         "P3",
        "status":           "open",
        "affected_services": json.dumps(["inventory"]),
        "start_time":       ago(hours=6),
        "resolved_time":    None,
    },
]


# ---------------------------------------------------------------------------
# Database insertion
# ---------------------------------------------------------------------------
async def seed() -> None:
    from app.config import settings  # type: ignore[import]
    from app.database import create_engine  # type: ignore[import]
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        log.info("seed_start", services=len(SERVICES), incidents=len(INCIDENTS), alerts=len(ALERTS))

        # ---- Services ----
        log.info("inserting_services")
        for svc in SERVICES:
            await session.execute(
                text("""
                    INSERT INTO services (id, name, namespace, team, dependencies, slo_target, labels, created_at, updated_at)
                    VALUES (:id, :name, :namespace, :team, :dependencies::jsonb, :slo_target, :labels::jsonb, now(), now())
                    ON CONFLICT (name) DO UPDATE SET
                        dependencies = EXCLUDED.dependencies,
                        slo_target   = EXCLUDED.slo_target,
                        labels       = EXCLUDED.labels,
                        updated_at   = now()
                """),
                svc,
            )

        # ---- Incidents ----
        log.info("inserting_incidents")
        for inc in INCIDENTS:
            await session.execute(
                text("""
                    INSERT INTO incidents (id, title, description, severity, status, affected_services, start_time, resolved_time, created_at, updated_at)
                    VALUES (:id, :title, :description, :severity, :status, :affected_services::jsonb, :start_time, :resolved_time, now(), now())
                    ON CONFLICT (id) DO NOTHING
                """),
                inc,
            )

        # ---- Alerts ----
        log.info("inserting_alerts")
        for alert in ALERTS:
            await session.execute(
                text("""
                    INSERT INTO alerts (id, name, fingerprint, labels, annotations, severity, status, source, fired_at, resolved_at, incident_id, correlation_group_id, created_at, updated_at)
                    VALUES (:id, :name, :fingerprint, :labels::jsonb, :annotations::jsonb, :severity, :status, :source, :fired_at, :resolved_at, :incident_id, :correlation_group_id, now(), now())
                    ON CONFLICT (fingerprint) DO UPDATE SET
                        status       = EXCLUDED.status,
                        resolved_at  = EXCLUDED.resolved_at,
                        updated_at   = now()
                """),
                alert,
            )

        # ---- Investigations ----
        log.info("inserting_investigations")
        for inv in INVESTIGATIONS:
            await session.execute(
                text("""
                    INSERT INTO investigations (id, incident_id, status, plan, findings, rca, confidence, tool_calls, started_at, completed_at, created_by, created_at, updated_at)
                    VALUES (:id, :incident_id, :status, :plan::jsonb, :findings::jsonb, :rca, :confidence, :tool_calls::jsonb, :started_at, :completed_at, :created_by, now(), now())
                    ON CONFLICT (id) DO NOTHING
                """),
                inv,
            )

        await session.commit()

    await engine.dispose()

    log.info(
        "seed_complete",
        services=len(SERVICES),
        incidents=len(INCIDENTS),
        alerts=len(ALERTS),
        investigations=len(INVESTIGATIONS),
    )
    print("\nSeed complete!")
    print(f"  Services:       {len(SERVICES)}")
    print(f"  Incidents:      {len(INCIDENTS)}")
    print(f"  Alerts:         {len(ALERTS)}")
    print(f"  Investigations: {len(INVESTIGATIONS)}")
    print("\nOpen http://localhost:5173 to see the data in the UI.")


if __name__ == "__main__":
    asyncio.run(seed())
