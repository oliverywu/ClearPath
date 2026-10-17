import json

import pytest

import audit_log

VALID_ENTRY = {
    "event_id": "SIM-DISRUPTION-001",
    "shipment_id": "SHIP-001",
    "selected_option": {"option_id": 1, "label": "Reroute via Rotterdam (alternate port)"},
    "authorized_actor": {"id": "pho_usr_maya", "name": "Maya", "role": "supply_lead"},
    "timestamp": "2026-10-05T09:06:00+00:00",
    "before_plan": {"estimated_arrival_date": "2026-10-12", "at_risk": True},
    "after_plan": {"estimated_arrival_date": "2026-10-08", "at_risk": False},
    "channel": "iMessage",
}


def test_append_entry_requires_all_fields(tmp_path):
    incomplete = dict(VALID_ENTRY)
    del incomplete["authorized_actor"]
    with pytest.raises(ValueError):
        audit_log.append_entry(incomplete, path=tmp_path / "audit.jsonl")


def test_append_and_load_round_trips_in_order(tmp_path):
    path = tmp_path / "audit.jsonl"
    first = dict(VALID_ENTRY)
    second = {**VALID_ENTRY, "shipment_id": "SHIP-002"}

    audit_log.append_entry(first, path=path)
    audit_log.append_entry(second, path=path)

    entries = audit_log.load_entries(path)
    assert len(entries) == 2
    assert entries[0]["shipment_id"] == "SHIP-001"
    assert entries[1]["shipment_id"] == "SHIP-002"


def test_append_is_append_only_never_rewrites_prior_lines(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit_log.append_entry(VALID_ENTRY, path=path)
    first_line = path.read_text(encoding="utf-8").splitlines()[0]

    audit_log.append_entry({**VALID_ENTRY, "shipment_id": "SHIP-003"}, path=path)
    lines = path.read_text(encoding="utf-8").splitlines()

    assert lines[0] == first_line  # untouched by the second append
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # each line is independently valid JSON


def test_load_entries_missing_file_returns_empty_list(tmp_path):
    assert audit_log.load_entries(tmp_path / "does-not-exist.jsonl") == []
