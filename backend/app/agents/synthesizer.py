"""
NovaSRE — Synthesizer Agent (RCA Writer)

The Synthesizer is the final node in the investigation graph.  It receives
all findings from the specialist agents and produces a structured Root Cause
Analysis (RCA) report in Markdown.

Design principles
-----------------
- Evidence-only: Never guess.  Only state what the data shows.
- Quantified impact: Always express user impact in numbers.
- Ranked confidence: High / Medium / Low evidence classification.
- Root cause vs symptoms: Always distinguish them explicitly.
- Actionable: 3 tiers of actions — immediate, short-term, long-term.

Output
------
- ``state.rca``         — Full Markdown RCA report
- ``state.confidence``  — Float 0.0–1.0 confidence in the root cause
- ``state.recommended_actions`` — List of action strings
- ``state.status``      — "complete"
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agents.state import InvestigationState, SignalFindings
from app.config import get_settings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYNTHESIZER_SYSTEM_PROMPT = """
You are the RCA Synthesizer for NovaSRE, an AI-powered SRE investigation system.
You receive findings from all specialist agents and produce a structured Root Cause Analysis.

CRITICAL RULES:
1. Never guess — only state what the data shows.  If data is missing, say so.
2. Always quantify user impact: how many sessions, what % of requests.
3. Rank evidence by confidence: High (directly observed) / Medium (inferred) / Low (circumstantial).
4. Distinguish root cause from symptoms. A spike in error rate is a symptom; a DB connection pool
   exhaustion is a root cause.
5. Provide exactly 3 action items per tier: immediate (do now), short-term (next 24h), long-term.
6. Assign a confidence score (0.0–1.0) at the end.  Base it on:
   - 0.9+: Multiple signals corroborate the same root cause with specific evidence
   - 0.7–0.9: Primary signal clearly points to root cause, secondaries consistent
   - 0.5–0.7: One signal indicates root cause, others unavailable or ambiguous
   - <0.5: Hypothesis only, insufficient data

OUTPUT FORMAT — produce the RCA in this EXACT Markdown structure.  Do not add or remove sections.
After the Markdown, output a JSON block with metadata:

---MARKDOWN START---
## Incident Summary
[1-2 sentences: what happened, when, which services, severity]

## Signal Evidence

### Metrics (Mimir)
[Bullet points of key metrics: error rate, latency, throughput. Use actual numbers if available.
Note "No data" if the signal was not queried or unavailable.]

### Logs (Loki)
[Top error patterns, stack traces, log volume anomalies.
Note "No data" if unavailable.]

### Traces (Tempo)
[Slowest traces, hot span, error propagation path.
Note "No data" if unavailable.]

### Profiles (Pyroscope)
[Top CPU/memory functions, regression analysis.
Note "No data" if unavailable.]

### Frontend (Faro)
[Core Web Vitals, JS errors, affected user sessions.
Note "No data" if unavailable.]

### Kubernetes
[Pod health, OOMKilled events, resource pressure.
Note "No data" if unavailable.]

## Root Cause
**[One sentence root cause statement]**

[2-3 sentences of supporting evidence, referencing specific data points from the signals.
If multiple hypotheses exist, rank them by confidence.]

**Evidence Confidence:** High | Medium | Low

## User Impact
- **Affected Sessions:** [X sessions or "Unknown"]
- **Error Rate:** [X% of requests or "Unknown"]
- **Duration:** [start time to end time or "Ongoing"]
- **Affected Features:** [list of user-facing features impacted]

## Recommended Actions

### Immediate (do now)
1. [Action 1]
2. [Action 2]
3. [Action 3]

### Short-term (next 24 hours)
1. [Action 1]
2. [Action 2]
3. [Action 3]

### Long-term (prevent recurrence)
1. [Action 1]
2. [Action 2]
3. [Action 3]

## Investigation Timeline
[Brief bullet list of events in chronological order, based on signal data]
---MARKDOWN END---

```json
{
  "confidence": <float 0.0-1.0>,
  "root_cause_category": "db_connection | memory_pressure | deployment_regression | dependency_failure | traffic_spike | code_bug | config_change | unknown",
  "recommended_actions": [
    "<immediate action 1>",
    "<immediate action 2>",
    "<short-term action 1>",
    "<long-term action 1>"
  ],
  "affected_user_count": <int or null>,
  "signals_used": ["metrics", "logs", "traces"]
}
```
"""


# ---------------------------------------------------------------------------
# Synthesizer node
# ---------------------------------------------------------------------------

async def synthesizer_node(state: InvestigationState) -> dict[str, Any]:
    """
    LangGraph node: Synthesizer.

    Collects all findings from state.findings, builds a comprehensive
    evidence prompt, and calls GPT-4o to produce the RCA.

    Updates:
    - state.rca
    - state.confidence
    - state.recommended_actions
    - state.status = "complete"
    """
    settings = get_settings()
    time_start = time.monotonic()
    incident_id = state.get("incident_id", "unknown")

    log.info(
        "agent.synthesizer.start",
        incident_id=incident_id,
        signals_available=_available_signals(state.get("findings", {})),
    )

    findings: SignalFindings = state.get("findings", {})
    affected_services = state.get("affected_services", [])
    query = state.get("query", "")
    time_window = state.get("time_window", {"start": "now-1h", "end": "now"})
    hypothesis = state.get("hypothesis", "")
    plan = state.get("plan", [])

    # --- Build the evidence summary for the LLM ---
    evidence_sections = _build_evidence_prompt(
        incident_id=incident_id,
        query=query,
        affected_services=affected_services,
        time_window=time_window,
        hypothesis=hypothesis,
        plan=plan,
        findings=findings,
    )

    user_msg = evidence_sections

    try:
        llm = ChatOpenAI(
            model=settings.openai_model_primary,
            temperature=0,
            api_key=settings.openai_api_key,
        )
        response = await llm.ainvoke([
            SystemMessage(content=SYNTHESIZER_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ])
        raw_content = response.content
    except Exception as exc:  # noqa: BLE001
        log.error(
            "agent.synthesizer.llm_error",
            incident_id=incident_id,
            error=str(exc),
        )
        raw_content = _fallback_rca(incident_id, query, affected_services, findings)

    # --- Parse the response ---
    rca_markdown, metadata = _parse_synthesizer_response(raw_content)

    confidence: float = metadata.get("confidence", 0.5)
    # Clamp to valid range
    confidence = max(0.0, min(1.0, float(confidence)))

    recommended_actions: list[str] = metadata.get("recommended_actions", [])

    # Prefer metadata's user count, fall back to state
    affected_user_count: int | None = metadata.get("affected_user_count") or state.get("affected_user_count")

    elapsed = round((time.monotonic() - time_start) * 1000, 2)

    log.info(
        "agent.synthesizer.complete",
        incident_id=incident_id,
        confidence=confidence,
        rca_length=len(rca_markdown),
        duration_ms=elapsed,
    )

    # Record synthesizer as a tool call
    synth_call = {
        "tool_name": "synthesizer_llm",
        "agent": "synthesizer",
        "query": f"Synthesise findings for incident {incident_id}",
        "result": f"RCA produced ({len(rca_markdown)} chars, confidence={confidence:.2f})",
        "success": bool(rca_markdown),
        "duration_ms": elapsed,
    }

    output: dict[str, Any] = {
        "rca": rca_markdown,
        "confidence": confidence,
        "recommended_actions": recommended_actions,
        "status": "complete",
        "tool_calls": [synth_call],
    }
    if affected_user_count is not None:
        output["affected_user_count"] = affected_user_count

    return output


# ---------------------------------------------------------------------------
# Evidence prompt builder
# ---------------------------------------------------------------------------

def _build_evidence_prompt(
    incident_id: str,
    query: str,
    affected_services: list[str],
    time_window: dict,
    hypothesis: str,
    plan: list[str],
    findings: SignalFindings,
) -> str:
    """
    Build the comprehensive evidence prompt that the Synthesizer LLM will use.
    Formats all per-signal findings as structured text.
    """
    sections = [
        f"INCIDENT ID: {incident_id}",
        f"QUERY / DESCRIPTION: {query}",
        f"AFFECTED SERVICES: {', '.join(affected_services) if affected_services else 'Unknown'}",
        f"TIME WINDOW: {time_window.get('start', 'unknown')} to {time_window.get('end', 'unknown')}",
        f"INITIAL HYPOTHESIS: {hypothesis or 'None provided'}",
        "",
        "INVESTIGATION PLAN:",
        "\n".join(f"  {step}" for step in plan) if plan else "  Not recorded",
        "",
        "=" * 60,
        "SIGNAL FINDINGS",
        "=" * 60,
    ]

    # Metrics findings
    metrics = findings.get("metrics") or {}
    sections.append("\n--- METRICS (Mimir/Prometheus) ---")
    if metrics.get("error"):
        sections.append(f"ERROR: {metrics['error']}")
    elif metrics:
        sections.append(_format_dict_as_text(metrics))
    else:
        sections.append("No metrics data collected.")

    # Logs findings
    logs = findings.get("logs") or {}
    sections.append("\n--- LOGS (Loki/LogQL) ---")
    if logs.get("error"):
        sections.append(f"ERROR: {logs['error']}")
    elif logs:
        sections.append(_format_dict_as_text(logs))
    else:
        sections.append("No log data collected.")

    # Traces findings
    traces = findings.get("traces") or {}
    sections.append("\n--- TRACES (Tempo/TraceQL) ---")
    if traces.get("error"):
        sections.append(f"ERROR: {traces['error']}")
    elif traces:
        sections.append(_format_dict_as_text(traces))
    else:
        sections.append("No trace data collected.")

    # Profiles findings
    profiles = findings.get("profiles") or {}
    sections.append("\n--- PROFILES (Pyroscope) ---")
    if profiles.get("error"):
        sections.append(f"ERROR: {profiles['error']}")
    elif profiles:
        sections.append(_format_dict_as_text(profiles))
    else:
        sections.append("No profiling data collected.")

    # Frontend findings
    frontend = findings.get("frontend") or {}
    sections.append("\n--- FRONTEND (Faro/RUM) ---")
    if frontend.get("error"):
        sections.append(f"ERROR: {frontend['error']}")
    elif frontend:
        sections.append(_format_dict_as_text(frontend))
    else:
        sections.append("No frontend data collected.")

    # K8s findings
    k8s = findings.get("k8s") or {}
    sections.append("\n--- KUBERNETES ---")
    if k8s.get("error"):
        sections.append(f"ERROR: {k8s['error']}")
    elif k8s:
        sections.append(_format_dict_as_text(k8s))
    else:
        sections.append("No Kubernetes data collected.")

    sections.append("\n" + "=" * 60)
    sections.append("Produce the Root Cause Analysis report following the exact format in your instructions.")

    return "\n".join(sections)


def _format_dict_as_text(d: dict, indent: int = 0) -> str:
    """Recursively format a dict as readable indented text."""
    lines = []
    prefix = "  " * indent
    for key, value in d.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(_format_dict_as_text(value, indent + 1))
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}:")
            for item in value[:10]:  # Cap at 10 list items
                if isinstance(item, dict):
                    lines.append(f"{prefix}  - {json.dumps(item)[:200]}")
                else:
                    lines.append(f"{prefix}  - {str(item)[:200]}")
        else:
            lines.append(f"{prefix}{key}: {str(value)[:300]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _parse_synthesizer_response(content: str) -> tuple[str, dict]:
    """
    Parse the synthesizer response into (markdown_rca, metadata_dict).

    The LLM is instructed to output:
    1. Markdown between ---MARKDOWN START--- and ---MARKDOWN END--- markers
    2. A JSON block with metadata

    Falls back gracefully if the markers are missing.
    """
    rca_markdown = ""
    metadata: dict = {}

    # Extract markdown section
    if "---MARKDOWN START---" in content and "---MARKDOWN END---" in content:
        try:
            start = content.index("---MARKDOWN START---") + len("---MARKDOWN START---")
            end = content.index("---MARKDOWN END---")
            rca_markdown = content[start:end].strip()
        except ValueError:
            pass

    # Fall back: if markers absent, use everything before the JSON block as markdown
    if not rca_markdown:
        if "```json" in content:
            json_start = content.index("```json")
            rca_markdown = content[:json_start].strip()
        else:
            rca_markdown = content.strip()

    # Extract JSON metadata block
    if "```json" in content:
        try:
            json_start = content.index("```json") + 7
            json_end = content.index("```", json_start)
            metadata = json.loads(content[json_start:json_end].strip())
        except (ValueError, json.JSONDecodeError):
            pass

    # Extract confidence from markdown if not in metadata
    if "confidence" not in metadata:
        conf_match = re.search(r"confidence[:\s]+([0-9.]+)", content, re.IGNORECASE)
        if conf_match:
            try:
                metadata["confidence"] = float(conf_match.group(1))
            except ValueError:
                metadata["confidence"] = 0.5
        else:
            metadata["confidence"] = 0.5

    return rca_markdown or content, metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _available_signals(findings: SignalFindings) -> list[str]:
    """Return list of signal names that have non-error findings."""
    available = []
    for signal in ["metrics", "logs", "traces", "profiles", "frontend", "k8s"]:
        data = findings.get(signal)  # type: ignore[literal-required]
        if data and not data.get("error"):
            available.append(signal)
    return available


def _fallback_rca(
    incident_id: str,
    query: str,
    affected_services: list[str],
    findings: SignalFindings,
) -> str:
    """
    Generate a minimal RCA when the LLM call fails entirely.
    Provides a templated response with whatever data is available.
    """
    services_str = ", ".join(affected_services) if affected_services else "Unknown services"
    available = _available_signals(findings)
    signals_str = ", ".join(available) if available else "None"

    return f"""---MARKDOWN START---
## Incident Summary
Investigation for incident {incident_id} involving {services_str}.
Query: {query}

## Signal Evidence

### Metrics (Mimir)
{_format_dict_as_text(findings.get('metrics') or {}) or 'No data collected.'}

### Logs (Loki)
{_format_dict_as_text(findings.get('logs') or {}) or 'No data collected.'}

### Traces (Tempo)
No data collected.

### Profiles (Pyroscope)
No data collected.

### Frontend (Faro)
No data collected.

### Kubernetes
No data collected.

## Root Cause
**Unable to determine root cause automatically — LLM synthesis failed.**

Investigation data was collected from the following signals: {signals_str}.
Manual analysis is required.

**Evidence Confidence:** Low

## User Impact
- **Affected Sessions:** Unknown
- **Error Rate:** Unknown
- **Duration:** Unknown
- **Affected Features:** Unknown

## Recommended Actions

### Immediate (do now)
1. Review the collected signal data manually.
2. Check Grafana dashboards for the affected services.
3. Escalate to the on-call engineer for manual investigation.

### Short-term (next 24 hours)
1. Identify the root cause from the collected evidence.
2. Apply a fix or workaround.
3. Monitor for recurrence.

### Long-term (prevent recurrence)
1. Improve automated investigation coverage.
2. Add alerting for the identified failure mode.
3. Document this incident in the runbook.

## Investigation Timeline
- Investigation triggered for incident {incident_id}
- Signals collected: {signals_str}
- Synthesis failed due to LLM error — manual review required
---MARKDOWN END---

```json
{{"confidence": 0.1, "root_cause_category": "unknown", "recommended_actions": ["Manual review required"], "affected_user_count": null, "signals_used": {json.dumps(available)}}}
```"""
