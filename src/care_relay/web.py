"""Local command-center API for the Care Relay demo."""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from pathlib import Path
from threading import RLock, Thread
from typing import Any, ClassVar
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from care_relay.demo import build_demo_case
from care_relay.engine import InvalidTransition, apply_event
from care_relay.models import ApprovalStatus, EventType
from care_relay.observability import TraceCollector
from care_relay.repository import CaseRepository
from care_relay.runtime import AgentRun
from care_relay.tools import CareRelayTools

STATIC_DIR = Path(__file__).with_name("static")
LOGGER = logging.getLogger(__name__)


def _public_runtime_error(exc: Exception) -> str:
    """Return a useful demo-safe message without exposing provider internals."""
    detail = f"{type(exc).__name__}: {exc}".lower()
    if "loginrefreshrequired" in detail or "session has expired" in detail:
        return "AWS session expired. Run 'aws login', then reset and retry the demo."
    if "accessdenied" in detail or "not authorized" in detail:
        return "Bedrock access was denied. Confirm the AWS profile and model access, then retry."
    if "throttl" in detail:
        return "Bedrock is temporarily throttling requests. Wait briefly, then retry."
    return "The live agent run stopped safely. Check the server log, then reset and retry."


class _EmptyNoArgToolInputFilter(logging.Filter):
    """Hide a harmless Strands warning emitted for known zero-argument tools."""

    TOOL_NAMES: ClassVar[set[str]] = {
        "get_case_snapshot",
        "list_approved_family_members",
        "get_available_follow_up_slots",
        "check_referral_receipt",
        "propose_referral_correction",
        "verify_corrected_referral",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not (
            "raw_input=<> | failed to parse tool input json" in message
            and any(f"tool_name=<{name}>" in message for name in self.TOOL_NAMES)
        )


logging.getLogger("strands.event_loop.streaming").addFilter(_EmptyNoArgToolInputFilter())


class Decision(BaseModel):
    approved: bool
    decided_by: str = "Aisha"


class AgentDecision(Decision):
    approval_id: str


class ExternalMessage(BaseModel):
    source: str
    channel: str = "Email"
    subject: str
    message: str


class RuntimeInvocation(BaseModel):
    """AgentCore-compatible invocation envelope."""

    input: dict[str, Any] = Field(default_factory=dict)


class DemoSession:
    """Synthetic case state shared by the dashboard and live Strands runtime."""

    def __init__(self, repository: CaseRepository | None = None) -> None:
        self.lock = RLock()
        self.repository = repository or CaseRepository(
            os.getenv("CARE_RELAY_DB_PATH", ".care-relay/care_relay.db")
        )
        restored = self.repository.load("VISIT-1042")
        if restored is None:
            self.reset()
        else:
            self.case = restored["case"]
            self.tools = CareRelayTools(self.case, restored["world"], state_lock=self.lock)
            self.stage = restored["stage"]
            self.agent_session_id = restored.get(
                "agent_session_id", f"care-relay-{uuid4().hex}"
            )
            self.agent_run = None
            self.activity = restored["activity"]
            self.external_events = restored["external_events"]
            self.trace_records = restored.get("traces", [])
            self.background_state = "idle"
            self.background_error: str | None = None

    def reset(self) -> None:
        self.case = build_demo_case()
        self.tools = CareRelayTools(self.case, state_lock=self.lock)
        self.stage = 0
        self.agent_session_id = f"care-relay-{uuid4().hex}"
        self.agent_run: AgentRun | None = None
        self.activity: list[dict[str, str]] = []
        self.external_events: list[dict[str, str]] = []
        self.trace_records: list[dict[str, Any]] = []
        self.background_state = "idle"
        self.background_error: str | None = None
        apply_event(
            self.case,
            EventType.CASE_OPENED,
            "care-relay.intake",
            {
                "appointment_at": "2026-09-10T10:00:00-04:00",
                "transport_owner": "Marcus",
            },
        )
        self.activity.append(
            {
                "agent": "Coordinator",
                "kind": "observed",
                "message": "Visit commitments discovered from calendars and messages.",
            }
        )
        self.persist()

    def persist(self) -> None:
        """Atomically save all non-model case state after a successful mutation."""
        self.repository.save(
            self.case,
            self.tools.world,
            stage=self.stage,
            agent_session_id=self.agent_session_id,
            activity=self.activity,
            external_events=self.external_events,
            traces=self.agent_run.trace_collector.snapshot()
            if self.agent_run is not None
            else self.trace_records,
        )

    def advance(self) -> None:
        if self.case.pending_approvals:
            raise InvalidTransition("Caregiver decision required before agents can resume")
        actions = [
            self._receive_schedule_change,
            self._repair_transport,
            self._challenge_referral,
            self._inspect_transmission,
            self._request_approval,
            self._verify_and_finish,
        ]
        if self.stage >= len(actions):
            raise InvalidTransition("Demo is already complete")
        actions[self.stage]()
        self.stage += 1
        self.persist()

    def _receive_schedule_change(self) -> None:
        self.external_events.append(
            {
                "source": "Northside Imaging",
                "channel": "Email",
                "subject": "Appointment time updated",
                "message": "Daniel's imaging appointment has moved from Sep 10 at 10:00 AM to Sep 11 at 2:30 PM.",
                "received_at": "Just now",
            }
        )
        apply_event(
            self.case,
            EventType.APPOINTMENT_MOVED,
            "northside-imaging.inbox",
            {
                "new_appointment_at": "2026-09-11T14:30:00-04:00",
                "source": "MSG-APPT-002",
            },
        )
        self.activity.append(
            {
                "agent": "Coordinator",
                "kind": "replanned",
                "message": "Appointment moved. Transport and follow-up were invalidated automatically.",
            }
        )

    def _repair_transport(self) -> None:
        availability = self.tools.check_family_availability("Elena", self.case.appointment_at or "")
        self.tools.request_family_transport("Elena")
        self.activity.append(
            {
                "agent": "Coordinator",
                "kind": "acted",
                "message": f"Checked Elena ({'available' if availability['available'] else 'unavailable'}) and secured transport.",
            }
        )

    def _challenge_referral(self) -> None:
        self.tools.check_referral_receipt()
        self.external_events.append(
            {
                "source": "Northside Imaging Department",
                "channel": "Portal check",
                "subject": "Referral not found",
                "message": "No valid referral is attached to this appointment.",
                "received_at": "Just now",
            }
        )
        self.activity.append(
            {
                "agent": "Verifier",
                "kind": "contradiction",
                "message": "Imaging reports no valid referral despite the clinic's sent claim.",
            }
        )

    def _inspect_transmission(self) -> None:
        result = self.tools.inspect_transmission("TX-8841")
        self.activity.append(
            {
                "agent": "Coordinator",
                "kind": "investigated",
                "message": f"Found the handoff failure: delivered to {result['destination']}.",
            }
        )

    def _request_approval(self) -> None:
        self.tools.propose_referral_correction()
        self.activity.append(
            {
                "agent": "Coordinator",
                "kind": "decision",
                "message": "Paused before disclosing identifiers in an external correction.",
            }
        )

    def decide(self, approval_id: str, decision: Decision) -> None:
        self.tools.record_approval(approval_id, decision.approved, decision.decided_by)
        self.activity.append(
            {
                "agent": decision.decided_by,
                "kind": "approved" if decision.approved else "rejected",
                "message": "Approved the scoped referral correction."
                if decision.approved
                else "Rejected the referral correction.",
            }
        )
        if decision.approved:
            self.tools.send_referral_correction(approval_id)
            self.activity.append(
                {
                    "agent": "Coordinator",
                    "kind": "acted",
                    "message": "Sent the approved correction; awaiting independent verification.",
                }
            )
        self.persist()

    def _verify_and_finish(self) -> None:
        self.tools.verify_corrected_referral()
        self.tools.reschedule_follow_up("2026-09-15T11:00:00-04:00")
        self.activity.extend(
            [
                {
                    "agent": "Verifier",
                    "kind": "verified",
                    "message": "Recipient independently confirmed the corrected referral.",
                },
                {
                    "agent": "Coordinator",
                    "kind": "complete",
                    "message": "Follow-up repaired. Every mandatory dependency is verified.",
                },
            ]
        )

    def snapshot(self) -> dict[str, Any]:
        commitments = []
        for key, item in self.case.commitments.items():
            commitments.append(
                {
                    "id": key,
                    "label": item.label,
                    "kind": item.kind.value,
                    "state": item.state.value,
                    "owner": item.owner,
                    "blocker": item.blocker,
                    "evidence": [asdict(self.case.evidence[eid]) for eid in item.evidence_ids],
                }
            )
        approvals = [
            asdict(item)
            for item in self.case.approvals.values()
            if item.status is ApprovalStatus.PENDING
        ]
        strands_dir = Path(
            os.getenv("CARE_RELAY_STRANDS_SESSION_DIR", ".care-relay/strands-sessions")
        )
        can_restore_agents = bool(approvals) and (
            strands_dir / f"session_{self.agent_session_id}"
        ).exists()
        runtime_status = (
            {
                "state": "running",
                "message": "Strands agents are working",
                "interrupts": [],
            }
            if self.background_state == "running"
            else {
                "state": "error",
                "message": self.background_error or "Agent run failed",
                "interrupts": [],
            }
            if self.background_state == "error"
            else self.agent_run.status()
            if self.agent_run is not None
            else {"state": "not_started", "interrupts": []}
        )
        traces = (
            self.agent_run.trace_collector.snapshot()
            if self.agent_run is not None
            else self.trace_records
        )
        return {
            "case": {
                "id": self.case.case_id,
                "recipient": self.case.care_recipient_alias,
                "coordinator": self.case.coordinator_alias,
                "appointment_at": self.case.appointment_at,
                "status": self.case.status.value,
                "readiness": self.case.readiness_percent,
            },
            "commitments": commitments,
            "dependencies": [asdict(edge) for edge in self.case.dependencies],
            "approvals": approvals,
            "activity": self._visible_activity(traces),
            "external_events": list(reversed(self.external_events)),
            "ledger": [asdict(entry) for entry in reversed(self.case.ledger)],
            "stage": self.stage,
            "can_start_agents": self.stage == 1 and self.agent_run is None,
            "can_process_event": self.stage == 0 and self.agent_run is None,
            "can_restore_agents": can_restore_agents and self.agent_run is None,
            "complete": self.case.status.value == "ready",
            "agent_runtime": runtime_status,
            "traces": traces,
        }

    def _visible_activity(self, traces: list[dict[str, Any]]) -> list[dict[str, str]]:
        messages = {
            "record_appointment_change": "Recorded the new appointment and propagated its impact.",
            "list_approved_family_members": "Found the caregiver-approved transport circle.",
            "check_family_availability": "Checked family availability for the new appointment.",
            "request_family_transport": "Secured replacement transportation.",
            "get_available_follow_up_slots": "Checked the provider calendar for valid follow-up slots.",
            "reschedule_follow_up": "Rescheduled follow-up within standing permission.",
            "check_referral_receipt": "Checked whether Imaging received the referral.",
            "inspect_transmission": "Inspected the claimed referral transmission destination.",
            "propose_referral_correction": "Prepared a narrowly scoped correction for approval.",
            "send_referral_correction": "Sent the approved referral correction.",
            "verify_corrected_referral": "Independently verified recipient acceptance.",
            "ask_verification_agent": "Delegated the disputed handoff to the independent Verifier.",
        }
        progress_messages = {
            "record_appointment_change": "Applying the provider update to dependent commitments…",
            "list_approved_family_members": "Finding transport options inside Aisha’s approved circle…",
            "check_family_availability": "Checking whether an approved family member can take the new time…",
            "request_family_transport": "Requesting replacement transportation…",
            "get_available_follow_up_slots": "Checking valid follow-up windows after the new appointment…",
            "reschedule_follow_up": "Moving the follow-up within standing permission…",
            "ask_verification_agent": "Delegating the disputed handoff to the independent Verifier…",
            "check_referral_receipt": "Checking the Imaging department’s receipt record…",
            "inspect_transmission": "Inspecting where the original transmission actually went…",
            "propose_referral_correction": "Preparing the smallest correction that could resolve the blocker…",
            "send_referral_correction": "Waiting at the protected disclosure boundary…",
            "verify_corrected_referral": "Confirming receipt with Imaging independently…",
        }
        evidence_tools = {
            "check_referral_receipt",
            "inspect_transmission",
            "verify_corrected_referral",
        }
        code_tools = {"record_appointment_change"}
        live = []
        seen_messages: set[str] = set()
        for item in traces:
            details = item.get("details", {})
            if item.get("event") != "tool_selected":
                continue
            tool_name = details.get("tool")
            if tool_name not in progress_messages:
                continue
            later_finish = any(
                later.get("event") == "tool_finished"
                and later.get("agent") == item.get("agent")
                and later.get("details", {}).get("tool") == tool_name
                and later.get("sequence", 0) > item.get("sequence", 0)
                for later in traces
            )
            if not later_finish:
                live.append(
                    {
                        "agent": "Verifier" if item.get("agent") == "verification_agent" else "Coordinator",
                        "kind": "in progress",
                        "layer": "evidence" if tool_name in evidence_tools else "code" if tool_name in code_tools else "agent",
                        "message": progress_messages[tool_name],
                        "duration": "working now",
                    }
                )
        for item in reversed(traces):
            details = item.get("details", {})
            tool_name = details.get("tool")
            if item.get("event") != "tool_finished" or tool_name not in messages:
                continue
            status = details.get("status")
            if tool_name == "send_referral_correction" and status == "cancelled":
                message = "Respected Aisha’s decision; the correction remained unsent."
                kind = "human boundary"
                layer = "code"
            elif status == "success":
                message = messages[tool_name]
                kind = "verified" if "verify" in tool_name else "acted"
                layer = "evidence" if tool_name in evidence_tools else "code" if tool_name in code_tools else "agent"
            else:
                continue
            if message in seen_messages:
                continue
            seen_messages.add(message)
            live.append(
                {
                    "agent": "Verifier"
                    if item.get("agent") == "verification_agent"
                    else "Coordinator",
                    "kind": kind,
                    "layer": layer,
                    "message": message,
                    "duration": f"{details['duration_ms'] / 1000:.1f}s" if details.get("duration_ms") and details["duration_ms"] >= 1000 else "",
                }
            )
        return live[:10] + list(reversed(self.activity))

    def begin_external_message(self, message: ExternalMessage) -> None:
        """Start a live Strands event run without blocking the HTTP request."""
        if self.agent_run is not None or self.background_state == "running":
            raise InvalidTransition("A Strands agent run already exists")
        self.agent_run = AgentRun(
            self.tools,
            session_id=self.agent_session_id,
            trace_collector=TraceCollector(self.trace_records),
        )
        self.external_events.append(
            {
                "source": message.source,
                "channel": message.channel,
                "subject": message.subject,
                "message": message.message,
                "received_at": "Just now",
            }
        )
        self.background_state = "running"
        self.background_error = None
        self.persist()
        Thread(
            target=self._run_external_message,
            args=(message,),
            daemon=True,
            name=f"care-relay-{self.case.case_id}",
        ).start()

    def _run_external_message(self, message: ExternalMessage) -> None:
        try:
            assert self.agent_run is not None
            self.agent_run.start_from_external_message(
                source=message.source,
                subject=message.subject,
                body=message.message,
            )
            with self.lock:
                if self.case.appointment_at == "2026-09-11T14:30:00-04:00":
                    self.stage = max(self.stage, 1)
                self.background_state = "idle"
                self.trace_records = self.agent_run.trace_collector.snapshot()
                self.persist()
        except Exception as exc:
            LOGGER.exception("Live agent run failed")
            with self.lock:
                self.background_state = "error"
                self.background_error = _public_runtime_error(exc)
                if self.agent_run is not None:
                    self.trace_records = self.agent_run.trace_collector.snapshot()
                self.persist()

    def begin_resume(self, decision: AgentDecision) -> None:
        """Record a decision and resume Strands on a background worker."""
        if self.background_state == "running":
            return
        if self.agent_run is None:
            raise InvalidTransition("No Strands agent run exists")
        existing = self.case.approvals.get(decision.approval_id)
        if existing is not None and existing.status in {
            ApprovalStatus.CONSUMED,
            ApprovalStatus.REJECTED,
        }:
            recorded_approved = existing.status is ApprovalStatus.CONSUMED
            if recorded_approved != decision.approved:
                raise InvalidTransition("Recorded approval decision cannot be changed")
            return
        self.tools.record_approval(
            decision.approval_id,
            decision.approved,
            decision.decided_by,
        )
        self.background_state = "running"
        self.background_error = None
        self.persist()
        Thread(
            target=self._run_resume,
            args=(decision.approved,),
            daemon=True,
            name=f"care-relay-resume-{self.case.case_id}",
        ).start()

    def _run_resume(self, approved: bool) -> None:
        try:
            assert self.agent_run is not None
            self.agent_run.resume(approved)
            with self.lock:
                if self.case.status.value == "ready":
                    self.stage = 6
                self.background_state = "idle"
                self.trace_records = self.agent_run.trace_collector.snapshot()
                self.persist()
        except Exception as exc:
            LOGGER.exception("Live agent resume failed")
            with self.lock:
                self.background_state = "error"
                self.background_error = _public_runtime_error(exc)
                if self.agent_run is not None:
                    self.trace_records = self.agent_run.trace_collector.snapshot()
                self.persist()

    def start_agent_run(self) -> None:
        if self.stage < 1:
            raise InvalidTransition("Introduce the appointment change before starting agents")
        if self.agent_run is not None:
            raise InvalidTransition("The Strands agent run has already started")
        self.agent_run = AgentRun(
            self.tools,
            session_id=self.agent_session_id,
            trace_collector=TraceCollector(self.trace_records),
        )
        self.agent_run.start()
        self.trace_records = self.agent_run.trace_collector.snapshot()
        self.persist()

    def process_external_message(self, message: ExternalMessage) -> None:
        if self.agent_run is not None:
            raise InvalidTransition("A Strands agent run already exists")
        self.agent_run = AgentRun(
            self.tools,
            session_id=self.agent_session_id,
            trace_collector=TraceCollector(self.trace_records),
        )
        self.agent_run.start_from_external_message(
            source=message.source,
            subject=message.subject,
            body=message.message,
        )
        self.external_events.append(
            {
                "source": message.source,
                "channel": message.channel,
                "subject": message.subject,
                "message": message.message,
                "received_at": "Just now",
            }
        )
        if self.case.appointment_at == "2026-09-11T14:30:00-04:00":
            self.stage = max(self.stage, 1)
        self.trace_records = self.agent_run.trace_collector.snapshot()
        self.persist()

    def resume_agent_run(self, decision: AgentDecision) -> None:
        if self.agent_run is None:
            raise InvalidTransition("No Strands agent run exists")
        existing = self.case.approvals.get(decision.approval_id)
        if existing is not None and existing.status in {
            ApprovalStatus.CONSUMED,
            ApprovalStatus.REJECTED,
        }:
            recorded_approved = existing.status is ApprovalStatus.CONSUMED
            if recorded_approved != decision.approved:
                raise InvalidTransition("Recorded approval decision cannot be changed")
            return
        self.tools.record_approval(
            decision.approval_id,
            decision.approved,
            decision.decided_by,
        )
        self.agent_run.resume(decision.approved)
        self.trace_records = self.agent_run.trace_collector.snapshot()
        if self.case.status.value == "ready":
            self.stage = 6
        self.persist()

    def restore_agent_run(self) -> None:
        if self.agent_run is not None:
            raise InvalidTransition("The Strands agent run is already loaded")
        run = AgentRun(
            self.tools,
            session_id=self.agent_session_id,
            trace_collector=TraceCollector(self.trace_records),
        )
        if not run.pending_interrupts:
            raise InvalidTransition("No paused Strands interrupt was found for this case")
        self.agent_run = run


session = DemoSession()
app = FastAPI(title="Care Relay", docs_url=None, redoc_url=None)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "landing.html")


@app.get("/demo")
def demo() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/landing.css")
def landing_styles() -> FileResponse:
    return FileResponse(STATIC_DIR / "landing.css")


@app.get("/landing.js")
def landing_script() -> FileResponse:
    return FileResponse(STATIC_DIR / "landing.js")


@app.get("/favicon.svg")
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg")


@app.get("/styles.css")
def styles() -> FileResponse:
    return FileResponse(STATIC_DIR / "styles.css")


@app.get("/app.js")
def javascript() -> FileResponse:
    return FileResponse(STATIC_DIR / "app.js")


@app.get("/api/case")
def get_case() -> dict[str, Any]:
    with session.lock:
        return session.snapshot()


@app.get("/ping")
def ping() -> dict[str, str]:
    """AgentCore Runtime health contract."""
    return {"status": "Healthy"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/invocations")
def invoke_runtime(invocation: RuntimeInvocation) -> dict[str, Any]:
    """AgentCore Runtime protocol adapter over the same durable case service."""
    payload = invocation.input
    action = payload.get("action", "status")
    with session.lock:
        try:
            if action == "status":
                pass
            elif action == "process_event":
                session.process_external_message(
                    ExternalMessage(
                        source=payload["source"],
                        channel=payload.get("channel", "AgentCore"),
                        subject=payload["subject"],
                        message=payload["message"],
                    )
                )
            elif action == "approve":
                approved = payload["approved"]
                if not isinstance(approved, bool):
                    raise HTTPException(
                        status_code=422,
                        detail="approved must be a JSON boolean",
                    )
                session.resume_agent_run(
                    AgentDecision(
                        approval_id=payload["approval_id"],
                        approved=approved,
                        decided_by=payload.get("decided_by", "Aisha"),
                    )
                )
            elif action == "restore":
                session.restore_agent_run()
            else:
                raise InvalidTransition(f"Unsupported runtime action: {action}")
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=f"Missing field: {exc.args[0]}") from exc
        except HTTPException:
            raise
        except (InvalidTransition, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"result": session.snapshot()}


@app.post("/api/demo/reset")
def reset_demo() -> dict[str, Any]:
    with session.lock:
        if session.background_state == "running":
            raise HTTPException(status_code=409, detail="Wait for the active agent run to stop")
        session.reset()
        return session.snapshot()


@app.post("/api/agents/start")
def start_agents() -> dict[str, Any]:
    """Start the live Bedrock-backed Strands loop after the external disruption."""
    with session.lock:
        try:
            session.start_agent_run()
        except InvalidTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            session.agent_run = None
            raise HTTPException(
                status_code=503,
                detail="Bedrock agent run unavailable; verify AWS login and model access.",
            ) from exc
        return session.snapshot()


@app.post("/api/agents/process-event")
def process_event(message: ExternalMessage) -> dict[str, Any]:
    """Interpret an untrusted external message through the live Strands coordinator."""
    with session.lock:
        try:
            session.begin_external_message(message)
        except InvalidTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            session.agent_run = None
            raise HTTPException(
                status_code=503,
                detail="Bedrock event interpretation unavailable; verify AWS login and model access.",
            ) from exc
        return session.snapshot()


@app.post("/api/agents/resume")
def resume_agents(decision: AgentDecision) -> dict[str, Any]:
    """Record the human decision and resume the preserved Strands agent instance."""
    with session.lock:
        try:
            session.begin_resume(decision)
        except (InvalidTransition, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return session.snapshot()


@app.post("/api/agents/restore")
def restore_agents() -> dict[str, Any]:
    """Reload a persisted Strands interrupt after a dashboard process restart."""
    with session.lock:
        try:
            session.restore_agent_run()
        except InvalidTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            session.agent_run = None
            raise HTTPException(
                status_code=503,
                detail="Paused agent state exists but Bedrock credentials are unavailable.",
            ) from exc
        return session.snapshot()


def main() -> None:
    uvicorn.run(
        "care_relay.web:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
