"""Regulatory-to-shipment impact workflow for Cleared for Takeoff.

Connects the simulated EU/Germany labeling-regulation change already
defined in label_grouping.py to the shipment arrival/risk math in
shipment_planner.py, while keeping two concerns clearly separate:

  - Regulatory REVIEW flags: candidate label group status and
    `review_reasons` from label_grouping.py. These describe what a human
    regulatory reviewer needs to look at. A regulatory change never, by
    itself, changes a shipment's transit schedule.
  - An operational HOLD: a separate, explicitly SIMULATED assumption that
    a fulfillment team *might* delay dispatch of one shipment to redo its
    label/packaging in response to the regulatory change. This is a
    logistics proposal, not a consequence the regulation itself dictates.

Reuses existing building blocks rather than re-implementing them:
  - label_grouping.SIMULATED_REGULATORY_CHANGE, apply_simulated_regulatory_change,
    normalize_requirements, build_candidate_groups, diff_group_reasons,
    label_eligible_shipments, classify_destination, IN_SCOPE_JURISDICTIONS,
    EXCLUDED_JURISDICTIONS
  - shipment_planner.load_shipments, calculate_shipment, ShipmentDataError
  - retrieval.load_regulations

This module never asserts that the simulated regulation is real law, nor
that any candidate label group is approved for compliant use. Human
regulatory review is always required. No Photon message is ever sent from
here -- alert payloads are prepared and clearly marked SIMULATED for a
future dashboard/notification integration to pick up.
"""

from __future__ import annotations

import json
from typing import Optional

import label_grouping
from retrieval import load_regulations
from shipment_planner import ShipmentDataError, calculate_shipment, load_shipments

# --- Simulated operational hold (requirement 4) ------------------------------
#
# Deliberately NOT part of label_grouping.SIMULATED_REGULATORY_CHANGE: the
# regulatory change only adds a language/content requirement and review
# reasons (see label_grouping.apply_simulated_regulatory_change). It does
# not add transit days on its own. This hold is a separate, explicitly
# SIMULATED operational assumption layered on top of it for comparison.
#
# Assumption made explicit here: the hold is assumed to occur *before* the
# shipment's already-scheduled shipping_date (there is no earlier
# "ready date" in the shipment schema to absorb it into), so its full
# duration pushes the entire dispatch -- and therefore the arrival -- back
# by the same number of days. The hold is only ever applied to the
# shipment it names, and only when that shipment is actually within the
# triggering regulatory change's jurisdiction/member state; otherwise
# there is no logistics reason for the hold and the projected arrival is
# left unchanged.
SIMULATED_LABEL_REVIEW_HOLD = {
    "hold_id": "SIM-HOLD-001",
    "label": "SIMULATED",
    "description": (
        "Simulated operational assumption: in response to the simulated "
        "EU/DE labeling change, SHIP-001 is held 3 extra days before "
        "dispatch for label review and repackaging into German-language "
        "packaging. This is a proposed logistics scenario for comparison "
        "only -- not a confirmed operational decision."
    ),
    "shipment_id": "SHIP-001",
    "additional_dispatch_delay_days": 3,
    "triggering_change_id": label_grouping.SIMULATED_REGULATORY_CHANGE["change_id"],
}


# --- Scope / affected-shipment resolution (requirement 2) -------------------


def find_affected_shipments(shipments: list, change: dict) -> list:
    """Return label-eligible shipments actually subject to `change`'s
    jurisdiction (and member state, if any).

    Reuses label_grouping.label_eligible_shipments(), so scope stays US/EU/
    Japan and Canada (or any other out-of-scope destination) is excluded
    exactly as it is for candidate grouping. Does not mutate `shipments`.
    """
    eligible = label_grouping.label_eligible_shipments(shipments)
    jurisdiction = change.get("jurisdiction")
    member_state = change.get("member_state")

    affected = []
    for shipment in eligible:
        if shipment["_jurisdiction"] != jurisdiction:
            continue
        if member_state and shipment["_member_state"] != member_state:
            continue
        affected.append(shipment)
    return affected


def _hold_applies(shipment_id: str, regulatorily_affected_ids: set, hold: dict) -> bool:
    """A simulated dispatch hold only changes a shipment's projected
    arrival when it targets that exact shipment AND that shipment is
    actually affected by the triggering regulatory change (requirement 4:
    "only adjust the projected arrival if the hold actually delays
    dispatch"). A shipment outside the regulation's jurisdiction/member
    state has no logistics reason to be held for it.
    """
    return shipment_id == hold.get("shipment_id") and shipment_id in regulatorily_affected_ids


# --- Alert payloads (requirement 9) ------------------------------------------


def _alert_reason_summary(impact: dict, needs_review: bool) -> str:
    parts = []
    if needs_review:
        parts.append("candidate label group needs regulatory review")
    if impact["operational_hold_applied"]:
        parts.append("simulated dispatch hold applied")
    if impact["revised_at_risk"]:
        parts.append("revised arrival is AT RISK vs. required delivery date")
    return "; ".join(parts) if parts else "flagged for review"


def _build_alert_payloads(shipment_impacts: list, groups_after_by_drug: dict, change: dict) -> list:
    """Prepare (never send) an alert payload for each shipment that needs
    human review or action: its candidate label group is NEEDS_REVIEW, a
    simulated dispatch hold was applied to it, or its revised arrival is
    AT RISK. Every payload is clearly marked SIMULATED and carries a note
    that no Photon message was sent -- this is data for a future
    dashboard/notification integration to decide on.

    Scoped to in-scope (US/EU/Japan) shipments only, matching this
    workflow's regulatory scope (requirement 2) -- a shipment this report
    doesn't analyze for regulatory purposes shouldn't surface here either,
    even if it happens to be at risk for an unrelated reason.
    """
    alerts = []
    for impact in shipment_impacts:
        if not impact["in_scope"]:
            continue
        group = groups_after_by_drug.get(impact["drug_name"])
        needs_review = bool(group and group["status"] == "NEEDS_REVIEW")
        needs_alert = (
            needs_review
            or impact["operational_hold_applied"]
            or impact["revised_at_risk"]
        )
        if not needs_alert:
            continue
        alerts.append(
            {
                "alert_id": f"SIM-ALERT:{change['change_id']}:{impact['shipment_id']}",
                "label": "SIMULATED",
                "shipment_id": impact["shipment_id"],
                "drug_name": impact["drug_name"],
                "reason_summary": _alert_reason_summary(impact, needs_review),
                "candidate_group_status": group["status"] if group else None,
                "regulatory_review_reasons": list(group["reasons"]) if group else [],
                "operational_hold_applied": impact["operational_hold_applied"],
                "revised_at_risk": impact["revised_at_risk"],
                "revised_buffer_days": impact["revised_buffer_days"],
                "sent": False,
                "note": (
                    "SIMULATED alert payload prepared for a future dashboard/Photon "
                    "integration -- no message has been sent."
                ),
            }
        )
    return alerts


# --- Report assembly (requirements 1, 2, 3, 5, 6, 7, 8) ----------------------


def build_regulatory_impact_report(
    shipments: Optional[list] = None,
    regulations: Optional[list] = None,
    change: Optional[dict] = None,
    hold: Optional[dict] = None,
) -> dict:
    """Assemble the full regulatory-to-shipment impact report.

    Does not mutate `shipments`, `regulations`, or any candidate label
    group -- label_grouping's own functions already guarantee this for the
    regulatory side, and shipment_planner.calculate_shipment() returns new
    dicts rather than mutating shipment records.

    Returns a JSON-serializable dict (all dates are rendered as ISO
    strings) suitable for a future dashboard.
    """
    if shipments is None:
        shipments = load_shipments()
    if regulations is None:
        regulations = load_regulations()
    if change is None:
        change = label_grouping.SIMULATED_REGULATORY_CHANGE
    if hold is None:
        hold = SIMULATED_LABEL_REVIEW_HOLD

    # --- regulatory side: candidate groups before/after the simulated change.
    # This is the review-flag layer; nothing here touches shipment schedules.
    normalized_before = label_grouping.normalize_requirements(regulations)
    groups_before = label_grouping.build_candidate_groups(shipments, normalized_before)

    normalized_after = label_grouping.apply_simulated_regulatory_change(normalized_before, change)
    groups_after = label_grouping.build_candidate_groups(shipments, normalized_after)

    reasons_diff = label_grouping.diff_group_reasons(groups_before, groups_after)
    groups_after_by_drug = {g["drug_name"]: g for g in groups_after}

    all_eligible = label_grouping.label_eligible_shipments(shipments)
    eligible_ids = {s["shipment_id"] for s in all_eligible}
    all_ids = {s.get("shipment_id", "<unknown>") for s in shipments}
    excluded_ids = all_ids - eligible_ids

    regulatorily_affected = find_affected_shipments(shipments, change)
    affected_ids = {s["shipment_id"] for s in regulatorily_affected}

    # --- operational side: shipment-level original vs. revised (requirement 5).
    # original_* never includes the hold; revised_* only includes it when
    # _hold_applies() says the hold actually has a reason to delay dispatch
    # for that shipment (requirement 3/4's review-vs-delay distinction).
    shipment_impacts = []
    for shipment in shipments:
        shipment_id = shipment.get("shipment_id", "<unknown>")
        hold_applies = _hold_applies(shipment_id, affected_ids, hold)

        original = calculate_shipment(shipment, delay_days=0)
        revised = calculate_shipment(
            shipment, delay_days=hold["additional_dispatch_delay_days"] if hold_applies else 0
        )

        shipment_impacts.append(
            {
                "shipment_id": shipment_id,
                "drug_name": shipment.get("drug_name", "Unknown drug"),
                "destination": shipment.get("destination"),
                "in_scope": shipment_id in eligible_ids,
                "regulatorily_affected": shipment_id in affected_ids,
                "operational_hold_applied": hold_applies,
                "operational_hold": (
                    {
                        "hold_id": hold["hold_id"],
                        "label": hold["label"],
                        "description": hold["description"],
                        "additional_dispatch_delay_days": hold["additional_dispatch_delay_days"],
                    }
                    if hold_applies
                    else None
                ),
                "original_arrival_date": original["estimated_arrival_date"].isoformat(),
                "revised_arrival_date": revised["estimated_arrival_date"].isoformat(),
                "required_delivery_date": original["required_delivery_date"].isoformat(),
                "original_buffer_days": original["buffer_days"],
                "revised_buffer_days": revised["buffer_days"],
                "original_at_risk": original["at_risk"],
                "revised_at_risk": revised["at_risk"],
            }
        )

    alerts = _build_alert_payloads(shipment_impacts, groups_after_by_drug, change)

    return {
        "scope": sorted(label_grouping.IN_SCOPE_JURISDICTIONS),
        "excluded_jurisdictions": sorted(label_grouping.EXCLUDED_JURISDICTIONS),
        "excluded_shipment_ids": sorted(excluded_ids),
        "simulated_regulatory_change": change,
        "simulated_operational_hold": hold,
        "candidate_groups_before_change": groups_before,
        "candidate_groups_after_change": groups_after,
        "regulatory_reasons_diff": reasons_diff,
        "regulatorily_affected_shipment_ids": sorted(affected_ids),
        "shipment_impacts": shipment_impacts,
        "alerts": alerts,
        "disclaimer": (
            "All regulatory content and candidate label groups are proposals for "
            "human regulatory review only -- not a legal compliance or approval "
            "determination. Both the regulatory change and the dispatch hold "
            "modeled here are explicitly SIMULATED: not real law, and not a "
            "confirmed operational decision."
        ),
    }


# --- Terminal output ----------------------------------------------------------


def _print_shipment_impact(impact: dict) -> None:
    print(f"{impact['shipment_id']} - {impact['drug_name']} ({impact['destination']})")
    print(f"    In scope (US/EU/Japan):     {impact['in_scope']}")
    print(f"    Regulatorily affected:      {impact['regulatorily_affected']}")
    print(f"    Operational hold applied:   {impact['operational_hold_applied']}")
    print(f"    Original arrival:           {impact['original_arrival_date']}")
    print(f"    Revised arrival:            {impact['revised_arrival_date']}")
    print(f"    Required delivery:          {impact['required_delivery_date']}")
    print(f"    Original buffer (days):     {impact['original_buffer_days']}")
    print(f"    Revised buffer (days):      {impact['revised_buffer_days']}")
    print(
        "    Risk status:                "
        f"{'AT RISK' if impact['original_at_risk'] else 'ON TRACK'} -> "
        f"{'AT RISK' if impact['revised_at_risk'] else 'ON TRACK'}"
    )


def main() -> None:
    try:
        report = build_regulatory_impact_report()
    except ShipmentDataError as exc:
        print(f"Error loading shipment data: {exc}")
        return

    print(f"Scope: {', '.join(report['scope'])} (excluded: {', '.join(report['excluded_jurisdictions'])})")
    if report["excluded_shipment_ids"]:
        print(f"Excluded shipment(s) (out of scope, not analyzed): {', '.join(report['excluded_shipment_ids'])}")
    print()

    change = report["simulated_regulatory_change"]
    print(f"=== [{change['label']}] Regulatory change: {change['change_id']} ===")
    print(f"Jurisdiction/member state: {change['jurisdiction']}/{change.get('member_state')}")
    print(f"{change['description']}")
    print(
        "Regulatorily affected shipment(s): "
        f"{', '.join(report['regulatorily_affected_shipment_ids']) or 'none'}\n"
    )

    print("--- Candidate label groups AFTER the simulated regulatory change ---")
    for group in report["candidate_groups_after_change"]:
        print(f"{group['drug_name']} -- status: {group['status']}")
        if group["reasons"]:
            for reason in group["reasons"]:
                print(f"    - {reason}")
        else:
            print("    - no review reasons")
        print()

    hold = report["simulated_operational_hold"]
    print(f"=== [{hold['label']}] Simulated operational hold: {hold['hold_id']} ===")
    print(hold["description"])
    print(
        "Note: this hold is a separate, explicitly SIMULATED operational "
        "assumption. The regulatory change above does NOT by itself add "
        "transit days -- the hold only changes a shipment's projected "
        "arrival when that shipment is actually affected by the triggering "
        "change.\n"
    )

    print("--- Shipment impact: original vs. revised ---")
    for impact in report["shipment_impacts"]:
        _print_shipment_impact(impact)
        print()

    print("--- Alerts (SIMULATED payloads only -- nothing sent) ---")
    if not report["alerts"]:
        print("No alerts generated.")
    for alert in report["alerts"]:
        print(f"[{alert['label']}] {alert['alert_id']} -- {alert['reason_summary']} (sent={alert['sent']})")
    print()

    serialized = json.dumps(report)
    print(f"Full report is JSON-serializable ({len(serialized)} bytes) for dashboard consumption.")
    print(report["disclaimer"])


if __name__ == "__main__":
    main()
