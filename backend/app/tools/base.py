"""
NovaSRE Tool Layer — BaseTool Abstract Class

Provides the contract all tools must implement, plus shared HTTP helpers,
circuit-breaker logic, and LangChain integration.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

import httpx
import structlog
from pydantic import BaseModel

log = structlog.get_logger()


class ToolResult(BaseModel):
    """Standardised result envelope returned by every tool execution."""

    tool_name: str
    success: bool
    data: Any
    error: Optional[str] = None
    duration_ms: float
    query: Optional[str] = None  # The actual query / URL sent to the upstream


class CircuitBreaker:
    """
    Simple per-tool circuit breaker.

    States
    ------
    CLOSED  — normal operation (failures < threshold)
    OPEN    — requests short-circuit immediately (failures >= threshold)

    The circuit stays OPEN until the tool is explicitly reset or restarted.
    This is intentional: NovaSRE continues investigations using the remaining
    healthy signals rather than hammering a degraded upstream.
    """

    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self.failures = 0
        self.is_open = False

    def record_success(self) -> None:
        self.failures = 0
        self.is_open = False

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.is_open = True

    def reset(self) -> None:
        self.failures = 0
        self.is_open = False


class BaseTool(ABC):
    """
    Abstract base for every NovaSRE MCP-style tool.

    Subclasses must:
    - Set ``name`` and ``description`` class attributes.
    - Implement ``execute(**kwargs) -> ToolResult``.

    All HTTP communication should go through ``_get`` / ``_post`` to benefit
    from unified error handling, timing, and circuit-breaker tracking.
    """

    name: str = "base_tool"
    description: str = "Abstract base tool — do not instantiate directly."

    def __init__(self) -> None:
        self._cb = CircuitBreaker(threshold=3)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with the given keyword arguments."""
        ...

    # ------------------------------------------------------------------
    # Shared HTTP helpers
    # ------------------------------------------------------------------

    async def _get(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: Optional[dict] = None,
    ) -> dict:
        """
        Perform an authenticated GET request.

        Returns the parsed JSON body on success.
        Raises ``httpx.HTTPStatusError`` on 4xx/5xx so callers can wrap in
        ``_safe_execute``.
        """
        start = time.monotonic()
        response = await client.get(url, params=params or {})
        response.raise_for_status()
        elapsed = (time.monotonic() - start) * 1000

        log.debug(
            "http.get",
            url=url,
            params=params,
            status=response.status_code,
            duration_ms=round(elapsed, 2),
        )
        return response.json()

    async def _post(
        self,
        client: httpx.AsyncClient,
        url: str,
        data: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> dict:
        """
        Perform an authenticated POST request.

        Accepts either form-encoded ``data`` or ``json`` body.
        """
        start = time.monotonic()
        response = await client.post(url, data=data, json=json)
        response.raise_for_status()
        elapsed = (time.monotonic() - start) * 1000

        log.debug(
            "http.post",
            url=url,
            status=response.status_code,
            duration_ms=round(elapsed, 2),
        )
        return response.json()

    # ------------------------------------------------------------------
    # Circuit-breaker helpers
    # ------------------------------------------------------------------

    def _record_success(self) -> None:
        self._cb.record_success()

    def _record_failure(self) -> None:
        self._cb.record_failure()
        if self._cb.is_open:
            log.warning(
                "circuit_breaker.open",
                tool=self.name,
                failures=self._cb.failures,
            )

    def _check_circuit(self, start: float) -> Optional[ToolResult]:
        """Return an open-circuit ToolResult if the breaker is open."""
        if self._cb.is_open:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=(
                    f"Circuit breaker open for '{self.name}' after "
                    f"{self._cb.failures} consecutive failures. "
                    "Skipping upstream call."
                ),
                duration_ms=round((time.monotonic() - start) * 1000, 2),
            )
        return None

    # ------------------------------------------------------------------
    # Convenience wrapper
    # ------------------------------------------------------------------

    async def safe_execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool with full circuit-breaker and exception handling.

        Agents should call this instead of ``execute`` directly so that
        transient errors never propagate as unhandled exceptions.
        """
        start = time.monotonic()

        # Short-circuit if breaker is open
        circuit_result = self._check_circuit(start)
        if circuit_result is not None:
            return circuit_result

        try:
            result = await self.execute(**kwargs)
            if result.success:
                self._record_success()
            else:
                self._record_failure()
            return result
        except Exception as exc:  # noqa: BLE001
            self._record_failure()
            elapsed = round((time.monotonic() - start) * 1000, 2)
            log.error(
                "tool.execute.error",
                tool=self.name,
                error=str(exc),
                duration_ms=elapsed,
            )
            return ToolResult(
                tool_name=self.name,
                success=False,
                data=None,
                error=str(exc),
                duration_ms=elapsed,
            )

    # ------------------------------------------------------------------
    # LangChain integration
    # ------------------------------------------------------------------

    def to_langchain_tool(self):  # noqa: ANN201
        """
        Convert this tool to a LangChain ``Tool`` for binding to an LLM.

        Lazy import so tests that don't need langchain can still import base.
        """
        from langchain_core.tools import StructuredTool

        async def _run(**kwargs):  # type: ignore[return]
            result = await self.safe_execute(**kwargs)
            if result.success:
                return result.data
            return {"error": result.error}

        return StructuredTool.from_function(
            coroutine=_run,
            name=self.name,
            description=self.description,
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
