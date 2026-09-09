"""Calendar adapters for Care Relay's single follow-up scheduling action."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

INITIAL_FOLLOW_UP_AT = "2026-09-11T11:00:00-04:00"
FOLLOW_UP_DURATION_MINUTES = 30
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class CalendarUpdateError(RuntimeError):
    """Raised when an external calendar does not confirm an update."""


@dataclass(frozen=True)
class CalendarConfirmation:
    """Minimal external receipt retained as evidence of a calendar write."""

    backend: str
    event_id: str
    scheduled_at: str
    html_link: str | None = None
    provider_updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class CalendarGateway(Protocol):
    """Boundary implemented by the demo adapter and Google Calendar."""

    backend: str

    def reschedule_follow_up(self, *, follow_up_at: str, action_id: str) -> CalendarConfirmation:
        """Move one existing follow-up event and return the provider receipt."""

    def reset_follow_up(self) -> CalendarConfirmation:
        """Restore the demo event to its known initial time."""


class DemoCalendarGateway:
    """Deterministic local counterparty used until Google credentials are configured."""

    backend = "demo"
    event_id = "CARE-RELAY-FOLLOW-UP"

    def reschedule_follow_up(self, *, follow_up_at: str, action_id: str) -> CalendarConfirmation:
        del action_id
        return CalendarConfirmation(
            backend=self.backend,
            event_id=self.event_id,
            scheduled_at=follow_up_at,
        )

    def reset_follow_up(self) -> CalendarConfirmation:
        return CalendarConfirmation(
            backend=self.backend,
            event_id=self.event_id,
            scheduled_at=INITIAL_FOLLOW_UP_AT,
        )


class GoogleCalendarGateway:
    """Least-scope Google Calendar adapter for one pre-created synthetic event."""

    backend = "google"

    def __init__(self, *, credentials_path: str, calendar_id: str, event_id: str) -> None:
        path = Path(credentials_path).expanduser()
        if not path.is_file():
            raise CalendarUpdateError(f"Google credential file was not found: {path}")
        self.credentials_path = str(path)
        self.calendar_id = calendar_id
        self.event_id = event_id

    def _service(self) -> Any:
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise CalendarUpdateError(
                "Google Calendar dependencies are missing; reinstall Care Relay dependencies"
            ) from exc
        credentials = service_account.Credentials.from_service_account_file(
            self.credentials_path,
            scopes=[GOOGLE_CALENDAR_SCOPE],
        )
        return build("calendar", "v3", credentials=credentials, cache_discovery=False)

    @staticmethod
    def _event_body(scheduled_at: str, action_id: str) -> dict[str, Any]:
        start = datetime.fromisoformat(scheduled_at)
        if start.tzinfo is None:
            raise CalendarUpdateError("Google Calendar event time must include a UTC offset")
        end = start + timedelta(minutes=FOLLOW_UP_DURATION_MINUTES)
        return {
            "summary": "Riverside follow-up",
            "description": (
                "Synthetic Care Relay demo event for VISIT-1042. "
                "Administrative coordination only; contains no real patient information."
            ),
            "start": {"dateTime": start.isoformat(), "timeZone": "America/New_York"},
            "end": {"dateTime": end.isoformat(), "timeZone": "America/New_York"},
            "extendedProperties": {
                "private": {
                    "careRelayCase": "VISIT-1042",
                    "careRelayAction": action_id,
                }
            },
        }

    def _patch(self, *, scheduled_at: str, action_id: str) -> CalendarConfirmation:
        try:
            event = (
                self._service()
                .events()
                .patch(
                    calendarId=self.calendar_id,
                    eventId=self.event_id,
                    body=self._event_body(scheduled_at, action_id),
                    sendUpdates="none",
                    fields="id,htmlLink,status,updated,start,end,summary",
                )
                .execute()
            )
        except CalendarUpdateError:
            raise
        except Exception as exc:
            raise CalendarUpdateError(
                "Google Calendar did not confirm the follow-up update"
            ) from exc
        if event.get("status") == "cancelled" or not event.get("id"):
            raise CalendarUpdateError("Google Calendar returned an invalid event receipt")
        return CalendarConfirmation(
            backend=self.backend,
            event_id=event["id"],
            scheduled_at=event.get("start", {}).get("dateTime", scheduled_at),
            html_link=event.get("htmlLink"),
            provider_updated_at=event.get("updated"),
        )

    def reschedule_follow_up(self, *, follow_up_at: str, action_id: str) -> CalendarConfirmation:
        return self._patch(scheduled_at=follow_up_at, action_id=action_id)

    def reset_follow_up(self) -> CalendarConfirmation:
        return self._patch(scheduled_at=INITIAL_FOLLOW_UP_AT, action_id="demo-reset")


def calendar_gateway_from_env() -> CalendarGateway:
    """Select Google only when its complete, explicit configuration is present."""
    values = {
        "credentials_path": os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip(),
        "calendar_id": os.getenv("CARE_RELAY_GOOGLE_CALENDAR_ID", "").strip(),
        "event_id": os.getenv("CARE_RELAY_GOOGLE_FOLLOW_UP_EVENT_ID", "").strip(),
    }
    if not any(values.values()):
        return DemoCalendarGateway()
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise CalendarUpdateError(
            "Google Calendar configuration is incomplete: " + ", ".join(missing)
        )
    return GoogleCalendarGateway(**values)
