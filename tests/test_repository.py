from care_relay.demo import build_demo_case
from care_relay.engine import apply_event
from care_relay.models import CommitmentState, EventType
from care_relay.repository import CaseRepository
from care_relay.tools import SyntheticWorld


def test_case_repository_round_trips_graph_evidence_and_world(tmp_path):
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
    world = SyntheticWorld()
    world.sent_messages.append({"message_type": "test"})
    world.calendar_updates.append({"backend": "google", "event_id": "event-1"})
    repository = CaseRepository(tmp_path / "care-relay.db")

    repository.save(
        case,
        world,
        stage=1,
        agent_session_id="care-relay-test-run",
        activity=[{"agent": "Coordinator", "kind": "replanned", "message": "Changed"}],
        external_events=[{"source": "Imaging", "message": "Moved"}],
        traces=[
            {
                "sequence": 1,
                "timestamp": "2026-09-01T00:00:00+00:00",
                "agent": "Coordinator",
                "event": "tool_selected",
                "summary": "Selected a tool",
                "details": {"tool": "test"},
            }
        ],
    )
    restored = repository.load(case.case_id)

    assert restored is not None
    assert restored["case"].appointment_at == "2026-09-11T14:30:00-04:00"
    assert restored["case"].commitments["transport"].state is CommitmentState.BLOCKED
    assert restored["case"].dependencies[0].source_id == "appointment"
    assert len(restored["case"].ledger) == 2
    assert restored["world"].sent_messages == [{"message_type": "test"}]
    assert restored["world"].calendar_updates == [
        {"backend": "google", "event_id": "event-1"}
    ]
    assert restored["stage"] == 1
    assert restored["agent_session_id"] == "care-relay-test-run"
    assert restored["traces"][0]["event"] == "tool_selected"
    assert stat.S_IMODE(repository.path.stat().st_mode) == 0o600
import stat
