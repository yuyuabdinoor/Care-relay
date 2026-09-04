from care_relay.demo import build_demo_case
from care_relay.engine import apply_event
from care_relay.models import CommitmentState, EventType
from care_relay.policy import PolicyContext, PolicyDecision, evaluate_action
from care_relay.tools import CareRelayTools


def moved_case():
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
    apply_event(
        case,
        EventType.APPOINTMENT_MOVED,
        "test",
        {
            "new_appointment_at": "2026-09-11T14:30:00-04:00",
            "source": "MSG-1",
        },
    )
    return case


def test_policy_denies_clinical_judgment_and_unknown_family():
    context = PolicyContext()
    clinical = evaluate_action("change_medication", context=context)
    unknown_family = evaluate_action(
        "request_family_transport",
        context=context,
        parameters={"family_member": "Unknown Person"},
    )

    assert clinical.decision is PolicyDecision.DENIED
    assert unknown_family.decision is PolicyDecision.DENIED


def test_follow_up_is_autonomous_only_inside_standing_permission():
    case = moved_case()
    tools = CareRelayTools(case)

    allowed = tools.reschedule_follow_up("2026-09-15T11:00:00-04:00")
    assert allowed["rescheduled"] is True
    assert allowed["policy"]["rule_id"] == "autonomy.follow-up-window"

    case = moved_case()
    tools = CareRelayTools(case)
    outside_window = tools.reschedule_follow_up("2026-10-15T11:00:00-04:00")
    assert outside_window["rescheduled"] is False
    assert outside_window["policy"]["decision"] is PolicyDecision.APPROVAL_REQUIRED
    assert case.commitments["follow_up"].state is CommitmentState.BLOCKED


def test_unknown_family_request_has_no_side_effect():
    case = moved_case()
    tools = CareRelayTools(case)
    ledger_size = len(case.ledger)

    result = tools.request_family_transport("Unknown Person")

    assert result["accepted"] is False
    assert result["policy"]["decision"] is PolicyDecision.DENIED
    assert len(case.ledger) == ledger_size
