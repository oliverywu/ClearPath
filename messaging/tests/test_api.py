from fastapi.testclient import TestClient

import api
import audit_log
import decision_agent
from notification_manager import load_alert_state
from shipment_planner import load_shipments

client = TestClient(api.app)


def test_health_check():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_scenarios_lists_exactly_the_three_required_options():
    resp = client.get("/api/scenarios")
    assert resp.status_code == 200
    ids = {s["id"] for s in resp.json()}
    assert ids == {"baseline", "customs_hold", "labeling_change"}


def test_invalid_scenario_rejected():
    resp = client.get("/api/dashboard", params={"scenario": "not-a-real-scenario"})
    assert resp.status_code == 422


# --- baseline scenario --------------------------------------------------


def test_baseline_scenario_counts_and_rows():
    resp = client.get("/api/dashboard", params={"scenario": "baseline"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["overview"]["shipment_count"] == 4
    assert data["overview"]["baseline_at_risk_count"] == 2  # SHIP-002, SHIP-004 per real fixture data
    assert data["overview"]["newly_at_risk_count"] == 0  # baseline has no scenario applied

    assert len(data["shipments"]) == 4
    for row in data["shipments"]:
        assert row["original_arrival_date"] == row["revised_arrival_date"]
        assert row["original_buffer_days"] == row["revised_buffer_days"]
        assert row["original_at_risk"] == row["revised_at_risk"]
        assert row["affected"] is False
        assert row["delay_type"] == "none"


# --- customs hold scenario (in-transit delay) ----------------------------


def test_customs_hold_scenario_delays_ship_001_and_flips_it_at_risk():
    resp = client.get("/api/dashboard", params={"scenario": "customs_hold"})
    data = resp.json()

    ship_001 = next(r for r in data["shipments"] if r["shipment_id"] == "SHIP-001")
    assert ship_001["delay_type"] == "in_transit_customs_hold"
    assert ship_001["affected"] is True
    assert ship_001["original_arrival_date"] == "2026-10-06"
    assert ship_001["revised_arrival_date"] == "2026-10-12"
    assert ship_001["original_at_risk"] is False
    assert ship_001["revised_at_risk"] is True

    ship_002 = next(r for r in data["shipments"] if r["shipment_id"] == "SHIP-002")
    assert ship_002["affected"] is False
    assert ship_002["original_arrival_date"] == ship_002["revised_arrival_date"]

    assert data["overview"]["newly_at_risk_count"] == 1


# --- labeling change scenario (pre-dispatch hold, distinct from transit delay) --


def test_labeling_change_scenario_applies_pre_dispatch_hold_not_transit_delay():
    resp = client.get("/api/dashboard", params={"scenario": "labeling_change"})
    data = resp.json()

    ship_001 = next(r for r in data["shipments"] if r["shipment_id"] == "SHIP-001")
    assert ship_001["delay_type"] == "pre_dispatch_labeling_hold"
    assert ship_001["delay_type"] != "in_transit_customs_hold"  # distinct from the customs scenario
    assert ship_001["revised_arrival_date"] == "2026-10-09"  # +3 days, not +6
    assert ship_001["revised_at_risk"] is False  # still arrives before the required date

    ship_002 = next(r for r in data["shipments"] if r["shipment_id"] == "SHIP-002")
    assert ship_002["delay_type"] == "none"  # Japan shipment is outside the EU/DE change's scope

    # the labeling scenario's hold is 3 days, not the customs scenario's 6 -- prove they're independent
    customs_resp = client.get("/api/dashboard", params={"scenario": "customs_hold"})
    customs_ship_001 = next(r for r in customs_resp.json()["shipments"] if r["shipment_id"] == "SHIP-001")
    assert customs_ship_001["revised_arrival_date"] != ship_001["revised_arrival_date"]


# --- regulatory panel (requirement 6) ------------------------------------


def test_regulatory_panel_scoped_to_us_eu_japan_and_preserves_both_warnings():
    resp = client.get("/api/dashboard", params={"scenario": "labeling_change"})
    reg = resp.json()["regulatory"]

    assert sorted(reg["scope"]) == ["EU", "Japan", "US"]
    assert "Canada" in reg["excluded_jurisdictions"]

    after = next(g for g in reg["candidate_groups_after_change"] if g["drug_name"] == "Investigational Insulin Glargine")
    before = next(g for g in reg["candidate_groups_before_change"] if g["drug_name"] == "Investigational Insulin Glargine")

    # EU-wide language warning survives a Germany-only simulated change...
    assert any("No documented language requirement" in r and "EU" in r for r in after["reasons"])
    # ...while the simulated change is clearly marked and additive, not a silent overwrite
    assert any("SIMULATED" in r for r in after["reasons"])
    assert not any("SIMULATED" in r for r in before["reasons"])
    # at least one real source URL is present for a human reviewer to check
    assert any(url.startswith("http") for url in after["sources"])


def test_regulatory_scope_never_deletes_out_of_scope_shipments_from_the_table():
    resp = client.get("/api/dashboard", params={"scenario": "baseline"})
    shipment_ids = {row["shipment_id"] for row in resp.json()["shipments"]}
    all_ids = {s["shipment_id"] for s in load_shipments()}
    assert shipment_ids == all_ids  # nothing dropped just because it's out of regulatory scope


# --- alerts panel: never claim "sent" without backend confirmation (requirement 7) --


def test_alerts_sent_flag_always_matches_persisted_backend_state():
    resp = client.get("/api/dashboard", params={"scenario": "customs_hold"})
    alerts = resp.json()["alerts"]
    assert alerts  # SHIP-001 should produce at least one alert in this scenario

    sent_keys = set(load_alert_state().get("sent_alert_keys", []))
    for alert in alerts:
        assert alert["label"] == "SIMULATED"
        if alert["source"] == "customs_disruption":
            assert alert["sent"] == (alert["alert_id"] in sent_keys)
        else:
            assert alert["sent"] is False  # regulatory_impact alerts are never sent


# --- no mutation of underlying data (requirement 8) -----------------------


def test_dashboard_requests_never_mutate_shipment_data_file():
    before = load_shipments()
    client.get("/api/dashboard", params={"scenario": "baseline"})
    client.get("/api/dashboard", params={"scenario": "customs_hold"})
    client.get("/api/dashboard", params={"scenario": "labeling_change"})
    after = load_shipments()
    assert before == after


# --- decision agent read-only endpoints (requirement 7) --------------------


def test_conversations_endpoint_lists_every_conversation(monkeypatch):
    fake = {
        "a": {"space_id": "s1", "event_id": "e1", "status": "AWAITING_OPTION"},
        "b": {"space_id": "s2", "event_id": "e1", "status": "APPROVED"},
    }
    monkeypatch.setattr(decision_agent, "load_conversations", lambda: fake)

    resp = client.get("/api/conversations")
    assert resp.status_code == 200
    statuses = {c["status"] for c in resp.json()}
    assert statuses == {"AWAITING_OPTION", "APPROVED"}


def test_pending_decisions_endpoint_excludes_approved_and_cancelled(monkeypatch):
    fake = {
        "a": {"space_id": "s1", "event_id": "e1", "status": "AWAITING_OPTION"},
        "b": {"space_id": "s2", "event_id": "e1", "status": "AWAITING_APPROVAL"},
        "c": {"space_id": "s3", "event_id": "e1", "status": "APPROVED"},
        "d": {"space_id": "s4", "event_id": "e1", "status": "CANCELLED"},
    }
    monkeypatch.setattr(decision_agent, "load_conversations", lambda: fake)

    resp = client.get("/api/pending-decisions")
    assert resp.status_code == 200
    statuses = {c["status"] for c in resp.json()}
    assert statuses == {"AWAITING_OPTION", "AWAITING_APPROVAL"}


def test_audit_log_endpoint_returns_persisted_entries(monkeypatch):
    fake_entries = [
        {
            "event_id": "SIM-DISRUPTION-001",
            "shipment_id": "SHIP-001",
            "selected_option": {"option_id": 1, "label": "Reroute via Rotterdam (alternate port)"},
            "authorized_actor": {"id": "pho_usr_maya", "name": "Maya", "role": "supply_lead"},
            "timestamp": "2026-10-05T09:06:00+00:00",
            "before_plan": {"estimated_arrival_date": "2026-10-12"},
            "after_plan": {"estimated_arrival_date": "2026-10-08"},
            "channel": "iMessage",
        }
    ]
    monkeypatch.setattr(audit_log, "load_entries", lambda: fake_entries)

    resp = client.get("/api/audit-log")
    assert resp.status_code == 200
    assert resp.json() == fake_entries


def test_audit_log_endpoint_empty_when_no_approvals_yet(monkeypatch):
    monkeypatch.setattr(audit_log, "load_entries", lambda: [])
    resp = client.get("/api/audit-log")
    assert resp.json() == []


# --- full pipeline integration: alert -> option -> preview -> approval ------
# -> persistent plan -> dashboard API. Drives the real decision_agent state
# machine against tmp_path files, then points the live endpoints at that
# persisted state the same way a restarted process would re-read it from
# disk -- never a live Photon send (no photon_client involved at all here).


def _approve_ship_001_customs_hold(tmp_path, *, actor_id="pho_usr_maya", roles=None, option="1"):
    from impact_analyzer import SIMULATED_DISRUPTION_EVENT

    state_path = tmp_path / "conversations.json"
    audit_path = tmp_path / "audit.jsonl"
    roles = roles if roles is not None else {"pho_usr_maya": {"name": "Maya", "role": "supply_lead", "can_approve": True}}

    alert = decision_agent.start_conversation(
        "pho_spc_maya", SIMULATED_DISRUPTION_EVENT["event_id"], "SHIP-001", state_path=state_path,
    )
    preview = decision_agent.handle_reply(
        "pho_spc_maya", SIMULATED_DISRUPTION_EVENT["event_id"], actor_id, option,
        state_path=state_path, audit_path=audit_path,
    )
    confirmation = decision_agent.handle_reply(
        "pho_spc_maya", SIMULATED_DISRUPTION_EVENT["event_id"], actor_id, "APPROVE",
        state_path=state_path, audit_path=audit_path, roles=roles,
    )
    return alert, preview, confirmation, state_path, audit_path


def test_full_pipeline_approved_decision_is_persistent_and_reflected_on_dashboard(monkeypatch, tmp_path):
    alert, preview, confirmation, state_path, audit_path = _approve_ship_001_customs_hold(tmp_path)

    assert "Pick a fix" in alert
    assert "Preview" in preview and "Reply APPROVE" in preview
    assert "Recorded" in confirmation and "Maya" in confirmation
    assert len(audit_log.load_entries(audit_path)) == 1

    # Simulate the dashboard reading persisted state after a process restart:
    # a totally fresh load from disk, no object shared with the steps above.
    persisted = decision_agent.load_conversations(state_path)
    monkeypatch.setattr(decision_agent, "load_conversations", lambda *a, **k: persisted)

    resp = client.get("/api/dashboard", params={"scenario": "customs_hold"})
    assert resp.status_code == 200
    data = resp.json()
    row = next(r for r in data["shipments"] if r["shipment_id"] == "SHIP-001")

    assert row["approved_decision"] is not None
    assert row["approved_decision"]["label"] == "Reroute via Rotterdam (alternate port)"
    assert row["approved_decision"]["approved_by"]["name"] == "Maya"
    assert row["approved_decision"]["channel"] == "iMessage"
    assert row["revised_arrival_date"] == "2026-10-08"
    assert row["revised_at_risk"] is False  # the approved plan, not the raw unmitigated disruption

    # the overview tile no longer counts this shipment as newly-at-risk
    assert data["overview"]["newly_at_risk_count"] == 0

    # the underlying simulated baseline fixture is untouched by any of this
    from shipment_planner import load_shipments
    ship_001_raw = next(s for s in load_shipments() if s["shipment_id"] == "SHIP-001")
    assert ship_001_raw["required_delivery_date"] == "2026-10-10"
    assert "approved_decision" not in ship_001_raw
    assert "estimated_arrival_date" not in ship_001_raw


def test_dashboard_never_reflects_an_unauthorized_approval_attempt(monkeypatch, tmp_path):
    from impact_analyzer import SIMULATED_DISRUPTION_EVENT

    state_path = tmp_path / "conversations.json"
    audit_path = tmp_path / "audit.jsonl"
    decision_agent.start_conversation(
        "pho_spc_maya", SIMULATED_DISRUPTION_EVENT["event_id"], "SHIP-001", state_path=state_path,
    )
    decision_agent.handle_reply(
        "pho_spc_maya", SIMULATED_DISRUPTION_EVENT["event_id"], "pho_usr_intruder", "1",
        state_path=state_path, audit_path=audit_path,
    )
    decision_agent.handle_reply(
        "pho_spc_maya", SIMULATED_DISRUPTION_EVENT["event_id"], "pho_usr_intruder", "APPROVE",
        state_path=state_path, audit_path=audit_path, roles={},  # no one authorized
    )

    persisted = decision_agent.load_conversations(state_path)
    monkeypatch.setattr(decision_agent, "load_conversations", lambda *a, **k: persisted)

    resp = client.get("/api/dashboard", params={"scenario": "customs_hold"})
    row = next(r for r in resp.json()["shipments"] if r["shipment_id"] == "SHIP-001")

    assert row["approved_decision"] is None
    assert row["revised_at_risk"] is True  # still the raw, unmitigated disruption
    assert audit_log.load_entries(audit_path) == []


def test_dashboard_reflects_duplicate_approve_once_not_as_conflicting_updates(monkeypatch, tmp_path):
    from impact_analyzer import SIMULATED_DISRUPTION_EVENT

    state_path = tmp_path / "conversations.json"
    audit_path = tmp_path / "audit.jsonl"
    roles = {"pho_usr_maya": {"name": "Maya", "role": "supply_lead", "can_approve": True}}

    decision_agent.start_conversation(
        "pho_spc_maya", SIMULATED_DISRUPTION_EVENT["event_id"], "SHIP-001", state_path=state_path,
    )
    decision_agent.handle_reply(
        "pho_spc_maya", SIMULATED_DISRUPTION_EVENT["event_id"], "pho_usr_maya", "1",
        state_path=state_path, audit_path=audit_path,
    )
    decision_agent.handle_reply(
        "pho_spc_maya", SIMULATED_DISRUPTION_EVENT["event_id"], "pho_usr_maya", "APPROVE",
        state_path=state_path, audit_path=audit_path, roles=roles,
    )
    # duplicate APPROVE, and a conflicting attempt to switch options afterward
    decision_agent.handle_reply(
        "pho_spc_maya", SIMULATED_DISRUPTION_EVENT["event_id"], "pho_usr_maya", "APPROVE",
        state_path=state_path, audit_path=audit_path, roles=roles,
    )
    decision_agent.handle_reply(
        "pho_spc_maya", SIMULATED_DISRUPTION_EVENT["event_id"], "pho_usr_maya", "3",
        state_path=state_path, audit_path=audit_path, roles=roles,
    )

    persisted = decision_agent.load_conversations(state_path)
    monkeypatch.setattr(decision_agent, "load_conversations", lambda *a, **k: persisted)

    resp = client.get("/api/dashboard", params={"scenario": "customs_hold"})
    row = next(r for r in resp.json()["shipments"] if r["shipment_id"] == "SHIP-001")

    assert row["approved_decision"]["option_id"] == 1  # the "3" attempt never took effect
    assert len(audit_log.load_entries(audit_path)) == 1
