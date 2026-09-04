"""Deterministic state transitions, permissions, and closure gates."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from care_relay.models import (
    Approval,
    ApprovalStatus,
    CareCase,
    CaseStatus,
    Commitment,
    CommitmentKind,
    CommitmentState,
    Dependency,
    EventType,
    EvidenceKind,
    LedgerEntry,
    utc_now,
)


class InvalidTransition(ValueError):
    """Raised when an event would violate a deterministic safety rule."""


def evaluate_case(case: CareCase) -> CaseStatus:
    """Derive status from commitments and approvals; agents cannot override it."""
    required = [item for item in case.commitments.values() if item.required]
    if required and all(item.state is CommitmentState.VERIFIED for item in required):
        case.status = CaseStatus.READY
    elif case.pending_approvals:
        case.status = CaseStatus.DECISION_REQUIRED
    elif any(item.state is CommitmentState.CONFLICTED for item in required):
        case.status = CaseStatus.INVESTIGATING
    elif any(
        item.state in {CommitmentState.BLOCKED, CommitmentState.NEEDS_APPROVAL}
        for item in required
    ):
        case.status = CaseStatus.BLOCKED
    else:
        case.status = CaseStatus.ACTIVE
    return case.status


def apply_event(
    case: CareCase,
    event_type: EventType,
    actor: str,
    details: dict[str, Any],
) -> CareCase:
    """Apply one validated event and append it to the action ledger."""
    handlers: dict[EventType, Callable[[CareCase, dict[str, Any]], None]] = {
        EventType.CASE_OPENED: _case_opened,
        EventType.APPOINTMENT_MOVED: _appointment_moved,
        EventType.FAMILY_TRANSPORT_ACCEPTED: _family_transport_accepted,
        EventType.REFERRAL_REJECTED: _referral_rejected,
        EventType.TRANSMISSION_INSPECTED: _transmission_inspected,
        EventType.APPROVAL_REQUESTED: _approval_requested,
        EventType.APPROVAL_DECIDED: _approval_decided,
        EventType.CORRECTION_SENT: _correction_sent,
        EventType.REFERRAL_CONFIRMED: _referral_confirmed,
        EventType.FOLLOW_UP_RESCHEDULED: _follow_up_rescheduled,
    }
    handlers[event_type](case, details)
    case.ledger.append(
        LedgerEntry(
            entry_id=f"LE-{uuid4().hex[:8]}",
            event_type=event_type,
            actor=actor,
            details=dict(details),
        )
    )
    evaluate_case(case)
    return case


def _require_commitment(case: CareCase, commitment_id: str) -> Commitment:
    try:
        return case.commitments[commitment_id]
    except KeyError as exc:
        raise InvalidTransition(f"Unknown commitment: {commitment_id}") from exc


def invalidate_dependents(case: CareCase, changed_id: str) -> list[str]:
    """Propagate one changed fact through the explicit causal dependency graph."""
    invalidated: list[str] = []
    queue = [changed_id]
    visited = {changed_id}
    while queue:
        source_id = queue.pop(0)
        for edge in case.dependencies:
            if edge.source_id != source_id or edge.target_id in visited:
                continue
            target = _require_commitment(case, edge.target_id)
            target.state = CommitmentState.BLOCKED
            target.blocker = edge.invalidation_reason
            invalidated.append(edge.target_id)
            visited.add(edge.target_id)
            queue.append(edge.target_id)
    return invalidated


def _case_opened(case: CareCase, details: dict[str, Any]) -> None:
    if case.commitments:
        raise InvalidTransition("A case can only be opened once")
    case.appointment_at = details["appointment_at"]
    case.commitments = {
        "appointment": Commitment(
            "appointment", CommitmentKind.APPOINTMENT, "Imaging appointment confirmed",
            state=CommitmentState.VERIFIED, owner="Northside Imaging",
        ),
        "transport": Commitment(
            "transport", CommitmentKind.TRANSPORT, "Transportation accepted",
            state=CommitmentState.CLAIMED, owner=details["transport_owner"],
        ),
        "referral": Commitment(
            "referral", CommitmentKind.REFERRAL, "Valid referral received by imaging",
            state=CommitmentState.CLAIMED, owner="Riverside Orthopedics",
        ),
        "follow_up": Commitment(
            "follow_up", CommitmentKind.FOLLOW_UP, "Follow-up scheduled after imaging",
            state=CommitmentState.VERIFIED, owner="Riverside Orthopedics",
        ),
    }
    case.dependencies = [
        Dependency(
            source_id="appointment",
            target_id="transport",
            relation="acceptance is valid for one appointment time",
            invalidation_reason="Existing acceptance was for the previous appointment time",
        ),
        Dependency(
            source_id="appointment",
            target_id="follow_up",
            relation="follow-up must occur after imaging",
            invalidation_reason="Follow-up now occurs before imaging",
        ),
    ]
    case.add_evidence(
        "appointment", EvidenceKind.VERIFICATION, "Northside Imaging",
        f"Appointment confirmed for {case.appointment_at}",
    )
    case.add_evidence(
        "transport", EvidenceKind.CLAIM, details["transport_owner"],
        "Family member stated they would provide transportation",
    )
    case.add_evidence(
        "referral", EvidenceKind.CLAIM, "Riverside Orthopedics",
        "Clinic stated that the referral was sent",
    )
    case.add_evidence(
        "follow_up", EvidenceKind.VERIFICATION, "care-relay.rules",
        "Follow-up time is after the original imaging appointment",
    )


def _appointment_moved(case: CareCase, details: dict[str, Any]) -> None:
    appointment = _require_commitment(case, "appointment")
    old_time = case.appointment_at
    case.appointment_at = details["new_appointment_at"]
    appointment.state = CommitmentState.VERIFIED
    case.add_evidence(
        "appointment", EvidenceKind.VERIFICATION, details["source"],
        f"Appointment moved from {old_time} to {case.appointment_at}",
    )
    invalidate_dependents(case, "appointment")


def _family_transport_accepted(case: CareCase, details: dict[str, Any]) -> None:
    transport = _require_commitment(case, "transport")
    if transport.state is not CommitmentState.BLOCKED:
        raise InvalidTransition("Replacement transport is only needed for a blocked commitment")
    transport.owner = details["family_member"]
    transport.state = CommitmentState.VERIFIED
    transport.blocker = None
    case.add_evidence(
        "transport", EvidenceKind.VERIFICATION, details["family_member"],
        f"Accepted transportation for {case.appointment_at}",
    )


def _referral_rejected(case: CareCase, details: dict[str, Any]) -> None:
    referral = _require_commitment(case, "referral")
    if referral.state not in {CommitmentState.CLAIMED, CommitmentState.VERIFIED}:
        raise InvalidTransition("Referral rejection does not match the current state")
    referral.state = CommitmentState.CONFLICTED
    referral.blocker = "Sender claims sent; receiving department reports no valid referral"
    case.add_evidence(
        "referral", EvidenceKind.VERIFICATION, details["source"],
        "Receiving imaging department reports no valid referral",
    )


def _transmission_inspected(case: CareCase, details: dict[str, Any]) -> None:
    referral = _require_commitment(case, "referral")
    if referral.state is not CommitmentState.CONFLICTED:
        raise InvalidTransition("Transmission inspection requires a conflicting referral claim")
    if details.get("destination") == details.get("required_destination"):
        raise InvalidTransition("The inspected transmission does not explain the conflict")
    referral.state = CommitmentState.BLOCKED
    referral.blocker = "Referral was sent to the wrong department"
    case.add_evidence(
        "referral", EvidenceKind.FACT, details["source"],
        f"Sent to {details['destination']}; required {details['required_destination']}",
    )


def _approval_requested(case: CareCase, details: dict[str, Any]) -> None:
    referral = _require_commitment(case, "referral")
    if referral.state is not CommitmentState.BLOCKED:
        raise InvalidTransition("A correction can only be proposed for a blocked referral")
    approval_id = details["approval_id"]
    if approval_id in case.approvals:
        raise InvalidTransition("Approval identifiers must be unique")
    case.approvals[approval_id] = Approval(
        approval_id=approval_id,
        action="send_referral_correction",
        recipient=details["recipient"],
        reason=details["reason"],
        disclosure=tuple(details["disclosure"]),
        requested_by=details["requested_by"],
    )
    referral.state = CommitmentState.NEEDS_APPROVAL


def _approval_decided(case: CareCase, details: dict[str, Any]) -> None:
    try:
        approval = case.approvals[details["approval_id"]]
    except KeyError as exc:
        raise InvalidTransition("Unknown approval request") from exc
    if approval.status is not ApprovalStatus.PENDING:
        raise InvalidTransition("Approval has already been decided")
    approval.status = ApprovalStatus.APPROVED if details["approved"] else ApprovalStatus.REJECTED
    approval.decided_by = details["decided_by"]
    approval.decided_at = utc_now()
    if not details["approved"]:
        referral = _require_commitment(case, "referral")
        referral.state = CommitmentState.BLOCKED
        referral.blocker = "Caregiver rejected the proposed correction"


def _correction_sent(case: CareCase, details: dict[str, Any]) -> None:
    referral = _require_commitment(case, "referral")
    try:
        approval = case.approvals[details["approval_id"]]
    except KeyError as exc:
        raise InvalidTransition("Protected action requires an approval") from exc
    if approval.status is not ApprovalStatus.APPROVED:
        raise InvalidTransition("Protected action requires an unused approved decision")
    if approval.action != "send_referral_correction" or approval.recipient != details["recipient"]:
        raise InvalidTransition("Approval scope does not match the protected action")
    approval.status = ApprovalStatus.CONSUMED
    referral.state = CommitmentState.CLAIMED
    referral.blocker = "Awaiting confirmation from the receiving department"
    case.add_evidence(
        "referral", EvidenceKind.CLAIM, details["source"],
        "Corrected referral was transmitted to imaging",
    )


def _referral_confirmed(case: CareCase, details: dict[str, Any]) -> None:
    referral = _require_commitment(case, "referral")
    if referral.state is not CommitmentState.CLAIMED:
        raise InvalidTransition("Recipient confirmation requires a transmitted referral")
    referral.state = CommitmentState.VERIFIED
    referral.blocker = None
    case.add_evidence(
        "referral", EvidenceKind.VERIFICATION, details["source"],
        "Imaging department confirmed receipt and acceptance of the valid referral",
    )


def _follow_up_rescheduled(case: CareCase, details: dict[str, Any]) -> None:
    follow_up = _require_commitment(case, "follow_up")
    if follow_up.state is not CommitmentState.BLOCKED:
        raise InvalidTransition("Follow-up does not currently need rescheduling")
    if details["after_appointment"] is not True:
        raise InvalidTransition("Follow-up must occur after the imaging appointment")
    follow_up.state = CommitmentState.VERIFIED
    follow_up.blocker = None
    case.add_evidence(
        "follow_up", EvidenceKind.VERIFICATION, details["source"],
        f"Follow-up rescheduled for {details['follow_up_at']}",
    )
