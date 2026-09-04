"""Deterministic autonomy and permission policy for agent-proposed actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class PolicyDecision(str, Enum):
    AUTONOMOUS = "autonomous"
    APPROVAL_REQUIRED = "approval_required"
    DENIED = "denied"


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    reason: str
    rule_id: str


@dataclass
class PolicyContext:
    """Standing permissions configured by the synthetic caregiver."""

    approved_family: set[str] = field(default_factory=lambda: {"Marcus", "Elena"})
    approved_providers: set[str] = field(
        default_factory=lambda: {"Northside Imaging Department", "Riverside Orthopedics"}
    )
    follow_up_window_days: int = 7


READ_ONLY_ACTIONS = {
    "get_case_snapshot",
    "check_family_availability",
    "check_referral_receipt",
    "inspect_transmission",
    "verify_corrected_referral",
}

DENIED_ACTIONS = {
    "diagnose_condition",
    "recommend_treatment",
    "change_medication",
    "determine_medical_urgency",
}


def evaluate_action(
    action: str,
    *,
    context: PolicyContext,
    parameters: dict[str, Any] | None = None,
) -> PolicyResult:
    """Return a deterministic decision; models cannot override this result."""
    parameters = parameters or {}
    if action in DENIED_ACTIONS:
        return PolicyResult(
            PolicyDecision.DENIED,
            "Clinical judgment is outside Care Relay's administrative scope",
            "scope.clinical-deny",
        )
    if action in READ_ONLY_ACTIONS:
        return PolicyResult(
            PolicyDecision.AUTONOMOUS,
            "Read-only administrative check",
            "autonomy.read-only",
        )
    if action == "record_appointment_change":
        return PolicyResult(
            PolicyDecision.AUTONOMOUS,
            "Recording a provider-originated fact does not create an external commitment",
            "autonomy.record-fact",
        )
    if action == "request_family_transport":
        family_member = parameters.get("family_member")
        if family_member not in context.approved_family:
            return PolicyResult(
                PolicyDecision.DENIED,
                "The family member is not on the caregiver's approved coordination list",
                "scope.family-allowlist",
            )
        return PolicyResult(
            PolicyDecision.AUTONOMOUS,
            "Caregiver preauthorized routine transport requests to approved family",
            "autonomy.family-transport",
        )
    if action == "send_referral_correction":
        return PolicyResult(
            PolicyDecision.APPROVAL_REQUIRED,
            "The action discloses visit identifiers to an external recipient",
            "approval.external-disclosure",
        )
    if action == "reschedule_follow_up":
        try:
            appointment = datetime.fromisoformat(parameters["appointment_at"])
            follow_up = datetime.fromisoformat(parameters["follow_up_at"])
        except (KeyError, ValueError):
            return PolicyResult(
                PolicyDecision.DENIED,
                "Scheduling policy requires valid timezone-aware appointment dates",
                "scope.valid-dates",
            )
        delta_days = (follow_up - appointment).total_seconds() / 86400
        recipient = parameters.get("recipient")
        if (
            appointment.tzinfo is not None
            and follow_up.tzinfo is not None
            and recipient in context.approved_providers
            and 0 < delta_days <= context.follow_up_window_days
        ):
            return PolicyResult(
                PolicyDecision.AUTONOMOUS,
                "Standing permission allows same-provider follow-up within seven days",
                "autonomy.follow-up-window",
            )
        return PolicyResult(
            PolicyDecision.APPROVAL_REQUIRED,
            "The proposed follow-up falls outside the caregiver's standing permission",
            "approval.follow-up-exception",
        )
    return PolicyResult(
        PolicyDecision.APPROVAL_REQUIRED,
        "No standing permission covers this action",
        "approval.default-deny",
    )
