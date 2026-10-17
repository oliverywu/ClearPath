import json
from pathlib import Path
import unittest

from packages.domain.validation import validate_dataset
from packages.planner.engine import business_diff, delivery_range, generate_plan

ROOT = Path(__file__).resolve().parents[2]


class LogisticsRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = json.loads((ROOT / "data/demo/trial.json").read_text(encoding="utf-8"))
        cls.enriched = json.loads((ROOT / "data/demo/trial_logistics.json").read_text(encoding="utf-8"))
        cls.plan = generate_plan(cls.enriched)

    def shipment(self, plan, code):
        return next(s for s in plan["shipments"] if s["country_code"] == code)

    def test_enriched_fixture_is_valid_and_deterministic(self):
        self.assertEqual([], validate_dataset(self.enriched))
        self.assertEqual(self.plan, generate_plan(self.enriched))

    def test_route_without_range_has_no_spread(self):
        route = {"transit_days": 5, "customs_days": 3, "depot_days": 1, "last_mile_days": 3}
        result = delivery_range(route, 0, "2026-11-02", "2026-11-30")
        self.assertEqual(result["delivery"]["best"], result["delivery"]["worst"])
        self.assertEqual(result["ship_by"]["likely"], result["ship_by"]["safe"])

    def test_safe_ship_by_absorbs_worst_case(self):
        route = {"transit_days": 3, "customs_days": 2, "depot_days": 1, "last_mile_days": 1,
                 "transit_days_range": {"best": 2, "worst": 5}, "customs_days_range": {"best": 1, "worst": 6}}
        holidays = ["2026-11-26"]
        result = delivery_range(route, 0, "2026-11-02", "2026-11-30", holidays)
        self.assertEqual(13, result["post_dispatch_days"]["worst"])
        self.assertLess(result["ship_by"]["safe"], result["ship_by"]["likely"])
        self.assertEqual(13, business_diff(result["ship_by"]["safe"], "2026-11-30", holidays))

    def test_likely_case_matches_main_schedule(self):
        for shipment in self.plan["shipments"]:
            self.assertEqual(shipment["projected_delivery"], shipment["delivery_range"]["likely"])
            self.assertLessEqual(shipment["delivery_range"]["best"], shipment["delivery_range"]["likely"])
            self.assertLessEqual(shipment["delivery_range"]["likely"], shipment["delivery_range"]["worst"])

    def test_holidays_and_domestic_customs_are_applied(self):
        jp = next(p for p in self.enriched["country_plans"] if p["jurisdiction"] == "JP")
        self.assertIn("2026-11-23", jp["holidays"])  # Labor Thanksgiving Day
        self.assertIn("2026-11-26", jp["holidays"])  # US Thanksgiving at the origin
        us_routes = [r for r in self.enriched["routes"] if r["jurisdiction"] == "US"]
        self.assertTrue(all(r["customs_days"] == 0 for r in us_routes))

    def test_worst_case_risk_is_explained(self):
        de = self.shipment(self.plan, "DE")
        self.assertLess(de["worst_case_slack_days"], 0)
        self.assertTrue(any("Worst case" in reason for reason in de["reasons"]))

    def test_base_demo_dates_are_unchanged(self):
        base_plan = generate_plan(self.base)
        jp = self.shipment(base_plan, "JP")
        self.assertEqual("2026-12-01", jp["projected_delivery"])
        self.assertEqual(jp["delivery_range"]["best"], jp["delivery_range"]["worst"])


if __name__ == "__main__":
    unittest.main()
