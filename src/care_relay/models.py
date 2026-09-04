"""Typed domain models for Care Relay's deterministic core."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017 -- local runner is Python 3.9


class CaseStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    INVESTIGATING = "investigating"
    DECISION_REQUIRED = "decision_required"
    READY = "ready"


class CommitmentKind(str, Enum):
    APPOINTMENT = "appointment"
    TRANSPORT = "transport"
    REFERRAL = "referral"
    FOLLOW_UP = "follow_up"


class CommitmentState(str, Enum):
    DISCOVERED = "discovered"
    ASSIGNED = "assigned"
    CLAIMED = "claimed"
    VERIFIED = "verified"
    BLOCKED = "blocked"
    CONFLICTED = "conflicted"
    NEEDS_APPROVAL = "needs_approval"


class EvidenceKind(str, Enum):
    FACT = "fact"
    CLAIM = "claim"
    VERIFICATION = "verification"
    INFERENCE = "inference"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONSUMED = "consumed"


class EventType(str, Enum):
    CASE_OPENED = "case_opened"
    APPOINTMENT_MOVED = "appointment_moved"
    FAMILY_TRANSPORT_ACCEPTED = "family_transport_accepted"
    REFERRAL_REJECTED = "referral_rejected"
    TRANSMISSION_INSPECTED = "transmission_inspected"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    CORRECTION_SENT = "correction_sent"
    REFERRAL_CONFIRMED = "referral_confirmed"
    FOLLOW_UP_RESCHEDULED = "follow_up_rescheduled"


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    commitment_id: str
    kind: EvidenceKind
    source: str
    summary: str
    observed_at: str = field(default_factory=utc_now)


@dataclass
class Commitment:
    commitment_id: str
    kind: CommitmentKind
    label: str
    required: bool = True
    state: CommitmentState = CommitmentState.DISCOVERED
    owner: str | None = None
    blocker: str | None = None
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Dependency:
    """A causal edge whose source change invalidates a downstream commitment."""

    source_id: str
    target_id: str
    relation: str
    invalidation_reason: str


@dataclass
class Approval:
    approval_id: str
    action: str
    recipient: str
    reason: str
    disclosure: tuple[str, ...]
    requested_by: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: str | None = None
    decided_at: str | None = None


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str
    event_type: EventType
    actor: str
    details: dict[str, Any]
    occurred_at: str = field(default_factory=utc_now)


@dataclass
class CareCase:
    case_id: str
    care_recipient_alias: str
    coordinator_alias: str
    appointment_at: str | None = None
    status: CaseStatus = CaseStatus.ACTIVE
    commitments: dict[str, Commitment] = field(default_factory=dict)
    dependencies: list[Dependency] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    approvals: dict[str, Approval] = field(default_factory=dict)
    ledger: list[LedgerEntry] = field(default_factory=list)

    @property
    def readiness_percent(self) -> int:
        required = [item for item in self.commitments.values() if item.required]
        if not required:
            return 0
        verified = sum(item.state is CommitmentState.VERIFIED for item in required)
        return round(100 * verified / len(required))

    @property
    def pending_approvals(self) -> list[Approval]:
        return [item for item in self.approvals.values() if item.status is ApprovalStatus.PENDING]

    def add_evidence(
        self,
        commitment_id: str,
        kind: EvidenceKind,
        source: str,
        summary: str,
    ) -> Evidence:
        evidence = Evidence(
            evidence_id=f"EV-{uuid4().hex[:8]}",
            commitment_id=commitment_id,
            kind=kind,
            source=source,
            summary=summary,
        )
        self.evidence[evidence.evidence_id] = evidence
        self.commitments[commitment_id].evidence_ids.append(evidence.evidence_id)
        return evidence
