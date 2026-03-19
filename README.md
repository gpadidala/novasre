<div align="center">

<img src="https://img.shields.io/badge/NovaSRE-AI%20Powered%20SRE-6366f1?style=for-the-badge&logo=grafana&logoColor=white" alt="NovaSRE"/>

# NovaSRE

### Next-Generation Intelligent Observability Agent

**Give your SRE team a 24/7 AI co-pilot that autonomously investigates, correlates, and explains production incidents across metrics, logs, traces, profiles, and frontend signals — in seconds, not hours.**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18+-61DAFB?style=flat-square&logo=react&logoColor=black)](https://reactjs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5+-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-FF6B35?style=flat-square&logo=chainlink&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-Ready-326CE5?style=flat-square&logo=kubernetes&logoColor=white)](https://kubernetes.io)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

[Features](#-features) • [Architecture](#-architecture) • [Quick Start](#-quick-start) • [Configuration](#-configuration) • [API Reference](#-api-reference) • [Deployment](#-kubernetes-deployment) • [Contributing](#-contributing)

</div>

---

## 🌟 What is NovaSRE?

NovaSRE is a **production-grade, self-hosted AI platform** that unifies the full Grafana observability stack into a single intelligent investigation agent. NovaSRE brings together:

- **Multi-agent RCA** — Specialist AI agents run parallel investigations across every signal source
- **3-layer alert correlation** — Temporal + topological + semantic noise reduction (85–95% alert noise cut)
- **RAPTOR Knowledge Base** — Hierarchical RAG over your runbooks, post-mortems, and past incidents
- **Anomaly Detection** — Prophet (seasonal), Z-score, and PELT change-point ensemble
- **Real-time command center** — Dark-mode UI with live WebSocket agent streaming

---

## ✨ Features

| Feature | Description |
|---|---|
| 🤖 **Multi-Agent RCA** | LangGraph orchestrated agents: Planner → Metrics, Logs, Traces, Profiles, Frontend, K8s → Synthesizer |
| 🔔 **Alert Correlation** | 3-layer engine (temporal + topological + semantic) that groups related alerts into incidents |
| 📊 **Full Signal Coverage** | Mimir (PromQL) + Loki (LogQL) + Tempo (TraceQL) + Pyroscope + Faro RUM |
| 🧠 **RAPTOR KB** | Hierarchical RAG with ChromaDB + BM25 + cross-encoder reranking for runbook retrieval |
| 📈 **Anomaly Detection** | Ensemble of Z-score, Meta Prophet, and PELT change-point detection |
| ⚡ **Real-time Streaming** | WebSocket-based agent streaming — see every tool call as it happens |
| 🔒 **Read-Only Safety** | NovaSRE never writes to your observability stack — investigation only |
| 🐳 **Docker + K8s** | One command dev stack, production-ready Kubernetes manifests with HPA |
| 🔌 **MCP Server** | Standalone Model Context Protocol server exposing all tools |
| 📚 **Self-Learning** | Auto-ingests resolved incidents into the knowledge base |

---

## 🏗 Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        NovaSRE Platform                          │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              React Frontend (Dark Mode UI)               │    │
│  │   Dashboard │ Incidents │ Investigation │ Chat │ KB       │    │
│  └──────────────────────┬──────────────────────────────────┘    │
│                         │ REST + WebSocket                       │
│  ┌──────────────────────▼──────────────────────────────────┐    │
│  │                    FastAPI Backend                        │    │
│  │        /api/v1/incidents  /api/v1/alerts  /ws/agent      │    │
│  └──────────────────────┬──────────────────────────────────┘    │
│                         │                                        │
│  ┌──────────────────────▼──────────────────────────────────┐    │
│  │         Multi-Agent Orchestration (LangGraph)            │    │
│  │                                                          │    │
│  │   ┌──────────┐   ┌──────────┐   ┌──────────┐           │    │
│  │   │ Planner  │──▶│ Metrics  │   │  Logs    │           │    │
│  │   │  Agent   │──▶│  Agent   │   │  Agent   │           │    │
│  │   │(Orchestr)│──▶│ (Mimir)  │   │  (Loki)  │           │    │
│  │   └──────────┘──▶├──────────┤   ├──────────┤           │    │
│  │                  │  Traces  │   │ Profiles │           │    │
│  │                  │  Agent   │   │  Agent   │           │    │
│  │                  │ (Tempo)  │   │(Pyroscope│           │    │
│  │                  ├──────────┤   ├──────────┤           │    │
│  │                  │Frontend  │   │  K8s     │           │    │
│  │                  │  (Faro)  │   │  Agent   │           │    │
│  │                  └──────────┘   └──────────┘           │    │
│  │                         │                               │    │
│  │                  ┌──────▼──────┐                        │    │
│  │                  │ Synthesizer │  Final RCA Report       │    │
│  │                  └─────────────┘                        │    │
│  └──────────────────────┬──────────────────────────────────┘    │
│                         │                                        │
│  ┌──────────────────────▼──────────────────────────────────┐    │
│  │                    MCP Tool Layer                         │    │
│  │  mimir_query │ loki_query │ tempo_search │ pyroscope_get  │    │
│  │  faro_vitals │ grafana_alerts │ k8s_pods │ k8s_events     │    │
│  └──────────────────────┬──────────────────────────────────┘    │
│                         │                                        │
│  ┌──────────────────────▼──────────────────────────────────┐    │
│  │               Signal Intelligence Layer                   │    │
│  │  ┌──────────────────┐  ┌──────────────────────────────┐  │    │
│  │  │ Alert Correlation │  │  Anomaly Detection Engine    │  │    │
│  │  │ ├─ Temporal       │  │  ├─ Z-Score (rolling)        │  │    │
│  │  │ ├─ Topological    │  │  ├─ Prophet (seasonal)       │  │    │
│  │  │ └─ Semantic       │  │  └─ PELT (change-point)      │  │    │
│  │  └──────────────────┘  └──────────────────────────────┘  │    │
│  │  ┌──────────────────────────────────────────────────┐     │    │
│  │  │  RAPTOR Knowledge Base                           │     │    │
│  │  │  ChromaDB │ OpenAI Embeddings │ BM25 │ Reranker  │     │    │
│  │  └──────────────────────────────────────────────────┘     │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  PostgreSQL  │  │    Redis     │  │   Grafana Stack      │   │
│  │  (incidents) │  │ (cache/pub)  │  │  Mimir/Loki/Tempo/   │   │
│  │              │  │              │  │  Pyroscope/Faro      │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
novasre/
├── backend/                        # Python FastAPI application
│   ├── app/
│   │   ├── agents/                 # LangGraph multi-agent system
│   │   │   ├── graph.py            # StateGraph definition
│   │   │   ├── planner.py          # Orchestrator agent
│   │   │   ├── metrics_agent.py    # Mimir/PromQL specialist
│   │   │   ├── logs_agent.py       # Loki/LogQL specialist
│   │   │   ├── traces_agent.py     # Tempo/TraceQL specialist
│   │   │   ├── profiles_agent.py   # Pyroscope specialist
│   │   │   ├── frontend_agent.py   # Faro/RUM specialist
│   │   │   ├── k8s_agent.py        # Kubernetes specialist
│   │   │   └── synthesizer.py      # RCA report generator
│   │   ├── tools/                  # MCP-style tool implementations
│   │   │   ├── mimir.py            # PromQL query tools
│   │   │   ├── loki.py             # LogQL query tools
│   │   │   ├── tempo.py            # TraceQL query tools
│   │   │   ├── pyroscope.py        # Profile query tools
│   │   │   ├── faro.py             # RUM query tools
│   │   │   ├── grafana.py          # Dashboard + alert tools
│   │   │   └── kubernetes.py       # K8s pod/event/log tools
│   │   ├── correlation/            # 3-layer alert correlation engine
│   │   ├── anomaly/                # Z-score + Prophet + PELT detection
│   │   ├── knowledge/              # RAPTOR KB + embeddings + BM25
│   │   ├── models/                 # SQLAlchemy ORM models
│   │   ├── schemas/                # Pydantic request/response schemas
│   │   ├── api/                    # FastAPI routers + WebSocket
│   │   └── services/               # Business logic layer
│   └── tests/                      # pytest test suites
├── frontend/                       # React + TypeScript UI
│   └── src/
│       ├── components/             # Reusable UI components
│       ├── pages/                  # Route-level page components
│       ├── hooks/                  # Custom React hooks
│       ├── store/                  # Zustand global state
│       └── lib/                    # API client + WebSocket manager
├── mcp-server/                     # Standalone MCP server
├── k8s/                            # Kubernetes manifests
├── docker-compose.yml              # Production stack
├── docker-compose.dev.yml          # Dev stack with hot reload
└── Makefile                        # Developer commands
```

---

## 🚀 Quick Start

### Prerequisites

| Tool | Version | Install |
|---|---|---|
| Docker Desktop | 4.x+ | [docker.com](https://docker.com) |
| Docker Compose | v2+ | Included with Docker Desktop |
| Git | 2.x+ | [git-scm.com](https://git-scm.com) |
| OpenAI API Key | — | [platform.openai.com](https://platform.openai.com) |

### 1. Clone the Repository

```bash
git clone https://github.com/gpadidala/novasre.git
cd novasre
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Open `.env` and set the required values:

```bash
# REQUIRED — The application will not start without these
OPENAI_API_KEY=sk-your-openai-key-here
APP_SECRET_KEY=$(openssl rand -hex 32)

# REQUIRED — Your Grafana stack endpoints
GRAFANA_URL=https://grafana.your-org.com
GRAFANA_API_KEY=your-grafana-service-account-token
MIMIR_URL=https://mimir.your-org.com
LOKI_URL=https://loki.your-org.com
TEMPO_URL=https://tempo.your-org.com
```

> **Tip:** For local testing without a Grafana stack, the app will start and the UI will work — tool calls will fail gracefully with error messages.

### 3. Start the Stack

```bash
make up
```

This builds and starts all services in one command. First run takes ~3 minutes to pull images.

| Service | URL | Description |
|---|---|---|
| **Frontend** | http://localhost:5173 | React dashboard |
| **Backend API** | http://localhost:8000 | FastAPI application |
| **Swagger Docs** | http://localhost:8000/docs | Interactive API explorer |
| **MCP Server** | http://localhost:8001 | Tool execution server |
| **PostgreSQL** | localhost:5432 | Primary database |
| **Redis** | localhost:6379 | Cache + pub/sub |
| **ChromaDB** | localhost:8002 | Vector store |

### 4. Apply Database Migrations

Open a new terminal tab and run:

```bash
make migrate
```

### 5. Seed Sample Data (Optional)

```bash
make seed
```

Loads sample incidents, alerts, and services so you can explore the UI without real data.

### 6. Verify Everything Works

```bash
make health
# Expected: {"status":"ok","db":"ok","redis":"ok","version":"0.1.0"}

make ps
# Expected: 6 containers all in "Up" state
```

Open **http://localhost:5173** to see the NovaSRE dashboard.

---

## ⚙️ Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` — never commit `.env` to version control.

### Core Settings

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | ✅ | — | OpenAI API key for GPT-4o |
| `OPENAI_MODEL_PRIMARY` | | `gpt-4o` | Primary LLM for complex reasoning |
| `OPENAI_MODEL_FAST` | | `gpt-4o-mini` | Fast model for quick tasks and summarization |
| `OPENAI_EMBEDDING_MODEL` | | `text-embedding-3-large` | Embedding model for RAPTOR KB |
| `APP_SECRET_KEY` | ✅ | — | JWT signing secret — use `openssl rand -hex 32` |
| `APP_ENV` | | `development` | `development` or `production` |
| `LOG_LEVEL` | | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `CORS_ORIGINS` | | `http://localhost:5173` | Comma-separated allowed origins |

### Database

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | ✅ | — | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `REDIS_URL` | ✅ | — | Redis URL (`redis://...`) |
| `CHROMA_HOST` | | `localhost` | ChromaDB host |
| `CHROMA_PORT` | | `8002` | ChromaDB port |

### Grafana Stack

| Variable | Required | Description |
|---|---|---|
| `GRAFANA_URL` | ✅ | Grafana Enterprise base URL |
| `GRAFANA_API_KEY` | ✅ | Grafana service account token (Viewer role minimum) |
| `GRAFANA_ORG_ID` | | Grafana organization ID (default: `1`) |
| `MIMIR_URL` | ✅ | Mimir/Prometheus-compatible base URL |
| `MIMIR_TENANT_ID` | | Multi-tenant org ID header value |
| `MIMIR_BASIC_AUTH_USER` | | Basic auth username (if required) |
| `MIMIR_BASIC_AUTH_PASSWORD` | | Basic auth password (if required) |
| `LOKI_URL` | ✅ | Loki base URL |
| `LOKI_TENANT_ID` | | Loki tenant ID |
| `TEMPO_URL` | ✅ | Tempo base URL |
| `TEMPO_TENANT_ID` | | Tempo tenant ID |
| `PYROSCOPE_URL` | | Pyroscope base URL |
| `PYROSCOPE_API_KEY` | | Pyroscope API key |
| `FARO_COLLECTOR_URL` | | Faro collector endpoint |
| `ALERTMANAGER_URL` | | Alertmanager URL for webhook ingestion |

### Alert Correlation Tuning

| Variable | Default | Description |
|---|---|---|
| `CORRELATION_TEMPORAL_WINDOW_SECONDS` | `300` | Group alerts firing within this window (seconds) |
| `CORRELATION_SEMANTIC_THRESHOLD` | `0.75` | Cosine similarity threshold for semantic grouping (0.0–1.0) |
| `CORRELATION_TOPOLOGICAL_DEPTH` | `3` | Max service dependency hops for topological correlation |

---

## 🛠 Developer Guide

### All Make Commands

```bash
make help                  # Show all available commands with descriptions

# Stack lifecycle
make up                    # Start full dev stack (build + run)
make up-detach             # Start in background (detached mode)
make down                  # Stop and remove containers
make down-volumes          # Stop + delete all persistent data (destructive!)
make restart               # Restart all services
make restart-backend       # Restart only the backend (fast)

# Database migrations
make migrate               # Apply all pending Alembic migrations
make migrate-down          # Rollback the last migration
make migrate-status        # Show current applied migration
make migrate-history       # Show full migration history
make migrate-generate MSG="add_index_on_alerts"  # Auto-generate new migration

# Data seeding
make seed                  # Load sample incidents, alerts, services
make seed-fresh            # Drop DB + re-migrate + seed from scratch

# Testing
make test                  # Run all tests
make test-tools            # Tool layer tests (Mimir, Loki, Tempo, etc.)
make test-agents           # Multi-agent system tests
make test-api              # REST API endpoint tests
make test-correlation      # Alert correlation engine tests
make test-cov              # Tests + HTML coverage report

# Code quality
make lint                  # Ruff (Python) + ESLint (TypeScript)
make format                # Ruff + isort + Prettier auto-format
make type-check            # mypy strict type checking
make check                 # lint + type-check combined

# Logs
make logs                  # Follow all container logs
make logs-backend          # Backend logs only
make logs-frontend         # Frontend logs only
make logs-mcp              # MCP server logs only

# Interactive shells
make shell-backend         # Python REPL inside backend container
make shell-db              # psql session inside postgres container
make shell-redis           # redis-cli session

# Health checks
make health                # GET /api/health
make health-ready          # GET /api/health/ready
make ps                    # Show container status table
```

### Running Tests

```bash
# Full test suite
make test

# By layer
make test-tools       # Tool layer — runs with mocked HTTP (no real Grafana needed)
make test-agents      # Agent system — runs with mocked tools
make test-api         # REST endpoints — uses test database
make test-correlation # Alert correlation logic

# Coverage report
make test-cov
open backend/htmlcov/index.html

# Run a specific test file
docker compose -f docker-compose.dev.yml exec backend \
  pytest tests/test_tools/test_mimir.py::test_mimir_query_returns_error_rate -v
```

### Adding a New Tool

1. Create `backend/app/tools/your_tool.py`:

```python
from app.tools.base import BaseTool, ToolResult

class YourNewTool(BaseTool):
    name = "your_tool_name"
    description = "What this tool does — used by the LLM to decide when to call it"

    async def execute(self, param: str, optional_param: str = "default") -> ToolResult:
        async with httpx.AsyncClient() as client:
            result = await self._get(client, f"{settings.YOUR_URL}/endpoint", {"q": param})
        return ToolResult(
            tool_name=self.name,
            success=True,
            data=result,
            duration_ms=...,
            query=param
        )
```

2. Register in `backend/app/tools/registry.py`
3. Add to the relevant agent's tool list in the agent file
4. Write tests in `backend/tests/test_tools/test_your_tool.py`
5. Add to the MCP server in `mcp-server/server.py`

### Adding a New Agent

1. Create `backend/app/agents/your_agent.py` following the pattern in `metrics_agent.py`
2. Register the node in `backend/app/agents/graph.py`
3. Add routing in the `route_from_planner()` function
4. Update `SignalFindings` TypedDict in `agents/state.py`
5. Add the finding to the Synthesizer prompt in `synthesizer.py`

---

## 📡 API Reference

Full interactive documentation: **http://localhost:8000/docs** (Swagger UI)

### Incidents

```http
GET    /api/v1/incidents                        List all incidents (filterable)
POST   /api/v1/incidents                        Create a new incident
GET    /api/v1/incidents/{id}                   Get incident by ID
PATCH  /api/v1/incidents/{id}                   Update incident status/severity
DELETE /api/v1/incidents/{id}                   Delete incident
POST   /api/v1/incidents/{id}/investigate       Trigger RCA investigation
```

### Investigations

```http
GET    /api/v1/investigations/{id}              Get investigation status + full results
GET    /api/v1/investigations/{id}/findings     Get per-signal findings breakdown
```

### Alerts

```http
GET    /api/v1/alerts                           List alerts (filter by status, service)
POST   /api/v1/alerts/webhook/alertmanager      Alertmanager webhook receiver
GET    /api/v1/alerts/{id}                      Get alert + correlation group
```

### Knowledge Base

```http
POST   /api/v1/knowledge/ingest                 Ingest runbook/post-mortem/document
GET    /api/v1/knowledge/search?q=...           Semantic + BM25 hybrid search
DELETE /api/v1/knowledge/{id}                   Remove document from KB
```

### Health Probes

```http
GET    /api/health                              Liveness probe — is the process alive?
GET    /api/health/ready                        Readiness probe — DB + Redis connected?
```

### WebSocket Agent Stream

Connect to: `ws://localhost:8000/ws/agent/{session_id}`

**Send a message:**
```json
{
  "type": "message",
  "content": "Investigate the high error rate on checkout service"
}
```

**Receive streaming events:**
```json
{ "type": "thinking",    "agent": "planner",  "content": "Analyzing incident context..." }
{ "type": "tool_call",   "tool": "mimir_query", "query": "rate(http_requests_total[5m])" }
{ "type": "tool_result", "tool": "mimir_query", "result": { "error_rate": "12.3%" } }
{ "type": "finding",     "agent": "metrics",  "content": "Error rate 12.3% — 40x baseline" }
{ "type": "tool_call",   "tool": "loki_extract_errors", "query": "{app='checkout'}" }
{ "type": "finding",     "agent": "logs",     "content": "DB connection refused — 847 occurrences" }
{ "type": "rca",         "content": "## Root Cause Analysis\n🎯 DB connection pool exhausted..." }
{ "type": "done" }
```

### Alertmanager Webhook Setup

Add this receiver to your `alertmanager.yml`:

```yaml
receivers:
  - name: novasre
    webhook_configs:
      - url: http://novasre-backend:8000/api/v1/alerts/webhook/alertmanager
        send_resolved: true
        http_config:
          bearer_token: your-mcp-server-api-key

route:
  receiver: novasre
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 12h
```

---

## 🔬 How It Works

### Multi-Agent Investigation Flow

```
User Query: "Investigate high error rate on checkout service"
         │
         ▼
   ┌─────────────┐
   │   Planner   │  Analyzes query, selects signals, sets time window
   │    Agent    │  Output: { agents: [metrics, logs, traces], window: now-1h }
   └──────┬──────┘
          │ parallel execution
    ┌─────┴──────────────────────┐
    ▼              ▼             ▼
┌─────────┐  ┌──────────┐  ┌─────────┐
│ Metrics │  │   Logs   │  │ Traces  │
│  Agent  │  │   Agent  │  │  Agent  │
│         │  │          │  │         │
│ PromQL  │  │  LogQL   │  │TraceQL  │
│ queries │  │ queries  │  │queries  │
└────┬────┘  └────┬─────┘  └────┬────┘
     │             │              │
     └─────────────┴──────┬───────┘
                          ▼
                   ┌─────────────┐
                   │ Synthesizer │  Combines all findings into RCA report
                   └─────────────┘
                          │
                          ▼
    ## Root Cause Analysis
    🎯 Root Cause: DB connection pool exhausted (pool_size=10, peak demand=47)
    📉 User Impact: ~2,400 sessions affected (8.3% of traffic)
    🔧 Immediate: kubectl set env deployment/checkout DB_POOL_SIZE=50
    🔧 Short-term: Add connection pool monitoring alert
    🔧 Long-term: Evaluate PgBouncer for connection pooling
```

### 3-Layer Alert Correlation

```
Incoming: 100 alerts/hour from Alertmanager
              │
              ▼ Layer 1: Temporal Grouping
    Sort by fired_at, sliding 5-minute window
              │ 100 → 40 groups
              ▼ Layer 2: Topological Merging
    Load service dependency graph from DB
    Merge groups where services are connected (BFS depth=3)
              │ 40 → 12 groups
              ▼ Layer 3: Semantic Merging
    Embed alert names + annotations with OpenAI
    Compute cosine similarity, merge if > 0.75
              │ 12 → 5 groups (95% noise reduction)
              ▼
    5 correlated incident groups → auto-create incidents for P1/P2
```

### RAPTOR Knowledge Base

```
Ingestion Pipeline:
  Document → Chunk (512 tokens, 50 overlap)
           → Embed (text-embedding-3-large)
           → Cluster (Gaussian Mixture)
           → Summarize clusters (GPT-4o-mini)
           → Recursively cluster summaries
           → Store tree in ChromaDB

Query Pipeline:
  Query → Dense Retrieval (ChromaDB cosine similarity, top-20)
        + Sparse Retrieval (BM25 keyword matching, top-20)
        → Reciprocal Rank Fusion (merge ranked lists)
        → Neural Reranker (cross-encoder, select top-10)
        → Return relevant context to agent
```

---

## ☸️ Kubernetes Deployment

### Prerequisites

- Kubernetes 1.24+ cluster
- `kubectl` configured with cluster access
- Container registry (Docker Hub, ECR, GCR, etc.)

### Step-by-Step Deployment

```bash
# 1. Build and push production images
docker build -t your-registry/novasre-backend:latest ./backend
docker build -t your-registry/novasre-frontend:latest ./frontend
docker push your-registry/novasre-backend:latest
docker push your-registry/novasre-frontend:latest

# 2. Create namespace
kubectl apply -f k8s/namespace.yaml

# 3. Create secrets from your .env file
kubectl create secret generic novasre-secrets \
  --from-env-file=.env \
  -n novasre

# 4. Deploy infrastructure (update image names first)
kubectl apply -f k8s/backend/configmap.yaml
kubectl apply -f k8s/backend/deployment.yaml
kubectl apply -f k8s/backend/service.yaml
kubectl apply -f k8s/backend/hpa.yaml
kubectl apply -f k8s/frontend/deployment.yaml
kubectl apply -f k8s/frontend/service.yaml
kubectl apply -f k8s/ingress.yaml

# 5. Verify deployment
kubectl get pods -n novasre
kubectl get svc -n novasre
kubectl logs -f deployment/novasre-backend -n novasre

# 6. Run migrations
kubectl exec -n novasre deployment/novasre-backend -- alembic upgrade head
```

### Resource Requirements

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit |
|---|---|---|---|---|
| Backend | 500m | 2 | 1Gi | 4Gi |
| Frontend | 100m | 500m | 128Mi | 512Mi |
| MCP Server | 200m | 1 | 512Mi | 2Gi |
| PostgreSQL | 250m | 1 | 512Mi | 2Gi |
| Redis | 100m | 500m | 128Mi | 512Mi |

### Auto-Scaling (HPA)

The backend scales automatically from 2 to 10 replicas based on CPU:

```bash
kubectl get hpa -n novasre
# NAME                   REFERENCE                   TARGETS   MINPODS   MAXPODS   REPLICAS
# novasre-backend-hpa    Deployment/novasre-backend  45%/70%   2         10        3
```

### Health Probes in K8s

```yaml
livenessProbe:
  httpGet:
    path: /api/health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /api/health/ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
```

---

## 🔒 Security

**NovaSRE is read-only by design** — it never writes to Grafana, Mimir, Loki, Tempo, Kubernetes, or any observability backend. All operations are queries and reads only.

### Best Practices

- Store all credentials in environment variables — never hardcode
- Use a dedicated Grafana service account with minimum permissions
- Run NovaSRE in its own Kubernetes namespace with network policies
- Rotate `APP_SECRET_KEY` periodically
- Use TLS/HTTPS in production (configure in your ingress)

### Minimum Grafana Permissions Required

| Permission | Why |
|---|---|
| `dashboards:read` | Read dashboard metadata |
| `alerts.instances:read` | Fetch active alert states |
| `annotations:read` | Detect deployments near incident time |
| `datasources:query` | Execute queries against Mimir/Loki/Tempo |

---

## 🏃 CI/CD Pipeline

### CI Workflow (`.github/workflows/ci.yml`)

Runs on every pull request:

```
Push to PR branch
    │
    ├── Lint (ruff + ESLint)
    ├── Type check (mypy strict)
    ├── Unit tests (pytest)
    ├── Build Docker images
    └── Integration tests
```

### Deploy Workflow (`.github/workflows/deploy.yml`)

Runs on merge to `main`:

```
Merge to main
    │
    ├── Build + tag production images
    ├── Push to container registry
    ├── Apply K8s manifests (kubectl apply)
    ├── Run smoke tests (health endpoint)
    └── Notify on failure (Slack/email)
```

---

## 🤝 Contributing

We welcome contributions of all kinds!

### Getting Started

```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/novasre.git
cd novasre

# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Start the dev stack
cp .env.example .env   # Fill in your values
make up
make migrate
make seed
```

### Pull Request Process

1. **Fork** the repository and create a feature branch
2. **Write tests** for your changes (minimum 80% coverage)
3. **Run all checks**: `make check && make test`
4. **Submit PR** with a clear description of what and why

### Commit Convention

Follow [Conventional Commits](https://conventionalcommits.org):

```
feat: add PagerDuty alert ingestion webhook
fix: correct temporal correlation window edge case
docs: add K8s deployment walkthrough
chore: upgrade LangGraph to 0.3
test: add coverage for semantic correlator
```

### Code Standards

| Language | Linter | Formatter | Type Checker |
|---|---|---|---|
| Python | ruff | ruff + isort | mypy (strict) |
| TypeScript | ESLint | Prettier | tsc (strict) |

---

## 🗺 Roadmap

### Near-term
- [ ] PagerDuty / OpsGenie bi-directional alert sync
- [ ] Slack bot — `@novasre investigate <incident>` in war room
- [ ] Confluence / Notion runbook connector
- [ ] GitHub deployment correlation (auto-detect deploys)

### Medium-term
- [ ] Multi-LLM backend — Claude, Gemini, local Ollama support
- [ ] SLO management UI — Define and track error budgets visually
- [ ] Mobile app — React Native on-call companion
- [ ] JIRA/Linear incident ticket auto-creation

### Long-term
- [ ] Predictive alerting — Flag anomalies before they become incidents
- [ ] Automated remediation suggestions with one-click execution
- [ ] Multi-cluster support — Federate across multiple K8s clusters

---

## 🙏 Acknowledgements

| Project | What we learned |
|---|---|
| [IncidentFox](https://github.com/incidentfox/incidentfox) | RAPTOR KB pattern, multi-agent orchestration, 3-layer correlation |
| [HolmesGPT](https://github.com/robusta-dev/holmesgpt) | MCP toolset pattern, read-only safety, petabyte-scale filtering |
| [k8sgpt](https://github.com/k8sgpt-ai/k8sgpt) | Pluggable analyzer pattern, multi-LLM backend architecture |
| [RAPTOR Paper (ICLR 2024)](https://arxiv.org/abs/2401.18059) | Hierarchical RAG tree construction algorithm |

---

## 📜 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 📬 Contact

**Gopal Padidala** — [gopalpadidala@gmail.com](mailto:gopalpadidala@gmail.com)

Project: [https://github.com/gpadidala/novasre](https://github.com/gpadidala/novasre)

---

<div align="center">

**Built with care for SREs who deserve better tooling**

If NovaSRE helps your team, please consider giving it a star — it motivates continued development!

[Report Bug](https://github.com/gpadidala/novasre/issues) · [Request Feature](https://github.com/gpadidala/novasre/issues) · [Discussions](https://github.com/gpadidala/novasre/discussions)

</div>
