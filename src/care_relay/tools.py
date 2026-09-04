"""Synthetic counterparty tools exposed to Care Relay agents.

The hackathon demo uses these deterministic adapters in place of real calendars,
provider portals, and messaging systems. Agent prompts do not contain the hidden
answers; agents must call tools to discover them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any

from care_relay.engine import apply_event
from care_relay.models import ApprovalStatus, CareCase, CommitmentState, EventType
from care_relay.policy import PolicyContext, PolicyDecision, evaluate_action


@dataclass
class SyntheticWorld:
    """Hidden external state for the Daniel imaging scenario."""

    family_availability: dict[str, set[str]] = field(
        default_factory=lambda: {
            "Marcus": {"2026-09-10T10:00:00-04:00"},
            "Elena": {"2026-09-11T14:30:00-04:00"},
        }
    )
    referral_transmissions: dict[str, dict[str, str]] = field(
        default_factory=lambda: {
            "TX-8841": {
                "destination": "Northside General Records",
                "required_destination": "Northside Imaging Department",
                "status": "delivered",
            }
        }
    )
    imaging_has_valid_referral: bool = False
    sent_messages: list[dict[str, Any]] = field(default_factory=list)


class CareRelayTools:
    """Controlled tool boundary between agents and deterministic state."""

    def __init__(
        self,
        case: CareCase,
        world: SyntheticWorld | None = None,
        policy_context: PolicyContext | None = None,
        state_lock: RLock | None = None,
    ) -> None:
        self.case = case
        self.world = world or SyntheticWorld()
        self.policy_context = policy_context or PolicyContext()
        self.state_lock = state_lock

    def get_case_snapshot(self) -> dict[str, Any]:
        """Return current administrative case state without hidden world state."""
        return {
            "case_id": self.case.case_id,
            "care_recipient": self.case.care_recipient_alias,
            "coordinator": self.case.coordinator_alias,
            "appointment_at": self.case.appointment_at,
            "status": self.case.status.value,
            "readiness_percent": self.case.readiness_percent,
            "commitments": {
                key: {
                    "kind": item.kind.value,
                    "label": item.label,
                    "state": item.state.value,
                    "owner": item.owner,
                    "blocker": item.blocker,
                }
                for key, item in self.case.commitments.items()
            },
            "pending_approvals": [asdict(item) for item in self.case.pending_approvals],
        }

    def record_appointment_change(
        self,
        new_appointment_at: str,
        source: str,
    ) -> dict[str, Any]:
        """Validate and record an explicitly stated appointment-time change."""
        try:
            parsed = datetime.fromisoformat(new_appointment_at)
        except ValueError as exc:
            raise ValueError("Appointment time must be valid ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("Appointment time must include a timezone offset")
        if self.case.appointment_at is None:
            raise ValueError("The case has no existing appointment to update")
        previous_parsed = datetime.fromisoformat(self.case.appointment_at)
        if parsed.year != previous_parsed.year:
            raise ValueError(
                "A yearless schedule update must retain the existing appointment year"
            )
        if parsed.utcoffset() != previous_parsed.utcoffset():
            raise ValueError(
                "A timezone-abbreviated update must retain the existing UTC offset"
            )
        if abs((parsed - previous_parsed).total_seconds()) > 31 * 86400:
            raise ValueError("Appointment change is outside the allowed 31-day update window")
        if new_appointment_at == self.case.appointment_at:
            return {"changed": False, "reason": "Appointment time is unchanged"}
        previous = self.case.appointment_at
        apply_event(
            self.case,
            EventType.APPOINTMENT_MOVED,
            "care-relay.coordinator",
            {"new_appointment_at": new_appointment_at, "source": source},
        )
        return {
            "changed": True,
            "previous_appointment_at": previous,
            "new_appointment_at": new_appointment_at,
            "invalidated": ["transport", "follow_up"],
        }

    def list_approved_family_members(self) -> dict[str, Any]:
        """Return aliases the caregiver preapproved for routine transport requests."""
        return {"family_members": sorted(self.policy_context.approved_family)}

    def check_family_availability(self, family_member: str, appointment_at: str) -> dict[str, Any]:
        """Check whether an approved family member is available for a visit time."""
        available = appointment_at in self.world.family_availability.get(family_member, set())
        return {
            "family_member": family_member,
            "appointment_at": appointment_at,
            "available": available,
        }

    def request_family_transport(self, family_member: str) -> dict[str, Any]:
        """Ask an approved family member to accept transport for the current appointment."""
        policy = evaluate_action(
            "request_family_transport",
            context=self.policy_context,
            parameters={"family_member": family_member},
        )
        if policy.decision is PolicyDecision.DENIED:
            return {
                "accepted": False,
                "reason": policy.reason,
                "policy": asdict(policy),
            }
        appointment_at = self.case.appointment_at
        if appointment_at is None:
            return {"accepted": False, "reason": "No appointment is scheduled"}
        available = appointment_at in self.world.family_availability.get(family_member, set())
        if not available:
            return {"accepted": False, "family_member": family_member, "reason": "Unavailable"}
        transport = self.case.commitments["transport"]
        if transport.state is CommitmentState.VERIFIED and transport.owner == family_member:
            return {
                "accepted": True,
                "family_member": family_member,
                "appointment_at": appointment_at,
                "already_confirmed": True,
            }
        apply_event(
            self.case,
            EventType.FAMILY_TRANSPORT_ACCEPTED,
            family_member,
            {"family_member": family_member},
        )
        return {
            "accepted": True,
            "family_member": family_member,
            "appointment_at": appointment_at,
            "policy": asdict(policy),
        }

    def check_referral_receipt(self) -> dict[str, Any]:
        """Ask the receiving imaging department whether it has a valid referral."""
        if self.world.imaging_has_valid_referral:
            return {
                "received": True,
                "accepted": True,
                "source": "Northside Imaging Department",
            }
        referral = self.case.commitments["referral"]
        if referral.state in {CommitmentState.CLAIMED, CommitmentState.VERIFIED}:
            apply_event(
                self.case,
                EventType.REFERRAL_REJECTED,
                "care-relay.verifier",
                {"source": "Northside Imaging Department"},
            )
        return {
            "received": False,
            "accepted": False,
            "source": "Northside Imaging Department",
            "reason": "No valid referral found for this appointment",
            "claimed_transmission_id": "TX-8841",
        }

    def get_available_follow_up_slots(self) -> dict[str, Any]:
        """Return synthetic provider-calendar slots after the current appointment."""
        appointment = datetime.fromisoformat(self.case.appointment_at or "")
        slots = ["2026-09-15T11:00:00-04:00"]
        return {
            "provider": "Riverside Orthopedics",
            "slots": [slot for slot in slots if datetime.fromisoformat(slot) > appointment],
        }

    def inspect_transmission(self, transmission_id: str) -> dict[str, Any]:
        """Inspect the clinic's delivery receipt for a claimed referral transmission."""
        record = self.world.referral_transmissions.get(transmission_id)
        if record is None:
            return {"found": False, "transmission_id": transmission_id}
        already_inspected = any(
            evidence.source == transmission_id for evidence in self.case.evidence.values()
        )
        if not already_inspected:
            apply_event(
                self.case,
                EventType.TRANSMISSION_INSPECTED,
                "care-relay.coordinator",
                {
                    "source": transmission_id,
                    "destination": record["destination"],
                    "required_destination": record["required_destination"],
                },
            )
        return {
            "found": True,
            "transmission_id": transmission_id,
            "already_inspected": already_inspected,
            **record,
        }

    def propose_referral_correction(self, approval_id: str = "APR-1001") -> dict[str, Any]:
        """Create a human decision for the protected referral correction action."""
        existing = self.case.approvals.get(approval_id)
        if existing is None and self.case.pending_approvals:
            existing = self.case.pending_approvals[0]
        if existing is not None:
            return {
                "approval_id": existing.approval_id,
                "status": existing.status.value,
                "recipient": existing.recipient,
                "disclosure": list(existing.disclosure),
                "already_exists": True,
            }
        apply_event(
            self.case,
            EventType.APPROVAL_REQUESTED,
            "care-relay.coordinator",
            {
                "approval_id": approval_id,
                "recipient": "Northside Imaging Department",
                "reason": "Correct the failed referral handoff",
                "disclosure": ["referral number", "appointment identifier"],
                "requested_by": "care-relay.coordinator",
            },
        )
        return {
            "approval_id": approval_id,
            "status": "pending",
            "recipient": "Northside Imaging Department",
            "disclosure": ["referral number", "appointment identifier"],
        }

    def record_approval(self, approval_id: str, approved: bool, decided_by: str) -> dict[str, Any]:
        """Record the caregiver's explicit decision; the agent cannot call this for itself."""
        existing = self.case.approvals.get(approval_id)
        if existing is not None and existing.status is not ApprovalStatus.PENDING:
            was_approved = existing.status in {ApprovalStatus.APPROVED, ApprovalStatus.CONSUMED}
            if was_approved != approved:
                raise ValueError("Recorded approval decision cannot be changed")
            return {
                "approval_id": approval_id,
                "approved": approved,
                "decided_by": existing.decided_by,
                "already_recorded": True,
            }
        apply_event(
            self.case,
            EventType.APPROVAL_DECIDED,
            decided_by,
            {"approval_id": approval_id, "approved": approved, "decided_by": decided_by},
        )
        return {"approval_id": approval_id, "approved": approved, "decided_by": decided_by}

    def send_referral_correction(self, approval_id: str) -> dict[str, Any]:
        """Send the correction only when a matching unused approval exists."""
        policy = evaluate_action(
            "send_referral_correction",
            context=self.policy_context,
            parameters={"approval_id": approval_id},
        )
        transmission_id = "TX-8842"
        recipient = "Northside Imaging Department"
        already_sent = next(
            (
                message
                for message in self.world.sent_messages
                if message.get("approval_id") == approval_id
                and message.get("message_type") == "referral_correction"
            ),
            None,
        )
        if already_sent is not None:
            return {
                "sent": True,
                "recipient": recipient,
                "transmission_id": already_sent["transmission_id"],
                "already_sent": True,
            }
        apply_event(
            self.case,
            EventType.CORRECTION_SENT,
            "care-relay.provider-tool",
            {
                "approval_id": approval_id,
                "recipient": recipient,
                "source": transmission_id,
            },
        )
        self.world.sent_messages.append(
            {
                "message_type": "referral_correction",
                "recipient": recipient,
                "approval_id": approval_id,
                "transmission_id": transmission_id,
            }
        )
        self.world.imaging_has_valid_referral = True
        return {
            "sent": True,
            "recipient": recipient,
            "transmission_id": transmission_id,
            "policy": asdict(policy),
        }

    def verify_corrected_referral(self) -> dict[str, Any]:
        """Independently confirm whether imaging accepted the corrected referral."""
        if not self.world.imaging_has_valid_referral:
            return {"received": False, "accepted": False}
        referral = self.case.commitments["referral"]
        already_confirmed = referral.state is CommitmentState.VERIFIED
        if not already_confirmed:
            apply_event(
                self.case,
                EventType.REFERRAL_CONFIRMED,
                "care-relay.verifier",
                {"source": "Northside Imaging Department"},
            )
        return {
            "received": True,
            "accepted": True,
            "source": "Northside Imaging Department",
            "already_confirmed": already_confirmed,
        }

    def reschedule_follow_up(self, follow_up_at: str) -> dict[str, Any]:
        """Apply the synthetic scheduling system's deterministic date-order check."""
        policy = evaluate_action(
            "reschedule_follow_up",
            context=self.policy_context,
            parameters={
                "appointment_at": self.case.appointment_at,
                "follow_up_at": follow_up_at,
                "recipient": "Riverside Orthopedics",
            },
        )
        if policy.decision is not PolicyDecision.AUTONOMOUS:
            return {
                "rescheduled": False,
                "reason": policy.reason,
                "policy": asdict(policy),
            }
        available_slots = self.get_available_follow_up_slots()["slots"]
        if follow_up_at not in available_slots:
            return {
                "rescheduled": False,
                "reason": "The selected time is not an available provider-calendar slot",
                "available_slots": available_slots,
                "policy": asdict(policy),
            }
        if self.case.commitments["follow_up"].state is CommitmentState.VERIFIED:
            return {"rescheduled": True, "follow_up_at": follow_up_at, "already_scheduled": True}
        after_appointment = self.case.appointment_at is not None and follow_up_at > self.case.appointment_at
        apply_event(
            self.case,
            EventType.FOLLOW_UP_RESCHEDULED,
            "care-relay.calendar-tool",
            {
                "follow_up_at": follow_up_at,
                "after_appointment": after_appointment,
                "source": "Riverside Orthopedics",
            },
        )
        return {"rescheduled": True, "follow_up_at": follow_up_at, "policy": asdict(policy)}
