import pytest

from care_relay.calendar import (
    CalendarUpdateError,
    DemoCalendarGateway,
    GoogleCalendarGateway,
    calendar_gateway_from_env,
)


def test_calendar_gateway_defaults_to_demo_without_configuration(monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("CARE_RELAY_GOOGLE_CALENDAR_ID", raising=False)
    monkeypatch.delenv("CARE_RELAY_GOOGLE_FOLLOW_UP_EVENT_ID", raising=False)

    assert isinstance(calendar_gateway_from_env(), DemoCalendarGateway)


def test_partial_google_calendar_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/key.json")
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("CARE_RELAY_GOOGLE_CALENDAR_ID", raising=False)
    monkeypatch.delenv("CARE_RELAY_GOOGLE_FOLLOW_UP_EVENT_ID", raising=False)

    with pytest.raises(CalendarUpdateError, match="configuration is incomplete"):
        calendar_gateway_from_env()


def test_google_calendar_can_load_service_account_from_secret_json(monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv(
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        '{"type":"service_account","client_email":"demo@example.com"}',
    )
    monkeypatch.setenv("CARE_RELAY_GOOGLE_CALENDAR_ID", "calendar-id")
    monkeypatch.setenv("CARE_RELAY_GOOGLE_FOLLOW_UP_EVENT_ID", "event-id")

    gateway = calendar_gateway_from_env()

    assert isinstance(gateway, GoogleCalendarGateway)
    assert gateway.credentials_path is None
    assert gateway.credentials_info == {
        "type": "service_account",
        "client_email": "demo@example.com",
    }


def test_google_calendar_rejects_multiple_credential_sources(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/key.json")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')
    monkeypatch.setenv("CARE_RELAY_GOOGLE_CALENDAR_ID", "calendar-id")
    monkeypatch.setenv("CARE_RELAY_GOOGLE_FOLLOW_UP_EVENT_ID", "event-id")

    with pytest.raises(CalendarUpdateError, match="multiple credential sources"):
        calendar_gateway_from_env()


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeEvents:
    def __init__(self):
        self.patch_args = None

    def patch(self, **kwargs):
        self.patch_args = kwargs
        return FakeRequest(
            {
                "id": "event-1",
                "htmlLink": "https://www.google.com/calendar/event?eid=test",
                "status": "confirmed",
                "updated": "2026-09-09T12:00:00Z",
                "start": {"dateTime": "2026-09-15T11:00:00-04:00"},
            }
        )


class FakeService:
    def __init__(self):
        self.events_api = FakeEvents()

    def events(self):
        return self.events_api


def test_google_gateway_patches_same_event_without_notifications(tmp_path, monkeypatch):
    credentials = tmp_path / "service-account.json"
    credentials.write_text("{}")
    gateway = GoogleCalendarGateway(
        credentials_path=str(credentials),
        calendar_id="demo@group.calendar.google.com",
        event_id="event-1",
    )
    service = FakeService()
    monkeypatch.setattr(gateway, "_service", lambda: service)

    receipt = gateway.reschedule_follow_up(
        follow_up_at="2026-09-15T11:00:00-04:00",
        action_id="VISIT-1042:follow-up:test",
    )

    assert receipt.event_id == "event-1"
    assert service.events_api.patch_args["eventId"] == "event-1"
    assert service.events_api.patch_args["sendUpdates"] == "none"
    assert service.events_api.patch_args["body"]["extendedProperties"]["private"] == {
        "careRelayCase": "VISIT-1042",
        "careRelayAction": "VISIT-1042:follow-up:test",
    }
