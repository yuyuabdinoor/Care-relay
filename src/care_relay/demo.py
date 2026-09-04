"""Synthetic case fixtures used by the Care Relay engine and tests."""

from care_relay.engine import apply_event
from care_relay.models import CareCase, EventType


def build_demo_case() -> CareCase:
    return CareCase(
        case_id="VISIT-1042",
        care_recipient_alias="Daniel",
        coordinator_alias="Aisha",
    )


def run_demo() -> CareCase:
    case = build_demo_case()
    events = [
        (
            EventType.CASE_OPENED,
            "care-relay.intake",
            {
                "appointment_at": "2026-09-10T10:00:00-04:00",
                "transport_owner": "Marcus",
            },
        ),
        (
            EventType.APPOINTMENT_MOVED,
            "northside-imaging.inbox",
            {
                "new_appointment_at": "2026-09-11T14:30:00-04:00",
                "source": "MSG-APPT-002",
            },
        ),
        (
            EventType.FAMILY_TRANSPORT_ACCEPTED,
            "Elena",
            {"family_member": "Elena"},
        ),
        (
            EventType.REFERRAL_REJECTED,
            "care-relay.verifier",
            {"source": "Northside Imaging Department"},
        ),
        (
            EventType.TRANSMISSION_INSPECTED,
            "care-relay.coordinator",
            {
                "source": "TX-8841",
                "destination": "Northside General Records",
                "required_destination": "Northside Imaging Department",
            },
        ),
        (
            EventType.APPROVAL_REQUESTED,
            "care-relay.coordinator",
            {
                "approval_id": "APR-1001",
                "recipient": "Northside Imaging Department",
                "reason": "Correct the failed referral handoff",
                "disclosure": ["referral number", "appointment identifier"],
                "requested_by": "care-relay.coordinator",
            },
        ),
        (
            EventType.APPROVAL_DECIDED,
            "Aisha",
            {"approval_id": "APR-1001", "approved": True, "decided_by": "Aisha"},
        ),
        (
            EventType.CORRECTION_SENT,
            "care-relay.provider-tool",
            {
                "approval_id": "APR-1001",
                "recipient": "Northside Imaging Department",
                "source": "TX-8842",
            },
        ),
        (
            EventType.REFERRAL_CONFIRMED,
            "care-relay.verifier",
            {"source": "Northside Imaging Department"},
        ),
        (
            EventType.FOLLOW_UP_RESCHEDULED,
            "care-relay.calendar-tool",
            {
                "follow_up_at": "2026-09-15T11:00:00-04:00",
                "after_appointment": True,
                "source": "Riverside Orthopedics",
            },
        ),
    ]
    for event_type, actor, details in events:
        apply_event(case, event_type, actor, details)
    return case
