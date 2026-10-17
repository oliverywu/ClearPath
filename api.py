"""FastAPI backend for the Cleared for Takeoff dashboard.

This is a thin HTTP layer only -- every number shown in the dashboard
comes from the existing, already-tested business logic modules. Nothing
here re-implements shipment math, regulatory grouping, or alerting; it
only calls into them and reshapes their results into a small, consistent
JSON contract for the frontend:

  - shipment_planner.load_shipments() / calculate_shipment()  -- baseline
    arrival/buffer/risk for every shipment (never deleted, even when a
    shipment is out of regulatory scope).
  - impact_analyzer.analyze_disruption_impact() / SIMULATED_DISRUPTION_EVENT
    -- the "Simulated Customs Hold" scenario (an in-transit delay).
  - regulatory_impact.build_regulatory_impact_report() -- the "Simulated
    German Labeling Change" scenario (a pre-dispatch label-review hold)
    plus the regulatory panel (candidate label groups, NEEDS_REVIEW
    reasons, source URLs, before/after diff).
  - notification_manager.find_newly_at_risk() / build_alert_message() /
    load_alert_state() -- disruption alerts, with "sent" read from the
    real persisted state file so the UI never claims a send that didn't
    happen.

No endpoint here ever sends a Photon message or mutates shipment/
regulatory data; everything returned is explicitly SIMULATED and carries
that marker through to the response.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import impact_analyzer
import label_grouping
import notification_manager
import regulatory_impact
from retrieval import load_regulations
from shipment_planner import ShipmentDataError, calculate_shipment, load_shipments

app = FastAPI(title="Cleared for Takeoff API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    # Matches any localhost/127.0.0.1 port: Vite defaults to 5173 but falls
    # back to the next free port if something else on the machine already
    # holds it, so a fixed origin list would break the dashboard for no
    # reason during local demos.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

ScenarioId = Literal["baseline", "customs_hold", "labeling_change"]

SIMULATED_DATA_NOTICE = (
    "All shipment, regulatory, and disruption data in this dashboard is "
    "SIMULATED for demonstration purposes only. No live tracking, no real "
    "Photon messages, and no regulatory compliance approvals are included."
)


def _scenario_catalog() -> dict:
    """Scenario descriptors for the selector, built from the same event /
    change objects the business logic actually uses -- not duplicated
    hardcoded text.
    """
    disruption = impact_analyzer.SIMULATED_DISRUPTION_EVENT
    change = label_grouping.SIMULATED_REGULATORY_CHANGE
    hold = regulatory_impact.SIMULATED_LABEL_REVIEW_HOLD
    return {
        "baseline": {
            "id": "baseline",
            "title": "Baseline",
            "kind": "baseline",
            "description": "No simulated disruption or regulatory change applied -- original shipment schedule only.",
        },
        "customs_hold": {
            "id": "customs_hold",
            "title": "Simulated Customs Hold",
            "kind": "in_transit_customs_hold",
            "description": disruption["description"],
            "event": disruption,
        },
        "labeling_change": {
            "id": "labeling_change",
            "title": "Simulated German Labeling Change",
            "kind": "pre_dispatch_labeling_hold",
            "description": f"{change['description']} {hold['description']}",
            "change": change,
            "hold": hold,
        },
    }


def _jurisdiction_info(destination: Optional[str]) -> tuple[Optional[str], bool]:
    jurisdiction, _member_state, _code = label_grouping.classify_destination(destination or "")
    return jurisdiction, jurisdiction in label_grouping.IN_SCOPE_JURISDICTIONS


def _baseline_rows(shipments: list) -> list:
    rows = []
    for shipment in shipments:
        result = calculate_shipment(shipment, delay_days=0)
        jurisdiction, in_scope = _jurisdiction_info(shipment.get("destination"))
        rows.append(
            {
                "shipment_id": result["shipment_id"],
                "drug_name": result["drug_name"],
                "origin": shipment.get("origin"),
                "destination": shipment.get("destination"),
                "jurisdiction": jurisdiction,
                "in_scope": in_scope,
                "original_arrival_date": result["estimated_arrival_date"].isoformat(),
                "revised_arrival_date": result["estimated_arrival_date"].isoformat(),
                "required_delivery_date": result["required_delivery_date"].isoformat(),
                "original_buffer_days": result["buffer_days"],
                "revised_buffer_days": result["buffer_days"],
                "original_at_risk": result["at_risk"],
                "revised_at_risk": result["at_risk"],
                "affected": False,
                "delay_type": "none",
                "delay_days": 0,
                "event_or_change": None,
            }
        )
    return rows


def _customs_hold_rows(shipments: list, disruption_results: list) -> list:
    event = impact_analyzer.SIMULATED_DISRUPTION_EVENT
    by_id = {s.get("shipment_id"): s for s in shipments}

    rows = []
    for result in disruption_results:
        shipment = by_id.get(result["shipment_id"], {})
        jurisdiction, in_scope = _jurisdiction_info(shipment.get("destination"))
        rows.append(
            {
                "shipment_id": result["shipment_id"],
                "drug_name": result["drug_name"],
                "origin": shipment.get("origin"),
                "destination": shipment.get("destination"),
                "jurisdiction": jurisdiction,
                "in_scope": in_scope,
                "original_arrival_date": result["original_arrival_date"].isoformat(),
                "revised_arrival_date": result["updated_arrival_date"].isoformat(),
                "required_delivery_date": result["required_delivery_date"].isoformat(),
                "original_buffer_days": result["original_buffer_days"],
                "revised_buffer_days": result["new_buffer_days"],
                "original_at_risk": result["original_at_risk"],
                "revised_at_risk": result["new_at_risk"],
                "affected": result["affected"],
                "delay_type": "in_transit_customs_hold" if result["affected"] else "none",
                "delay_days": event["additional_delay_days"] if result["affected"] else 0,
                "event_or_change": (
                    {
                        "id": result["event_id"],
                        "label": result["event_label"],
                        "description": result["event_description"],
                    }
                    if result["affected"]
                    else None
                ),
            }
        )
    return rows


def _labeling_change_rows(shipments: list, regulatory_report: dict) -> list:
    by_id = {s.get("shipment_id"): s for s in shipments}
    change = regulatory_report["simulated_regulatory_change"]

    rows = []
    for impact in regulatory_report["shipment_impacts"]:
        shipment = by_id.get(impact["shipment_id"], {})
        hold = impact.get("operational_hold")

        if impact["operational_hold_applied"] and hold:
            delay_type = "pre_dispatch_labeling_hold"
            delay_days = hold["additional_dispatch_delay_days"]
            event_or_change = {
                "id": hold["hold_id"],
                "label": hold["label"],
                "description": hold["description"],
            }
        elif impact["regulatorily_affected"]:
            delay_type = "regulatory_review_only"
            delay_days = 0
            event_or_change = {
                "id": change["change_id"],
                "label": change["label"],
                "description": change["description"],
            }
        else:
            delay_type = "none"
            delay_days = 0
            event_or_change = None

        jurisdiction, _in_scope = _jurisdiction_info(impact.get("destination"))
        rows.append(
            {
                "shipment_id": impact["shipment_id"],
                "drug_name": impact["drug_name"],
                "origin": shipment.get("origin"),
                "destination": impact["destination"],
                "jurisdiction": jurisdiction,
                "in_scope": impact["in_scope"],
                "original_arrival_date": impact["original_arrival_date"],
                "revised_arrival_date": impact["revised_arrival_date"],
                "required_delivery_date": impact["required_delivery_date"],
                "original_buffer_days": impact["original_buffer_days"],
                "revised_buffer_days": impact["revised_buffer_days"],
                "original_at_risk": impact["original_at_risk"],
                "revised_at_risk": impact["revised_at_risk"],
                "affected": impact["operational_hold_applied"] or impact["regulatorily_affected"],
                "delay_type": delay_type,
                "delay_days": delay_days,
                "event_or_change": event_or_change,
            }
        )
    return rows


def _newly_at_risk_count(scenario: str, disruption_results: list, regulatory_report: dict) -> int:
    if scenario == "customs_hold":
        return len(notification_manager.find_newly_at_risk(disruption_results))
    if scenario == "labeling_change":
        return sum(
            1
            for impact in regulatory_report["shipment_impacts"]
            if not impact["original_at_risk"] and impact["revised_at_risk"]
        )
    return 0


def _combined_alerts(disruption_results: list, regulatory_report: dict) -> list:
    """Alert payloads for the Alerts panel. "sent" is only ever True when
    notification_manager's persisted state file actually recorded a
    successful send for that exact alert key -- never assumed from the
    UI's current scenario selection.
    """
    state = notification_manager.load_alert_state()
    sent_keys = set(state.get("sent_alert_keys", []))

    alerts = []
    for result in notification_manager.find_newly_at_risk(disruption_results):
        key = f"{result['event_id']}:{result['shipment_id']}"
        alerts.append(
            {
                "alert_id": key,
                "source": "customs_disruption",
                "label": result["event_label"],
                "shipment_id": result["shipment_id"],
                "drug_name": result["drug_name"],
                "message": notification_manager.build_alert_message(result),
                "sent": key in sent_keys,
            }
        )

    for alert in regulatory_report["alerts"]:
        alerts.append(
            {
                "alert_id": alert["alert_id"],
                "source": "regulatory_change",
                "label": alert["label"],
                "shipment_id": alert["shipment_id"],
                "drug_name": alert["drug_name"],
                "message": alert["reason_summary"],
                "sent": alert["sent"],
            }
        )
    return alerts


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/scenarios")
def scenarios() -> list:
    return list(_scenario_catalog().values())


@app.get("/api/dashboard")
def dashboard(scenario: ScenarioId = Query("baseline")) -> dict:
    try:
        shipments = load_shipments()
    except ShipmentDataError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    regulations = load_regulations()
    regulatory_report = regulatory_impact.build_regulatory_impact_report(
        shipments=shipments, regulations=regulations
    )
    disruption_results = impact_analyzer.analyze_disruption_impact(
        shipments, impact_analyzer.SIMULATED_DISRUPTION_EVENT
    )

    if scenario == "baseline":
        rows = _baseline_rows(shipments)
    elif scenario == "customs_hold":
        rows = _customs_hold_rows(shipments, disruption_results)
    else:
        rows = _labeling_change_rows(shipments, regulatory_report)

    baseline_at_risk_count = sum(1 for row in _baseline_rows(shipments) if row["original_at_risk"])
    alerts = _combined_alerts(disruption_results, regulatory_report)

    overview = {
        "shipment_count": len(shipments),
        "baseline_at_risk_count": baseline_at_risk_count,
        "newly_at_risk_count": _newly_at_risk_count(scenario, disruption_results, regulatory_report),
        "regulatory_alerts_count": len(regulatory_report["alerts"]),
    }

    regulatory_panel = {
        "scope": regulatory_report["scope"],
        "excluded_jurisdictions": regulatory_report["excluded_jurisdictions"],
        "excluded_shipment_ids": regulatory_report["excluded_shipment_ids"],
        "simulated_regulatory_change": regulatory_report["simulated_regulatory_change"],
        "candidate_groups_before_change": regulatory_report["candidate_groups_before_change"],
        "candidate_groups_after_change": regulatory_report["candidate_groups_after_change"],
        "reasons_diff": regulatory_report["regulatory_reasons_diff"],
        "disclaimer": regulatory_report["disclaimer"],
    }

    return {
        "scenario": _scenario_catalog()[scenario],
        "overview": overview,
        "shipments": rows,
        "regulatory": regulatory_panel,
        "alerts": alerts,
        "simulated_data_notice": SIMULATED_DATA_NOTICE,
    }
