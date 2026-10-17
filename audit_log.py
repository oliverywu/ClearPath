"""Append-only audit log for approved supply-chain decisions.

Every entry records who approved what, when, and the before/after plan.
Entries are appended as one JSON object per line to an append-only file --
never rewritten in place, never containing secrets (API keys, tokens).
Only `decision_agent.handle_reply()` ever writes here, and only after an
explicit APPROVE from a verified, authorized actor.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

AUDIT_LOG_PATH = Path(__file__).resolve().parent / ".audit_log.jsonl"

REQUIRED_FIELDS = (
    "event_id",
    "shipment_id",
    "selected_option",
    "authorized_actor",
    "timestamp",
    "before_plan",
    "after_plan",
    "channel",
)


def append_entry(entry: dict[str, Any], path: Path = AUDIT_LOG_PATH) -> dict[str, Any]:
    """Append one audit entry as a JSON line. Raises ValueError if a
    required field is missing rather than silently logging a partial
    record -- the audit trail must stay trustworthy.
    """
    missing = [field for field in REQUIRED_FIELDS if field not in entry]
    if missing:
        raise ValueError(f"Audit log entry missing required field(s): {', '.join(missing)}")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def load_entries(path: Path = AUDIT_LOG_PATH) -> list[dict[str, Any]]:
    """Return every audit entry in file order (oldest first). An empty or
    missing file returns an empty list, never an error.
    """
    path = Path(path)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries
