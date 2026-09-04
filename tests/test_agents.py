"""Structural tests for the Strands agent composition."""

from strands.models import Model
from strands.session import FileSessionManager

from care_relay.agents import build_agents
from care_relay.demo import build_demo_case
from care_relay.engine import apply_event
from care_relay.models import EventType
from care_relay.tools import CareRelayTools


class OfflineModel(Model):
    """No-network model used to inspect agent wiring in unit tests."""

    def __init__(self):
        self.config = {"model_id": "offline-test-model"}

    def update_config(self, **model_config):
        self.config.update(model_config)

    def get_config(self):
        return self.config

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}, "contentBlockIndex": 0}}
        yield {"contentBlockDelta": {"delta": {"text": "offline"}, "contentBlockIndex": 0}}
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}}}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError


def test_agent_bundle_registers_separate_tool_boundaries():
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
    bundle = build_agents(CareRelayTools(case), model=OfflineModel())

    coordinator_tools = set(bundle.coordinator.tool_names)
    verifier_tools = set(bundle.verifier.tool_names)

    assert "send_referral_correction" in coordinator_tools
    assert "request_family_transport" in coordinator_tools
    assert "record_appointment_change" in coordinator_tools
    assert "list_approved_family_members" in coordinator_tools
    assert "get_available_follow_up_slots" in coordinator_tools
    assert "ask_verification_agent" in coordinator_tools
    assert "send_referral_correction" not in verifier_tools
    assert "request_family_transport" not in verifier_tools
    assert verifier_tools == {
        "get_case_snapshot",
        "check_referral_receipt",
        "inspect_transmission",
        "verify_corrected_referral",
    }


def test_registered_strands_tool_can_read_case_without_model_call():
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
    bundle = build_agents(CareRelayTools(case), model=OfflineModel())

    result = bundle.coordinator.tool.get_case_snapshot()
    assert result["status"] == "success"
    assert '"case_id": "VISIT-1042"' in result["content"][0]["text"]
    assert '"readiness_percent": 50' in result["content"][0]["text"]


def test_strands_conversation_restores_from_durable_session(tmp_path):
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
    storage_dir = str(tmp_path / "strands")
    first = build_agents(
        CareRelayTools(case),
        model=OfflineModel(),
        session_manager=FileSessionManager("run-1", storage_dir=storage_dir),
    )
    first.coordinator("Remember this case")

    restored = build_agents(
        CareRelayTools(case),
        model=OfflineModel(),
        session_manager=FileSessionManager("run-1", storage_dir=storage_dir),
    )

    assert restored.coordinator.messages[0]["role"] == "user"
    assert restored.coordinator.messages[0]["content"][0]["text"] == "Remember this case"
