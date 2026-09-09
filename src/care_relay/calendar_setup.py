"""Create the two synthetic Google Calendar fixtures used by the demo."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from care_relay.calendar import GOOGLE_CALENDAR_SCOPE

FIXTURES = {
    "imaging": {
        "summary": "Imaging appointment · Northside Imaging",
        "scheduled_at": "2026-09-11T14:30:00-04:00",
        "duration_minutes": 60,
    },
    "follow_up": {
        "summary": "Riverside follow-up",
        "scheduled_at": "2026-09-11T11:00:00-04:00",
        "duration_minutes": 30,
    },
}


def _service(credentials_path: str) -> Any:
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SystemExit("Install Care Relay dependencies before running calendar setup") from exc
    credentials = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=[GOOGLE_CALENDAR_SCOPE],
    )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _event_body(kind: str, fixture: dict[str, Any]) -> dict[str, Any]:
    start = datetime.fromisoformat(fixture["scheduled_at"])
    end = start + timedelta(minutes=fixture["duration_minutes"])
    return {
        "summary": fixture["summary"],
        "description": (
            "Synthetic Care Relay demo event for VISIT-1042. "
            "Administrative coordination only; contains no real patient information."
        ),
        "start": {"dateTime": start.isoformat(), "timeZone": "America/New_York"},
        "end": {"dateTime": end.isoformat(), "timeZone": "America/New_York"},
        "extendedProperties": {"private": {"careRelayFixture": kind}},
    }


def _upsert_fixture(service: Any, calendar_id: str, kind: str) -> dict[str, Any]:
    fixture = FIXTURES[kind]
    existing = (
        service.events()
        .list(
            calendarId=calendar_id,
            privateExtendedProperty=f"careRelayFixture={kind}",
            maxResults=1,
            singleEvents=True,
        )
        .execute()
        .get("items", [])
    )
    body = _event_body(kind, fixture)
    if existing:
        return (
            service.events()
            .patch(
                calendarId=calendar_id,
                eventId=existing[0]["id"],
                body=body,
                sendUpdates="none",
            )
            .execute()
        )
    return (
        service.events()
        .insert(calendarId=calendar_id, body=body, sendUpdates="none")
        .execute()
    )


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Create or reset Care Relay's synthetic Google Calendar events."
    )
    parser.add_argument(
        "--credentials",
        default=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        help="Path to the service-account JSON file",
    )
    parser.add_argument(
        "--calendar-id",
        default=os.getenv("CARE_RELAY_GOOGLE_CALENDAR_ID"),
        help="ID of the dedicated Care Relay Demo calendar",
    )
    args = parser.parse_args()
    if not args.credentials or not args.calendar_id:
        parser.error("--credentials and --calendar-id are required (or set them in .env)")
    credentials_path = Path(args.credentials).expanduser()
    if not credentials_path.is_file():
        parser.error(f"credential file not found: {credentials_path}")

    service = _service(str(credentials_path))
    imaging = _upsert_fixture(service, args.calendar_id, "imaging")
    follow_up = _upsert_fixture(service, args.calendar_id, "follow_up")

    print("Care Relay Demo calendar is ready.")
    print(f"Imaging event: {imaging.get('htmlLink', imaging['id'])}")
    print(f"Follow-up event: {follow_up.get('htmlLink', follow_up['id'])}")
    print("Add this value to .env:")
    print(f"CARE_RELAY_GOOGLE_FOLLOW_UP_EVENT_ID={follow_up['id']}")


if __name__ == "__main__":
    main()
