import json

import label_grouping
import regulatory_impact
from retrieval import load_regulations


def make_shipment(shipment_id, drug_name, destination, shipping_date="2026-10-01",
                   estimated_transit_days=5, required_delivery_date="2026-10-10"):
    return {
        "shipment_id": shipment_id,
        "drug_name": drug_name,
        "origin": "Indianapolis, US",
        "destination": destination,
        "shipping_date": shipping_date,
        "estimated_transit_days": estimated_transit_days,
        "required_delivery_date": required_delivery_date,
    }


SHIPMENTS = [
    make_shipment("SHIP-001", "Investigational Insulin Glargine", "Berlin, DE"),
    make_shipment("SHIP-002", "Investigational Insulin Glargine", "Tokyo, JP",
                   shipping_date="2026-10-03", estimated_transit_days=6,
                   required_delivery_date="2026-10-08"),
    make_shipment("SHIP-999", "Investigational Insulin Glargine", "Toronto, CA"),
]


# --- affected / unaffected shipments (requirement 2) -------------------------


def test_find_affected_shipments_matches_jurisdiction_and_member_state():
    affected = regulatory_impact.find_affected_shipments(SHIPMENTS, label_grouping.SIMULATED_REGULATORY_CHANGE)
    affected_ids = {s["shipment_id"] for s in affected}
    assert affected_ids == {"SHIP-001"}  # only the Berlin, DE shipment matches EU/DE


def test_canada_shipment_never_counted_as_affected():
    affected = regulatory_impact.find_affected_shipments(SHIPMENTS, label_grouping.SIMULATED_REGULATORY_CHANGE)
    affected_ids = {s["shipment_id"] for s in affected}
    assert "SHIP-999" not in affected_ids


def test_build_report_marks_in_scope_and_excluded_shipments_correctly():
    report = regulatory_impact.build_regulatory_impact_report(shipments=SHIPMENTS, regulations=load_regulations())

    impacts_by_id = {i["shipment_id"]: i for i in report["shipment_impacts"]}
    assert impacts_by_id["SHIP-001"]["in_scope"] is True
    assert impacts_by_id["SHIP-001"]["regulatorily_affected"] is True
    assert impacts_by_id["SHIP-002"]["in_scope"] is True
    assert impacts_by_id["SHIP-002"]["regulatorily_affected"] is False
    assert impacts_by_id["SHIP-999"]["in_scope"] is False
    assert impacts_by_id["SHIP-999"]["regulatorily_affected"] is False
    assert "SHIP-999" in report["excluded_shipment_ids"]


# --- no mutation (requirement 8) ---------------------------------------------


def test_build_report_never_mutates_input_shipments():
    shipments_copy = [dict(s) for s in SHIPMENTS]
    regulations = load_regulations()
    regulations_copy = [r.to_dict() for r in regulations]

    regulatory_impact.build_regulatory_impact_report(shipments=SHIPMENTS, regulations=regulations)

    assert SHIPMENTS == shipments_copy
    assert [r.to_dict() for r in regulations] == regulations_copy


def test_build_report_candidate_groups_before_and_after_are_independent_snapshots():
    report = regulatory_impact.build_regulatory_impact_report(shipments=SHIPMENTS, regulations=load_regulations())

    before = next(g for g in report["candidate_groups_before_change"] if g["drug_name"] == "Investigational Insulin Glargine")
    after = next(g for g in report["candidate_groups_after_change"] if g["drug_name"] == "Investigational Insulin Glargine")
    # the "before" snapshot must not have picked up the simulated reason
    assert not any("SIMULATED" in r for r in before["reasons"])
    assert any("SIMULATED" in r for r in after["reasons"])


# --- review-vs-delay distinction (requirement 3/4) ---------------------------


def test_regulatory_change_alone_never_adds_transit_days():
    # A hold that targets a shipment ID nobody has: the regulatory change
    # still flags SHIP-001 as affected, but with no hold able to apply,
    # revised arrival must equal original arrival for every shipment.
    inert_hold = {**regulatory_impact.SIMULATED_LABEL_REVIEW_HOLD, "shipment_id": "NO-SUCH-SHIPMENT"}

    report = regulatory_impact.build_regulatory_impact_report(
        shipments=SHIPMENTS, regulations=load_regulations(), hold=inert_hold,
    )

    ship_001 = next(i for i in report["shipment_impacts"] if i["shipment_id"] == "SHIP-001")
    assert ship_001["regulatorily_affected"] is True
    assert ship_001["operational_hold_applied"] is False
    assert ship_001["original_arrival_date"] == ship_001["revised_arrival_date"]
    assert ship_001["original_buffer_days"] == ship_001["revised_buffer_days"]
    assert ship_001["original_at_risk"] == ship_001["revised_at_risk"]


def test_hold_does_not_apply_to_shipment_outside_the_regulatory_change_scope():
    # Force the hold onto SHIP-002 (Tokyo, JP) -- it is not EU/DE, so even
    # though the hold *names* it, the hold must not apply (requirement 4:
    # only adjust the projected arrival if the hold actually delays dispatch).
    misdirected_hold = {**regulatory_impact.SIMULATED_LABEL_REVIEW_HOLD, "shipment_id": "SHIP-002"}

    report = regulatory_impact.build_regulatory_impact_report(
        shipments=SHIPMENTS, regulations=load_regulations(), hold=misdirected_hold,
    )

    ship_002 = next(i for i in report["shipment_impacts"] if i["shipment_id"] == "SHIP-002")
    assert ship_002["operational_hold_applied"] is False
    assert ship_002["original_arrival_date"] == ship_002["revised_arrival_date"]


# --- before/after calculations (requirement 5) -------------------------------


def test_hold_applies_to_ship_001_and_shifts_arrival_by_exactly_the_hold_days():
    report = regulatory_impact.build_regulatory_impact_report(shipments=SHIPMENTS, regulations=load_regulations())

    ship_001 = next(i for i in report["shipment_impacts"] if i["shipment_id"] == "SHIP-001")
    assert ship_001["operational_hold_applied"] is True
    assert ship_001["original_arrival_date"] == "2026-10-06"
    assert ship_001["revised_arrival_date"] == "2026-10-09"  # +3 days from the hold
    assert ship_001["required_delivery_date"] == "2026-10-10"
    assert ship_001["original_buffer_days"] == 4
    assert ship_001["revised_buffer_days"] == 1
    assert ship_001["original_at_risk"] is False
    assert ship_001["revised_at_risk"] is False  # still arrives before the required date


def test_unaffected_shipment_original_and_revised_are_identical():
    report = regulatory_impact.build_regulatory_impact_report(shipments=SHIPMENTS, regulations=load_regulations())

    ship_002 = next(i for i in report["shipment_impacts"] if i["shipment_id"] == "SHIP-002")
    assert ship_002["operational_hold_applied"] is False
    assert ship_002["original_arrival_date"] == ship_002["revised_arrival_date"]
    assert ship_002["original_buffer_days"] == ship_002["revised_buffer_days"]
    assert ship_002["original_at_risk"] == ship_002["revised_at_risk"]


def test_large_hold_can_flip_risk_status():
    big_hold = {**regulatory_impact.SIMULATED_LABEL_REVIEW_HOLD, "additional_dispatch_delay_days": 10}

    report = regulatory_impact.build_regulatory_impact_report(
        shipments=SHIPMENTS, regulations=load_regulations(), hold=big_hold,
    )

    ship_001 = next(i for i in report["shipment_impacts"] if i["shipment_id"] == "SHIP-001")
    assert ship_001["original_at_risk"] is False
    assert ship_001["revised_at_risk"] is True
    assert ship_001["revised_buffer_days"] < 0


# --- regulatory evidence / uncertainty preserved (requirement 6) ------------


def test_eu_wide_and_germany_specific_warnings_both_preserved_in_report():
    report = regulatory_impact.build_regulatory_impact_report(shipments=SHIPMENTS, regulations=load_regulations())

    after = next(g for g in report["candidate_groups_after_change"] if g["drug_name"] == "Investigational Insulin Glargine")
    assert any("No documented language requirement" in r and "EU" in r for r in after["reasons"])
    assert any("SIMULATED" in r for r in after["reasons"])


# --- alert payloads (requirement 9) ------------------------------------------


def test_alerts_only_generated_for_shipments_needing_review_or_action():
    report = regulatory_impact.build_regulatory_impact_report(shipments=SHIPMENTS, regulations=load_regulations())

    alert_ids = {a["shipment_id"] for a in report["alerts"]}
    assert "SHIP-001" in alert_ids  # NEEDS_REVIEW candidate group + hold applied
    for alert in report["alerts"]:
        assert alert["label"] == "SIMULATED"
        assert alert["sent"] is False


def test_no_photon_send_function_referenced_in_module():
    # This module must never import or call the Photon bridge -- alerts are
    # prepared data only, left for notification_manager/a dashboard to act on.
    assert not hasattr(regulatory_impact, "send_text_message")
    assert not hasattr(regulatory_impact, "build_photon_client")


# --- JSON serializability (requirement 7) ------------------------------------


def test_build_report_is_json_serializable():
    report = regulatory_impact.build_regulatory_impact_report(shipments=SHIPMENTS, regulations=load_regulations())
    dumped = json.dumps(report)
    assert json.loads(dumped)["scope"] == ["EU", "Japan", "US"]
