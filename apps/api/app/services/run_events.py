import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from app.models.enums import RunStatus


TERMINAL_STATUS_VALUES = {"COMPLETED", "FAILED", "CANCELLED"}
TOTAL_RESEARCH_STEPS = 9
COMPLETED_STEPS_BY_STATUS = {
    RunStatus.QUEUED: 0,
    RunStatus.VALIDATING: 0,
    RunStatus.DECOMPOSING: 1,
    RunStatus.RESEARCHING: 2,
    RunStatus.EXTRACTING: 3,
    RunStatus.ANALYZING_PROVENANCE: 5,
    RunStatus.SCORING: 6,
    RunStatus.SYNTHESIZING: 7,
    RunStatus.AUDITING: 8,
    RunStatus.COMPLETED: 9,
    RunStatus.FAILED: 0,
    RunStatus.CANCELLED: 0,
}


def validate_last_event_id(value: str | None) -> str:
    if value is None or not value.strip():
        return "0-0"
    parts = value.strip().split("-", maxsplit=1)
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("Last-Event-ID must be a Redis Stream id")
    return value.strip()


def public_event_data(fields: Mapping[str, Any]) -> dict[str, Any]:
    raw_payload = fields.get("payload", "{}")
    try:
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else dict(raw_payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    stage = RunStatus(str(fields["stage"]))
    source_counts = payload.get("source_counts", {})
    return {
        "run_id": str(fields["run_id"]),
        "stage": stage.value,
        "message": str(fields.get("message", "Research progress updated.")),
        "completed_steps": int(
            payload.get("completed_steps", COMPLETED_STEPS_BY_STATUS[stage])
        ),
        "total_steps": int(payload.get("total_steps", TOTAL_RESEARCH_STEPS)),
        "source_counts": source_counts if isinstance(source_counts, dict) else {},
        "inaccessible_count": int(payload.get("inaccessible_count", 0)),
        "event_type": str(fields.get("event_type", "run.progress")),
        "created_at": str(fields.get("created_at", datetime.now().astimezone().isoformat())),
    }


def terminal_database_event(
    *, run_id: UUID, status: RunStatus, message: str, created_at: datetime
) -> dict[str, Any]:
    return public_event_data(
        {
            "run_id": str(run_id),
            "stage": status.value,
            "message": message,
            "event_type": f"run.{status.value.lower()}",
            "payload": "{}",
            "created_at": created_at.isoformat(),
        }
    )


def encode_sse(event_id: str, data: Mapping[str, Any]) -> str:
    encoded = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return f"event: progress\nid: {event_id}\ndata: {encoded}\n\n"
