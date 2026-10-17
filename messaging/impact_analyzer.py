"""Disruption impact analysis for simulated clinical supply shipments.

Reuses shipment_planner.load_shipments() and shipment_planner.calculate_shipment()
rather than re-implementing shipment math. Given a simulated disruption event,
this module computes a *proposed* revised plan showing how the affected
shipment's arrival, buffer, and risk status would change -- without mutating
the original shipment data loaded from data/shipments.json.
"""

import unittest

from shipment_planner import ShipmentDataError, calculate_shipment, load_shipments

# A single simulated disruption event. Clearly labeled SIMULATED since this
# is not a real logistics event -- it exists only to demonstrate impact
# analysis for the HackHarvard project.
SIMULATED_DISRUPTION_EVENT = {
    "event_id": "SIM-DISRUPTION-001",
    "label": "SIMULATED",
    "description": "Simulated customs hold at Berlin, DE adding 6 transit days",
    "affected_shipment_ids": ["SHIP-001"],
    "additional_delay_days": 6,
}


def analyze_disruption_impact(shipments, disruption_event):
    """Compare each shipment's original plan to its plan under a disruption.

    Does not mutate `shipments`. Only shipment IDs listed in
    disruption_event["affected_shipment_ids"] receive the extra delay;
    every other shipment is analyzed with delay_days=0 (unaffected).

    Returns a list of result dicts, one per shipment, each containing the
    original calculation, the revised (proposed) calculation, and whether
    the disruption applied to that shipment.
    """
    affected_ids = set(disruption_event.get("affected_shipment_ids", []))
    delay_days = disruption_event.get("additional_delay_days", 0)

    results = []
    for shipment in shipments:
        shipment_id = shipment.get("shipment_id", "<unknown>")
        is_affected = shipment_id in affected_ids

        original = calculate_shipment(shipment, delay_days=0)
        revised = calculate_shipment(shipment, delay_days=delay_days if is_affected else 0)

        results.append(
            {
                "shipment_id": shipment_id,
                "drug_name": shipment.get("drug_name", "Unknown drug"),
                "affected": is_affected,
                "event_id": disruption_event.get("event_id") if is_affected else None,
                "event_label": disruption_event.get("label") if is_affected else None,
                "event_description": disruption_event.get("description") if is_affected else None,
                "original_arrival_date": original["estimated_arrival_date"],
                "updated_arrival_date": revised["estimated_arrival_date"],
                "required_delivery_date": original["required_delivery_date"],
                "original_buffer_days": original["buffer_days"],
                "new_buffer_days": revised["buffer_days"],
                "original_at_risk": original["at_risk"],
                "new_at_risk": revised["at_risk"],
            }
        )
    return results


def _format_result(result):
    lines = [f"{result['shipment_id']} - {result['drug_name']}"]

    if result["affected"]:
        lines.append(
            f"    Event:              [{result['event_label']}] {result['event_id']} "
            f"- {result['event_description']}"
        )
    else:
        lines.append("    Event:              none (not affected by this disruption)")

    lines.append(f"    Original arrival:   {result['original_arrival_date'].isoformat()}")
    lines.append(f"    Updated arrival:    {result['updated_arrival_date'].isoformat()}")
    lines.append(f"    Required by:        {result['required_delivery_date'].isoformat()}")
    lines.append(f"    Original buffer:    {result['original_buffer_days']} day(s)")
    lines.append(f"    New buffer:         {result['new_buffer_days']} day(s)")
    lines.append(
        "    Risk status:        "
        f"{'ORIGINAL AT RISK' if result['original_at_risk'] else 'ORIGINAL ON TRACK'} -> "
        f"{'NOW AT RISK' if result['new_at_risk'] else 'NOW ON TRACK'}"
    )
    return "\n".join(lines)


def main():
    try:
        shipments = load_shipments()
    except ShipmentDataError as exc:
        print(f"Error loading shipment data: {exc}")
        return

    print(f"Simulated disruption event: [{SIMULATED_DISRUPTION_EVENT['label']}] "
          f"{SIMULATED_DISRUPTION_EVENT['event_id']}")
    print(f"Description: {SIMULATED_DISRUPTION_EVENT['description']}")
    print(f"Affected shipment(s): {', '.join(SIMULATED_DISRUPTION_EVENT['affected_shipment_ids'])}")
    print("This is a proposed revised plan only; original shipment data is unchanged.\n")

    try:
        results = analyze_disruption_impact(shipments, SIMULATED_DISRUPTION_EVENT)
    except ShipmentDataError as exc:
        print(f"Error analyzing shipments: {exc}")
        return

    for result in results:
        print(_format_result(result))
        print()


class ImpactAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.shipments = [
            {
                "shipment_id": "SHIP-001",
                "drug_name": "Investigational Insulin Glargine",
                "shipping_date": "2026-10-01",
                "estimated_transit_days": 5,
                "required_delivery_date": "2026-10-10",
            },
            {
                "shipment_id": "SHIP-002",
                "drug_name": "Investigational Insulin Glargine",
                "shipping_date": "2026-10-03",
                "estimated_transit_days": 6,
                "required_delivery_date": "2026-10-08",
            },
        ]
        self.disruption = {
            "event_id": "SIM-DISRUPTION-001",
            "label": "SIMULATED",
            "description": "Simulated customs hold adding 6 transit days",
            "affected_shipment_ids": ["SHIP-001"],
            "additional_delay_days": 6,
        }

    def test_affected_shipment_original_scenario(self):
        results = analyze_disruption_impact(self.shipments, self.disruption)
        ship_001 = next(r for r in results if r["shipment_id"] == "SHIP-001")
        self.assertEqual(ship_001["original_arrival_date"].isoformat(), "2026-10-06")
        self.assertEqual(ship_001["original_buffer_days"], 4)
        self.assertFalse(ship_001["original_at_risk"])

    def test_affected_shipment_disrupted_scenario(self):
        results = analyze_disruption_impact(self.shipments, self.disruption)
        ship_001 = next(r for r in results if r["shipment_id"] == "SHIP-001")
        self.assertTrue(ship_001["affected"])
        self.assertEqual(ship_001["updated_arrival_date"].isoformat(), "2026-10-12")
        self.assertEqual(ship_001["new_buffer_days"], -2)
        self.assertTrue(ship_001["new_at_risk"])
        self.assertEqual(ship_001["event_id"], "SIM-DISRUPTION-001")
        self.assertEqual(ship_001["event_label"], "SIMULATED")

    def test_unaffected_shipment_unchanged(self):
        results = analyze_disruption_impact(self.shipments, self.disruption)
        ship_002 = next(r for r in results if r["shipment_id"] == "SHIP-002")
        self.assertFalse(ship_002["affected"])
        self.assertIsNone(ship_002["event_id"])
        self.assertEqual(ship_002["original_arrival_date"], ship_002["updated_arrival_date"])
        self.assertEqual(ship_002["original_buffer_days"], ship_002["new_buffer_days"])
        self.assertEqual(ship_002["original_at_risk"], ship_002["new_at_risk"])

    def test_original_shipment_data_not_mutated(self):
        original_copy = [dict(s) for s in self.shipments]
        analyze_disruption_impact(self.shipments, self.disruption)
        self.assertEqual(self.shipments, original_copy)


if __name__ == "__main__":
    main()
