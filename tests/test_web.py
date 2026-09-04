import time
from threading import Event

from fastapi.testclient import TestClient

from care_relay.repository import CaseRepository
from care_relay.web import AgentDecision, Decision, DemoSession, ExternalMessage, app


def test_dashboard_exposes_live_agent_path_only():
    client = TestClient(app)
    state = client.post("/api/demo/reset").json()
    assert state["case"]["readiness"] == 50
    assert len(state["dependencies"]) == 2
    assert state["can_process_event"] is True

    assert "can_advance" not in state
    assert client.post("/api/demo/advance").status_code == 404
    assert client.post("/api/approvals/APR-1001", json={"approved": True}).status_code == 404


def test_demo_session_restores_case_after_process_restart(tmp_path):
    repository = CaseRepository(tmp_path / "dashboard.db")
    first = DemoSession(repository)
    first.advance()

    restored = DemoSession(repository)
    snapshot = restored.snapshot()

    assert snapshot["stage"] == 1
    assert snapshot["external_events"][0]["subject"] == "Appointment time updated"
    assert {item["id"] for item in snapshot["commitments"] if item["state"] == "blocked"} == {
        "transport",
        "follow_up",
    }


def test_agentcore_health_and_status_contract():
    client = TestClient(app)

    assert client.get("/ping").json() == {"status": "Healthy"}
    response = client.post("/invocations", json={"input": {"action": "status"}})

    assert response.status_code == 200
    assert response.json()["result"]["case"]["id"] == "VISIT-1042"


def test_agentcore_contract_rejects_unknown_action():
    client = TestClient(app)
    response = client.post("/invocations", json={"input": {"action": "erase_everything"}})

    assert response.status_code == 409
    assert "Unsupported runtime action" in response.json()["detail"]


def test_agentcore_contract_does_not_coerce_approval_strings():
    client = TestClient(app)
    response = client.post(
        "/invocations",
        json={
            "input": {
                "action": "approve",
                "approval_id": "APR-1",
                "approved": "false",
            }
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "approved must be a JSON boolean"


def test_repeated_matching_resume_is_idempotent_after_completion(tmp_path):
    session = DemoSession(CaseRepository(tmp_path / "dashboard.db"))
    session.advance()
    session.advance()
    session.advance()
    session.advance()
    session.advance()
    session.decide("APR-1001", Decision(approved=True))
    session.agent_run = type("CompletedRun", (), {})()

    session.resume_agent_run(
        AgentDecision(approval_id="APR-1001", approved=True, decided_by="Aisha")
    )


def test_declined_correction_stays_blocked_and_is_never_sent(tmp_path):
    session = DemoSession(CaseRepository(tmp_path / "dashboard.db"))
    for _ in range(5):
        session.advance()

    session.decide("APR-1001", Decision(approved=False))
    snapshot = session.snapshot()
    referral = next(
        item for item in snapshot["commitments"] if item["id"] == "referral"
    )

    assert snapshot["case"]["readiness"] < 100
    assert snapshot["case"]["status"] != "ready"
    assert referral["state"] == "blocked"
    assert referral["blocker"] == "Caregiver rejected the proposed correction"
    assert session.case.approvals["APR-1001"].status.value == "rejected"
    assert not any(
        item["message_type"] == "referral_correction"
        for item in session.tools.world.sent_messages
    )


def test_background_agent_run_returns_immediately_and_exposes_running_state(
    tmp_path, monkeypatch
):
    started = Event()
    release = Event()

    class Collector:
        def snapshot(self):
            return []

    class BackgroundRun:
        def __init__(self, *args, **kwargs):
            self.trace_collector = Collector()

        def start_from_external_message(self, **kwargs):
            started.set()
            release.wait(timeout=1)

        def status(self):
            return {"state": "completed", "interrupts": []}

    monkeypatch.setattr("care_relay.web.AgentRun", BackgroundRun)
    dashboard = DemoSession(CaseRepository(tmp_path / "dashboard.db"))
    dashboard.begin_external_message(
        ExternalMessage(
            source="Imaging",
            subject="Schedule updated",
            message="Appointment moved.",
        )
    )

    assert started.wait(timeout=0.5)
    assert dashboard.snapshot()["agent_runtime"]["state"] == "running"
    assert dashboard.snapshot()["external_events"][0]["subject"] == "Schedule updated"

    release.set()
    deadline = time.monotonic() + 1
    while dashboard.background_state == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert dashboard.snapshot()["agent_runtime"]["state"] == "completed"
