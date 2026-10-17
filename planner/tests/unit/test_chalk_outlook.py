import json
from pathlib import Path
import unittest

from packages.assistant.grounded import answer_question
from packages.feature_provider import logistics
from packages.feature_provider.providers import LocalFeatureProvider, OUTLOOK_OUTPUTS
from packages.planner.engine import generate_plan

ROOT = Path(__file__).resolve().parents[2]


class ChalkOutlookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = json.loads((ROOT / "data/demo/trial_logistics.json").read_text(encoding="utf-8"))
        cls.plan = LocalFeatureProvider().enrich(generate_plan(cls.dataset))

    def shipment(self, code):
        return next(s for s in self.plan["shipments"] if s["country_code"] == code)

    def test_deployment_copy_is_identical(self):
        app_copy = (ROOT / "packages/feature_provider/logistics.py").read_bytes()
        chalk_copy = (ROOT / "chalk/logistics_formulas.py").read_bytes()
        self.assertEqual(app_copy, chalk_copy, "Copy packages/feature_provider/logistics.py to chalk/logistics_formulas.py")

    def test_outlook_matches_planner_for_every_country(self):
        for shipment in self.plan["shipments"]:
            f = shipment["features"]
            self.assertEqual(f["delivery_likely_at"], shipment["projected_delivery"], shipment["country_code"])
            self.assertEqual(f["delivery_best_at"], shipment["delivery_range"]["best"])
            self.assertEqual(f["delivery_worst_at"], shipment["delivery_range"]["worst"])
            self.assertEqual(f["ship_by_safe"], shipment["ship_by"]["safe"])
            self.assertEqual(f["ship_by_likely"], shipment["ship_by"]["likely"])
            self.assertEqual(f["worst_case_slack_days"], shipment["worst_case_slack_days"])
            self.assertTrue(all(key in f for key in OUTLOOK_OUTPUTS))

    def test_japan_answer_states_planner_dates(self):
        answer = self.shipment("JP")["features"]["agent_answer"]
        for text in ("dispatch by Sep 16", "target Oct 8", "NRT", "World Bank LPI 2023"):
            self.assertIn(text, answer)

    def test_domestic_answer_has_no_customs(self):
        answer = self.shipment("US")["features"]["agent_answer"]
        self.assertIn("no import clearance", answer)

    def test_late_dispatch_is_called_out(self):
        legs = json.dumps([{"best": 3, "likely": 4, "worst": 6}] * 4)
        answer = logistics.agent_answer("Test", "2026-11-02", "2026-11-20", "2026-11-30", "XXX", "demo estimate", legs, 0, "[]")
        self.assertIn("after the safe date", answer)

    def test_timing_question_uses_outlook_facts(self):
        scenario = dict(self.plan, name="Test", status="approved", id="test")
        result = answer_question("When does Japan need to ship?", scenario, self.dataset)
        self.assertIn(self.shipment("JP")["features"]["agent_answer"], result["answer"])
        self.assertIn("Source: local planner calculation", result["answer"])

    def test_approval_requests_still_refused(self):
        scenario = dict(self.plan, name="Test", status="approved", id="test")
        result = answer_question("Approve the express route for Japan, when can it ship?", scenario, self.dataset)
        self.assertIn("cannot approve", result["answer"])


if __name__ == "__main__":
    unittest.main()
