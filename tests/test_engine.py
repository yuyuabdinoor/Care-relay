"""Tests for Care Relay's deterministic safety and closure engine."""

import pytest

from care_relay.demo import build_demo_case, run_demo
from care_relay.engine import InvalidTransition, apply_event
from care_relay.models import ApprovalStatus, CaseStatus, CommitmentState, EventType
from care_relay.tools import CareRelayTools


def opened_case():
    case = build_demo_case()
    apply_event(
        case,
        EventType.CASE_OPENED,
        "test",
        {
            "appointment_at": "2026-09-10T10:00:00-04:00",
            "transport_owner": "Marcus",
        },
    )
    return case


def move_and_find_referral_failure(case):
    apply_event(
        case,
        EventType.APPOINTMENT_MOVED,
        "test",
        {
            "new_appointment_at": "2026-09-11T14:30:00-04:00",
            "source": "MSG-1",
        },
    )
    apply_event(case, EventType.REFERRAL_REJECTED, "test", {"source": "Imaging"})
    apply_event(
        case,
        EventType.TRANSMISSION_INSPECTED,
        "test",
        {
            "source": "TX-1",
            "destination": "General Records",
            "required_destination": "Imaging",
        },
    )


def test_demo_closes_only_after_every_commitment_is_verified():
    case = run_demo()
    assert case.status is CaseStatus.READY
    assert case.readiness_percent == 100
    assert len(case.ledger) == 10
    assert all(
        item.state is CommitmentState.VERIFIED
        for item in case.commitments.values()
        if item.required
    )


def test_appointment_change_invalidates_dependent_commitments():
    case = opened_case()
    apply_event(
        case,
        EventType.APPOINTMENT_MOVED,
        "test",
        {
            "new_appointment_at": "2026-09-11T14:30:00-04:00",
            "source": "MSG-1",
        },
    )
    assert case.commitments["appointment"].state is CommitmentState.VERIFIED
    assert case.commitments["transport"].state is CommitmentState.BLOCKED
    assert case.commitments["follow_up"].state is CommitmentState.BLOCKED
    assert case.status is CaseStatus.BLOCKED
    assert {
        (edge.source_id, edge.target_id)
        for edge in case.dependencies
    } == {("appointment", "transport"), ("appointment", "follow_up")}


def test_sender_claim_does_not_verify_referral():
    case = opened_case()
    assert case.commitments["referral"].state is CommitmentState.CLAIMED
    assert case.readiness_percent == 50


def test_protected_action_requires_approval():
    case = opened_case()
    move_and_find_referral_failure(case)
    with pytest.raises(InvalidTransition, match="requires an approval"):
        apply_event(
            case,
            EventType.CORRECTION_SENT,
            "agent",
            {"approval_id": "missing", "recipient": "Imaging", "source": "TX-2"},
        )


def test_approval_is_scoped_to_recipient_and_single_use():
    case = opened_case()
    move_and_find_referral_failure(case)
    apply_event(
        case,
        EventType.APPROVAL_REQUESTED,
        "agent",
        {
            "approval_id": "APR-1",
            "recipient": "Imaging",
            "reason": "Correct handoff",
            "disclosure": ["referral number"],
            "requested_by": "agent",
        },
    )
    apply_event(
        case,
        EventType.APPROVAL_DECIDED,
        "Aisha",
        {"approval_id": "APR-1", "approved": True, "decided_by": "Aisha"},
    )
    with pytest.raises(InvalidTransition, match="scope does not match"):
        apply_event(
            case,
            EventType.CORRECTION_SENT,
            "agent",
            {"approval_id": "APR-1", "recipient": "Different Clinic", "source": "TX-2"},
        )
    apply_event(
        case,
        EventType.CORRECTION_SENT,
        "agent",
        {"approval_id": "APR-1", "recipient": "Imaging", "source": "TX-2"},
    )
    assert case.approvals["APR-1"].status is ApprovalStatus.CONSUMED
    with pytest.raises(InvalidTransition, match="unused approved"):
        apply_event(
            case,
            EventType.CORRECTION_SENT,
            "agent",
            {"approval_id": "APR-1", "recipient": "Imaging", "source": "TX-3"},
        )


def test_rejected_approval_keeps_referral_blocked():
    case = opened_case()
    move_and_find_referral_failure(case)
    apply_event(
        case,
        EventType.APPROVAL_REQUESTED,
        "agent",
        {
            "approval_id": "APR-1",
            "recipient": "Imaging",
            "reason": "Correct handoff",
            "disclosure": ["referral number"],
            "requested_by": "agent",
        },
    )
    apply_event(
        case,
        EventType.APPROVAL_DECIDED,
        "Aisha",
        {"approval_id": "APR-1", "approved": False, "decided_by": "Aisha"},
    )
    assert case.commitments["referral"].state is CommitmentState.BLOCKED
    assert case.status is CaseStatus.BLOCKED


def test_agent_tool_sequence_discovers_hidden_failure_and_recovers():
    case = opened_case()
    apply_event(
        case,
        EventType.APPOINTMENT_MOVED,
        "inbox",
        {
            "new_appointment_at": "2026-09-11T14:30:00-04:00",
            "source": "MSG-1",
        },
    )
    tools = CareRelayTools(case)

    assert tools.check_family_availability("Marcus", case.appointment_at)["available"] is False
    assert tools.check_family_availability("Elena", case.appointment_at)["available"] is True
    assert tools.request_family_transport("Elena")["accepted"] is True
    assert tools.check_referral_receipt()["accepted"] is False
    assert tools.inspect_transmission("TX-8841")["destination"] == "Northside General Records"

    approval = tools.propose_referral_correction()
    assert case.status is CaseStatus.DECISION_REQUIRED
    tools.record_approval(approval["approval_id"], approved=True, decided_by="Aisha")
    tools.send_referral_correction(approval["approval_id"])
    assert tools.verify_corrected_referral()["accepted"] is True
    tools.reschedule_follow_up("2026-09-15T11:00:00-04:00")

    assert case.status is CaseStatus.READY
    assert case.readiness_percent == 100
    assert len(tools.world.sent_messages) == 1

    ledger_size = len(case.ledger)
    assert tools.request_family_transport("Elena")["already_confirmed"] is True
    assert tools.inspect_transmission("TX-8841")["already_inspected"] is True
    assert tools.propose_referral_correction()["already_exists"] is True
    assert tools.record_approval(
        approval["approval_id"], approved=True, decided_by="Aisha"
    )["already_recorded"] is True
    assert tools.send_referral_correction(approval["approval_id"])["already_sent"] is True
    assert tools.verify_corrected_referral()["already_confirmed"] is True
    assert tools.reschedule_follow_up("2026-09-15T11:00:00-04:00")[
        "already_scheduled"
    ] is True
    assert len(case.ledger) == ledger_size
    assert len(tools.world.sent_messages) == 1


def test_appointment_change_tool_requires_timezone_and_propagates():
    case = opened_case()
    tools = CareRelayTools(case)

    with pytest.raises(ValueError, match="timezone"):
        tools.record_appointment_change("2026-09-11T14:30:00", "MSG-1")

    with pytest.raises(ValueError, match="retain the existing appointment year"):
        tools.record_appointment_change("2025-09-11T14:30:00-04:00", "MSG-1")

    with pytest.raises(ValueError, match="retain the existing UTC offset"):
        tools.record_appointment_change("2026-09-11T14:30:00-05:00", "MSG-1")

    result = tools.record_appointment_change(
        "2026-09-11T14:30:00-04:00",
        "MSG-1",
    )
    assert result["invalidated"] == ["transport", "follow_up"]
    assert case.commitments["transport"].state is CommitmentState.BLOCKED


def test_agents_must_choose_discoverable_people_and_calendar_slots():
    case = opened_case()
    apply_event(
        case,
        EventType.APPOINTMENT_MOVED,
        "test",
        {
            "new_appointment_at": "2026-09-11T14:30:00-04:00",
            "source": "MSG-1",
        },
    )
    tools = CareRelayTools(case)

    assert tools.list_approved_family_members() == {"family_members": ["Elena", "Marcus"]}
    assert tools.get_available_follow_up_slots()["slots"] == ["2026-09-15T11:00:00-04:00"]
    rejected = tools.reschedule_follow_up("2026-09-12T10:00:00-04:00")
    assert rejected["rescheduled"] is False
    assert case.commitments["follow_up"].state is CommitmentState.BLOCKED
