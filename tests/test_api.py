from fastapi.testclient import TestClient

import api
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
