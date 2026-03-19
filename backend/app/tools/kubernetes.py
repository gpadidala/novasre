"""
NovaSRE — Kubernetes Tool Implementations

Tools
-----
KubernetesPodsTool    — List pods with status/resource info
KubernetesEventsTool  — List events for a namespace or pod
KubernetesLogsTool    — Fetch container logs directly from K8s API

Strategy
--------
1. Try to use the ``kubernetes`` Python client (``pip install kubernetes``).
2. Fall back to ``kubectl`` subprocess if the client library is unavailable or
   in-cluster config cannot be loaded.

All tools are **read-only** — NovaSRE never modifies cluster state.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from typing import Any, Optional

import structlog

from app.tools.base import BaseTool, ToolResult

log = structlog.get_logger()

_mono = time.monotonic

# ---------------------------------------------------------------------------
# Kubernetes client detection
# ---------------------------------------------------------------------------

try:
    from kubernetes import client as k8s_client
    from kubernetes import config as k8s_config

    _K8S_CLIENT_AVAILABLE = True
except ImportError:
    _K8S_CLIENT_AVAILABLE = False
    log.info("kubernetes_client.not_installed", fallback="kubectl subprocess")

_KUBECTL_PATH: Optional[str] = shutil.which("kubectl")


# ---------------------------------------------------------------------------
# Client initialisation helpers
# ---------------------------------------------------------------------------

def _load_k8s_config() -> bool:
    """
    Attempt to load K8s configuration.

    Tries in-cluster config first (running inside a pod), then falls back to
    the local kubeconfig file (developer machine).  Returns ``True`` on success.
    """
    if not _K8S_CLIENT_AVAILABLE:
        return False
    try:
        k8s_config.load_incluster_config()
        return True
    except Exception:
        pass
    try:
        k8s_config.load_kube_config()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# kubectl subprocess helper
# ---------------------------------------------------------------------------

async def _kubectl(
    *args: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """
    Run a kubectl command and return the parsed JSON output.

    Raises ``RuntimeError`` if kubectl is not found or the command fails.
    """
    if not _KUBECTL_PATH:
        raise RuntimeError(
            "kubectl not found in PATH and kubernetes Python client is not available. "
            "Install either 'kubernetes' (pip) or ensure kubectl is on PATH."
        )

    cmd = [_KUBECTL_PATH, *args, "--output=json"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise RuntimeError(f"kubectl timed out after {timeout}s") from exc

    if proc.returncode != 0:
        raise RuntimeError(
            f"kubectl exited {proc.returncode}: {stderr.decode()[:500]}"
        )

    return json.loads(stdout.decode())


# ---------------------------------------------------------------------------
# KubernetesPodsTool
# ---------------------------------------------------------------------------

class KubernetesPodsTool(BaseTool):
    """
    List pods in a namespace with status, phase, restarts, and resource usage.
    """

    name = "k8s_pods"
    description = (
        "List Kubernetes pods in a namespace. "
        "Returns pod name, phase (Running/Pending/Failed), container statuses, "
        "restart counts, and resource requests/limits. "
        "Use to identify OOMKilled, CrashLoopBackOff, or Pending pods."
    )

    async def execute(  # type: ignore[override]
        self,
        namespace: str = "default",
        label_selector: Optional[str] = None,
        field_selector: Optional[str] = None,
    ) -> ToolResult:
        """
        Parameters
        ----------
        namespace:
            Kubernetes namespace to query.
        label_selector:
            Optional label selector, e.g. ``"app=checkout"``.
        field_selector:
            Optional field selector, e.g. ``"status.phase=Running"``.
        """
        time_start = _mono()
        log.info(
            "tool.execute",
            tool_name=self.name,
            namespace=namespace,
            label_selector=label_selector,
        )

        try:
            raw = await self._list_pods(namespace, label_selector, field_selector)
        except Exception as exc:  # noqa: BLE001
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(exc),
                duration_ms=elapsed,
                query=f"pods/{namespace}",
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        pods = _parse_pods(raw)

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            namespace=namespace,
            pod_count=len(pods),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "namespace": namespace,
                "pods": pods,
                "total": len(pods),
                "summary": _pods_summary(pods),
            },
            duration_ms=elapsed,
            query=f"pods/{namespace}",
        )

    async def _list_pods(
        self,
        namespace: str,
        label_selector: Optional[str],
        field_selector: Optional[str],
    ) -> dict:
        if _load_k8s_config():
            v1 = k8s_client.CoreV1Api()
            kwargs: dict[str, Any] = {}
            if label_selector:
                kwargs["label_selector"] = label_selector
            if field_selector:
                kwargs["field_selector"] = field_selector
            # Run the synchronous k8s client in a thread pool
            loop = asyncio.get_event_loop()
            pod_list = await loop.run_in_executor(
                None,
                lambda: v1.list_namespaced_pod(namespace, **kwargs),
            )
            return pod_list.to_dict()

        # Fallback: kubectl
        args = ["get", "pods", "-n", namespace]
        if label_selector:
            args += ["-l", label_selector]
        if field_selector:
            args += [f"--field-selector={field_selector}"]
        return await _kubectl(*args)


def _parse_pods(raw: dict) -> list[dict[str, Any]]:
    """Normalise pod list response (works for both k8s client dict and kubectl JSON)."""
    items = raw.get("items", [])
    parsed = []
    for pod in items:
        meta = pod.get("metadata", {})
        spec = pod.get("spec", {})
        status = pod.get("status", {})

        # Container statuses
        container_statuses = []
        for cs in status.get("containerStatuses", []):
            state = cs.get("state", {})
            state_name = next(iter(state), "unknown") if state else "unknown"
            state_detail = state.get(state_name, {})
            container_statuses.append(
                {
                    "name": cs.get("name"),
                    "ready": cs.get("ready", False),
                    "restarts": cs.get("restartCount", 0),
                    "state": state_name,
                    "reason": state_detail.get("reason"),
                    "message": state_detail.get("message"),
                    "image": cs.get("image"),
                }
            )

        # Resource requests/limits
        containers_resources = []
        for c in spec.get("containers", []):
            resources = c.get("resources", {})
            containers_resources.append(
                {
                    "name": c.get("name"),
                    "requests": resources.get("requests", {}),
                    "limits": resources.get("limits", {}),
                }
            )

        parsed.append(
            {
                "name": meta.get("name"),
                "namespace": meta.get("namespace"),
                "labels": meta.get("labels", {}),
                "phase": status.get("phase", "Unknown"),
                "conditions": [
                    {"type": c.get("type"), "status": c.get("status")}
                    for c in status.get("conditions", [])
                ],
                "container_statuses": container_statuses,
                "resources": containers_resources,
                "node": spec.get("nodeName"),
                "start_time": str(status.get("startTime") or ""),
                "pod_ip": status.get("podIP"),
            }
        )
    return parsed


def _pods_summary(pods: list[dict]) -> dict[str, Any]:
    """Quick health summary of a pod list."""
    total = len(pods)
    running = sum(1 for p in pods if p["phase"] == "Running")
    pending = sum(1 for p in pods if p["phase"] == "Pending")
    failed = sum(1 for p in pods if p["phase"] == "Failed")
    crash_loop = sum(
        1
        for p in pods
        for cs in p["container_statuses"]
        if cs.get("reason") == "CrashLoopBackOff"
    )
    oom_killed = sum(
        1
        for p in pods
        for cs in p["container_statuses"]
        if cs.get("reason") == "OOMKilled"
    )
    total_restarts = sum(
        cs.get("restarts", 0)
        for p in pods
        for cs in p["container_statuses"]
    )
    return {
        "total": total,
        "running": running,
        "pending": pending,
        "failed": failed,
        "crash_loop_back_off": crash_loop,
        "oom_killed": oom_killed,
        "total_restarts": total_restarts,
    }


# ---------------------------------------------------------------------------
# KubernetesEventsTool
# ---------------------------------------------------------------------------

class KubernetesEventsTool(BaseTool):
    """
    List Kubernetes events for a namespace or a specific pod.

    Events capture scheduler decisions, health probe failures, OOM kills, and
    image pull errors — essential context for diagnosing pod failures.
    """

    name = "k8s_events"
    description = (
        "List Kubernetes events for a namespace or pod. "
        "Returns event type (Normal/Warning), reason, message, and count. "
        "Use to diagnose OOMKilled, ImagePullBackOff, probe failures, "
        "and scheduling issues."
    )

    async def execute(  # type: ignore[override]
        self,
        namespace: str = "default",
        pod_name: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 50,
    ) -> ToolResult:
        """
        Parameters
        ----------
        namespace:
            Kubernetes namespace.
        pod_name:
            Optional pod name to filter events for a specific pod.
        event_type:
            Optional filter: ``"Warning"`` or ``"Normal"``.
        limit:
            Maximum number of events to return.
        """
        time_start = _mono()
        log.info(
            "tool.execute",
            tool_name=self.name,
            namespace=namespace,
            pod_name=pod_name,
        )

        try:
            raw = await self._list_events(namespace, pod_name)
        except Exception as exc:  # noqa: BLE001
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(exc),
                duration_ms=elapsed,
                query=f"events/{namespace}/{pod_name or '*'}",
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        events = _parse_events(raw)

        # Optional type filter
        if event_type:
            events = [e for e in events if e["type"] == event_type]

        # Sort by last occurrence, most recent first, then apply limit
        events.sort(key=lambda e: e.get("last_time") or "", reverse=True)
        events = events[:limit]

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            namespace=namespace,
            event_count=len(events),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "namespace": namespace,
                "pod_name": pod_name,
                "events": events,
                "total": len(events),
                "warning_count": sum(1 for e in events if e["type"] == "Warning"),
            },
            duration_ms=elapsed,
            query=f"events/{namespace}/{pod_name or '*'}",
        )

    async def _list_events(self, namespace: str, pod_name: Optional[str]) -> dict:
        if _load_k8s_config():
            v1 = k8s_client.CoreV1Api()
            field_selector = None
            if pod_name:
                field_selector = (
                    f"involvedObject.name={pod_name},"
                    f"involvedObject.kind=Pod"
                )
            loop = asyncio.get_event_loop()
            kwargs: dict[str, Any] = {}
            if field_selector:
                kwargs["field_selector"] = field_selector
            event_list = await loop.run_in_executor(
                None,
                lambda: v1.list_namespaced_event(namespace, **kwargs),
            )
            return event_list.to_dict()

        # Fallback: kubectl
        args = ["get", "events", "-n", namespace]
        if pod_name:
            args += [f"--field-selector=involvedObject.name={pod_name}"]
        return await _kubectl(*args)


def _parse_events(raw: dict) -> list[dict[str, Any]]:
    items = raw.get("items", [])
    parsed = []
    for event in items:
        meta = event.get("metadata", {})
        source = event.get("source", {})
        involved = event.get("involvedObject", {})
        parsed.append(
            {
                "name": meta.get("name"),
                "namespace": meta.get("namespace"),
                "type": event.get("type", "Normal"),
                "reason": event.get("reason", ""),
                "message": event.get("message", ""),
                "count": event.get("count", 1),
                "first_time": str(event.get("firstTimestamp") or ""),
                "last_time": str(event.get("lastTimestamp") or ""),
                "source_component": source.get("component"),
                "source_host": source.get("host"),
                "involved_object": {
                    "kind": involved.get("kind"),
                    "name": involved.get("name"),
                    "namespace": involved.get("namespace"),
                },
            }
        )
    return parsed


# ---------------------------------------------------------------------------
# KubernetesLogsTool
# ---------------------------------------------------------------------------

class KubernetesLogsTool(BaseTool):
    """
    Fetch container logs directly from the Kubernetes API.

    Complements Loki for situations where Loki is unavailable or logs have
    not yet been indexed.
    """

    name = "k8s_logs"
    description = (
        "Fetch container logs directly from Kubernetes for a pod. "
        "Returns the most recent log lines. "
        "Use when Loki is unavailable or to get very recent logs not yet indexed."
    )

    async def execute(  # type: ignore[override]
        self,
        pod_name: str,
        namespace: str = "default",
        container: Optional[str] = None,
        tail_lines: int = 100,
        previous: bool = False,
    ) -> ToolResult:
        """
        Parameters
        ----------
        pod_name:
            Name of the pod.
        namespace:
            Kubernetes namespace.
        container:
            Container name (required for multi-container pods).
        tail_lines:
            Number of log lines to return from the end.
        previous:
            If ``True``, return logs from the previous (crashed) container instance.
        """
        time_start = _mono()
        log.info(
            "tool.execute",
            tool_name=self.name,
            pod_name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines,
        )

        try:
            logs_text = await self._get_logs(
                pod_name, namespace, container, tail_lines, previous
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = round((_mono() - time_start) * 1000, 2)
            self._record_failure()
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(exc),
                duration_ms=elapsed,
                query=f"logs/{namespace}/{pod_name}",
            )

        elapsed = round((_mono() - time_start) * 1000, 2)
        self._record_success()

        lines = [l.rstrip() for l in logs_text.splitlines() if l.strip()]

        log.info(
            "tool.execute.success",
            tool_name=self.name,
            pod_name=pod_name,
            line_count=len(lines),
            duration_ms=elapsed,
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data={
                "pod_name": pod_name,
                "namespace": namespace,
                "container": container,
                "previous": previous,
                "lines": lines,
                "total_lines": len(lines),
            },
            duration_ms=elapsed,
            query=f"logs/{namespace}/{pod_name}",
        )

    async def _get_logs(
        self,
        pod_name: str,
        namespace: str,
        container: Optional[str],
        tail_lines: int,
        previous: bool,
    ) -> str:
        if _load_k8s_config():
            v1 = k8s_client.CoreV1Api()
            kwargs: dict[str, Any] = {
                "tail_lines": tail_lines,
                "previous": previous,
            }
            if container:
                kwargs["container"] = container
            loop = asyncio.get_event_loop()
            logs = await loop.run_in_executor(
                None,
                lambda: v1.read_namespaced_pod_log(pod_name, namespace, **kwargs),
            )
            return logs or ""

        # Fallback: kubectl logs
        args = ["logs", pod_name, "-n", namespace, f"--tail={tail_lines}"]
        if container:
            args += ["-c", container]
        if previous:
            args.append("--previous")

        # kubectl logs doesn't return JSON, so we bypass _kubectl helper
        if not _KUBECTL_PATH:
            raise RuntimeError(
                "kubectl not found in PATH and kubernetes Python client is not installed."
            )
        proc = await asyncio.create_subprocess_exec(
            _KUBECTL_PATH,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        if proc.returncode != 0:
            raise RuntimeError(
                f"kubectl logs exited {proc.returncode}: {stderr.decode()[:500]}"
            )
        return stdout.decode()
