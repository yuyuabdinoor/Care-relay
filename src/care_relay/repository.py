"""Durable local storage for Care Relay cases and synthetic demo state."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from care_relay.models import (
    Approval,
    ApprovalStatus,
    CareCase,
    CaseStatus,
    Commitment,
    CommitmentKind,
    CommitmentState,
    Dependency,
    EventType,
    Evidence,
    EvidenceKind,
    LedgerEntry,
)
from care_relay.tools import SyntheticWorld


class CaseRepository:
    """Small SQLite repository with atomic whole-case snapshots."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS case_snapshots (
                    case_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        self.path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save(
        self,
        case: CareCase,
        world: SyntheticWorld,
        *,
        stage: int,
        agent_session_id: str,
        activity: list[dict[str, str]],
        external_events: list[dict[str, str]],
        traces: list[dict[str, Any]],
    ) -> None:
        payload = {
            "case": asdict(case),
            "world": {
                "family_availability": {
                    name: sorted(times) for name, times in world.family_availability.items()
                },
                "referral_transmissions": world.referral_transmissions,
                "imaging_has_valid_referral": world.imaging_has_valid_referral,
                "sent_messages": world.sent_messages,
            },
            "stage": stage,
            "agent_session_id": agent_session_id,
            "activity": activity,
            "external_events": external_events,
            "traces": traces,
        }
        serialized = json.dumps(payload, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO case_snapshots (case_id, payload)
                VALUES (?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (case.case_id, serialized),
            )

    def load(self, case_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM case_snapshots WHERE case_id = ?", (case_id,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        payload["case"] = self._restore_case(payload["case"])
        payload["world"] = self._restore_world(payload["world"])
        return payload

    def delete(self, case_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM case_snapshots WHERE case_id = ?", (case_id,))

    @staticmethod
    def _restore_case(data: dict[str, Any]) -> CareCase:
        case = CareCase(
            case_id=data["case_id"],
            care_recipient_alias=data["care_recipient_alias"],
            coordinator_alias=data["coordinator_alias"],
            appointment_at=data["appointment_at"],
            status=CaseStatus(data["status"]),
        )
        case.commitments = {
            key: Commitment(
                commitment_id=item["commitment_id"],
                kind=CommitmentKind(item["kind"]),
                label=item["label"],
                required=item["required"],
                state=CommitmentState(item["state"]),
                owner=item["owner"],
                blocker=item["blocker"],
                evidence_ids=list(item["evidence_ids"]),
            )
            for key, item in data["commitments"].items()
        }
        case.dependencies = [Dependency(**item) for item in data["dependencies"]]
        case.evidence = {
            key: Evidence(
                evidence_id=item["evidence_id"],
                commitment_id=item["commitment_id"],
                kind=EvidenceKind(item["kind"]),
                source=item["source"],
                summary=item["summary"],
                observed_at=item["observed_at"],
            )
            for key, item in data["evidence"].items()
        }
        case.approvals = {
            key: Approval(
                approval_id=item["approval_id"],
                action=item["action"],
                recipient=item["recipient"],
                reason=item["reason"],
                disclosure=tuple(item["disclosure"]),
                requested_by=item["requested_by"],
                status=ApprovalStatus(item["status"]),
                decided_by=item["decided_by"],
                decided_at=item["decided_at"],
            )
            for key, item in data["approvals"].items()
        }
        case.ledger = [
            LedgerEntry(
                entry_id=item["entry_id"],
                event_type=EventType(item["event_type"]),
                actor=item["actor"],
                details=item["details"],
                occurred_at=item["occurred_at"],
            )
            for item in data["ledger"]
        ]
        return case

    @staticmethod
    def _restore_world(data: dict[str, Any]) -> SyntheticWorld:
        return SyntheticWorld(
            family_availability={
                name: set(times) for name, times in data["family_availability"].items()
            },
            referral_transmissions=data["referral_transmissions"],
            imaging_has_valid_referral=data["imaging_has_valid_referral"],
            sent_messages=data["sent_messages"],
        )
