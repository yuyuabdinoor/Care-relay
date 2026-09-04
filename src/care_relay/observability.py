"""Privacy-conscious structured traces for Strands agent execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Any

from strands.hooks import (
    AfterInvocationEvent,
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookRegistry,
)

from care_relay.models import utc_now


@dataclass(frozen=True)
class TraceRecord:
    sequence: int
    timestamp: str
    agent: str
    event: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


class TraceCollector:
    """Strands hook provider that records metadata without raw sensitive values."""

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._records = [TraceRecord(**item) for item in records or []]
        self._lock = Lock()

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self.before_invocation)
        registry.add_callback(BeforeModelCallEvent, self.before_model)
        registry.add_callback(AfterModelCallEvent, self.after_model)
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)
        registry.add_callback(AfterInvocationEvent, self.after_invocation)

    def _append(
        self,
        agent: str,
        event: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._records.append(
                TraceRecord(
                    sequence=len(self._records) + 1,
                    timestamp=utc_now(),
                    agent=agent,
                    event=event,
                    summary=summary,
                    details=details or {},
                )
            )

    @staticmethod
    def _agent_name(event: Any) -> str:
        return event.agent.name or event.agent.agent_id

    def before_invocation(self, event: BeforeInvocationEvent) -> None:
        self._append(self._agent_name(event), "run_started", "Agent invocation started")

    def before_model(self, event: BeforeModelCallEvent) -> None:
        self._append(
            self._agent_name(event),
            "model_started",
            "Model reasoning cycle started",
            {"projected_input_tokens": event.projected_input_tokens},
        )

    def after_model(self, event: AfterModelCallEvent) -> None:
        stop_reason = (
            event.stop_response.stop_reason
            if event.stop_response is not None
            else "error"
        )
        self._append(
            self._agent_name(event),
            "model_finished",
            f"Model cycle ended with {stop_reason}",
            {"stop_reason": stop_reason, "error": type(event.exception).__name__ if event.exception else None},
        )

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        tool_name = event.tool_use["name"]
        self._append(
            self._agent_name(event),
            "tool_selected",
            f"Selected {tool_name}",
            {
                "tool": tool_name,
                "input_fields": sorted(event.tool_use.get("input", {}).keys()),
                "tool_use_id": event.tool_use["toolUseId"],
            },
        )

    def after_tool(self, event: AfterToolCallEvent) -> None:
        tool_name = event.tool_use["name"]
        status = "error" if event.exception else "cancelled" if event.cancel_message else "success"
        self._append(
            self._agent_name(event),
            "tool_finished",
            f"{tool_name} finished with {status}",
            {
                "tool": tool_name,
                "status": status,
                "duration_ms": round(event.duration * 1000, 2) if event.duration is not None else None,
            },
        )

    def after_invocation(self, event: AfterInvocationEvent) -> None:
        stop_reason = event.result.stop_reason if event.result is not None else "structured_output"
        self._append(
            self._agent_name(event),
            "run_stopped",
            f"Agent invocation stopped at {stop_reason}",
            {"stop_reason": stop_reason},
        )

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(item) for item in self._records]
