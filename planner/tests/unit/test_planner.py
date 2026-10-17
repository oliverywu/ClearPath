import json
from copy import deepcopy
from pathlib import Path
import unittest

from packages.domain.validation import validate_dataset, validate_rule
from packages.planner.engine import business_add, business_diff, compare_plans, generate_plan, group_labels, select_rules

ROOT = Path(__file__).resolve().parents[2]


class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = json.loads((ROOT / "data/demo/trial.json").read_text(encoding="utf-8"))
        cls.baseline = generate_plan(cls.dataset)

    def shipment(self, plan, code):
        return next(s for s in plan["shipments"] if s["country_code"] == code)

    def test_complete_deterministic_baseline(self):
        self.assertEqual([], validate_dataset(self.dataset))
        self.assertEqual(self.baseline, generate_plan(self.dataset))
        self.assertEqual(24, self.baseline["metrics"]["countries"])
        self.assertEqual(4, self.baseline["metrics"]["blocked_shipments"])
        jp = self.shipment(self.baseline, "JP")
        self.assertEqual("SHIP-002", jp["id"])
        self.assertEqual("2026-12-01", jp["projected_delivery"])
        self.assertEqual(-38, jp["slack_days"])
        group = next(g for g in self.baseline["label_groups"] if "JP" in g["country_codes"])
        self.assertEqual(["JP"], group["country_codes"])

    def test_business_days_skip_weekend_and_holidays(self):
        self.assertEqual("2026-10-20", business_add("2026-10-16", 1, ["2026-10-19"]))
        self.assertEqual("2026-10-16", business_add("2026-10-20", -1, ["2026-10-19"]))
        self.assertEqual(-1, business_diff("2026-10-20", "2026-10-16", ["2026-10-19"]))

    def test_future_effective_rule_excluded_then_selected(self):
        before = select_rules(self.dataset, "2027-01-14")
        after = select_rules(self.dataset, "2027-01-15")
        self.assertFalse(any(r["id"].endswith("-v2") for r in before))
        self.assertTrue(any(r["id"].endswith("-v2") for r in after))
        self.assertFalse(any(r["id"] == "demo-JP-label.mandatory_fields-v1" for r in after))

    def test_unreviewed_rules_do_not_replace_accepted_evidence(self):
        data = deepcopy(self.dataset)
        data["rules"] = [dict(r, review_status="needs_review") for r in data["rules"]]
        self.assertEqual([], select_rules(data))
        plan = generate_plan(data)
        self.assertEqual(24, plan["metrics"]["blocked_shipments"])

    def test_label_change_propagation_and_split_repair(self):
        event = self.dataset["events"][0]
        proposed = generate_plan(self.dataset, parent=self.baseline, event=event)
        repaired = generate_plan(self.dataset, parent=self.baseline, event=event, repair="jp-split-label")
        jp = self.shipment(proposed, "JP")
        self.assertEqual("2026-12-08", jp["projected_delivery"])
        self.assertEqual("blocked", jp["risk_band"])
        self.assertEqual(5, jp["features"]["rework_days"])
        self.assertEqual(1, self.shipment(repaired, "JP")["features"]["rework_days"])
        self.assertEqual(4, repaired["metrics"]["blocked_shipments"])
        self.assertEqual(self.shipment(self.baseline, "NL"), self.shipment(proposed, "NL"))
        self.assertEqual(self.shipment(self.baseline, "DE")["projected_delivery"], self.shipment(repaired, "DE")["projected_delivery"])
        self.assertEqual(self.baseline, generate_plan(self.dataset))
        self.assertTrue(compare_plans(self.baseline, proposed)["causal_chain"])
        split = next(g for g in proposed["label_groups"] if "JP" in g["country_codes"])
        self.assertEqual(["JP"], split["country_codes"])
        self.assertTrue(any(r["code"] == "single_country" for r in split["reasons"]))

    def test_route_event_and_alternative_only_affect_destination(self):
        event = self.dataset["events"][1]
        proposed = generate_plan(self.dataset, parent=self.baseline, event=event)
        repaired = generate_plan(self.dataset, parent=self.baseline, event=event, repair="de-alternative-route")
        comparison = compare_plans(self.baseline, proposed)
        self.assertEqual(["DE"], [c["country_code"] for c in comparison["changes"]])
        self.assertEqual("2026-12-07", self.shipment(proposed, "DE")["projected_delivery"])
        self.assertGreater(self.shipment(repaired, "DE")["cost_proxy"], self.shipment(self.baseline, "DE")["cost_proxy"])
        self.assertGreater(self.shipment(repaired, "DE")["slack_days"], self.shipment(proposed, "DE")["slack_days"])
        impact = proposed["impacts"][0]
        self.assertEqual(["customs_arrival", "customs_release", "depot_arrival", "site_delivery"], [i.split(":")[-1] for i in impact["milestone_ids"]])

    def test_permit_event_preserves_other_countries(self):
        proposed = generate_plan(self.dataset, parent=self.baseline, event=self.dataset["events"][2])
        self.assertEqual(["CA"], [c["country_code"] for c in compare_plans(self.baseline, proposed)["changes"]])
        self.assertEqual(17, self.shipment(proposed, "CA")["features"]["permit_lead_days"])

    def test_cumulative_events_and_repairs(self):
        jp = generate_plan(self.dataset, parent=self.baseline, event=self.dataset["events"][0], repair="jp-split-label")
        both = generate_plan(self.dataset, parent=jp, event=self.dataset["events"][1])
        self.assertEqual(["jp-label-field", "de-route-delay"], both["applied_event_ids"])
        self.assertEqual(1, self.shipment(both, "JP")["features"]["rework_days"])
        self.assertEqual(4, self.shipment(both, "DE")["features"]["disruption_delay_days"])

    def test_comparison_only_explains_new_material_impacts(self):
        approved = generate_plan(self.dataset, parent=self.baseline, event=self.dataset["events"][0], repair="jp-split-label")
        proposed = generate_plan(self.dataset, parent=approved, event=self.dataset["events"][1])
        comparison = compare_plans(approved, proposed)
        self.assertEqual(["DE"], [change["country_code"] for change in comparison["changes"]])
        self.assertEqual([("DE", "de-route-delay")], [(chain["country_code"], chain["event_id"]) for chain in comparison["causal_chain"]])
        proposed["impacts"].append(deepcopy(next(impact for impact in proposed["impacts"] if impact["event_id"] == "de-route-delay")))
        self.assertEqual(1, len(compare_plans(approved, proposed)["causal_chain"]))
        self.assertEqual([], compare_plans(proposed, proposed)["causal_chain"])
        # A historical shared-label event also touches Germany, but its
        # unchanged contribution must not be repeated for a new route delay.
        shared = generate_plan(self.dataset, parent=self.baseline, event=self.dataset["events"][0])
        delayed = generate_plan(self.dataset, parent=shared, event=self.dataset["events"][1])
        self.assertEqual(["de-route-delay"], [chain["event_id"] for chain in compare_plans(shared, delayed)["causal_chain"]])

    def test_dag_dates_and_monotonic_delay(self):
        for plan in (self.baseline, generate_plan(self.dataset, parent=self.baseline, event=self.dataset["events"][0])):
            for shipment in plan["shipments"]:
                milestones = {m["id"]: m for m in shipment["milestones"]}
                for milestone in milestones.values():
                    for dependency in milestone["dependencies"]:
                        for field in ("planned_date", "projected_date"):
                            self.assertGreaterEqual(milestone[field], milestones[dependency][field])
        for delay in range(8):
            event = dict(self.dataset["events"][1], transit_delay_days=delay)
            plan = generate_plan(self.dataset, event=event)
            self.assertGreaterEqual(self.shipment(plan, "DE")["projected_delivery"], self.shipment(self.baseline, "DE")["projected_delivery"])

    def test_missing_data_temperature_and_capacity_block(self):
        data = deepcopy(self.dataset)
        data["rules"] = [r for r in data["rules"] if not (r["jurisdiction"] == "US" and r["requirement_key"] == "label.languages")]
        self.assertEqual("blocked", self.shipment(generate_plan(data), "US")["risk_band"])
        data = deepcopy(self.dataset)
        for route in data["routes"]:
            if route["jurisdiction"] == "US":
                route["storage_max_c"] = 25
        self.assertFalse(self.shipment(generate_plan(data), "US")["features"]["temperature_compatible"])
        data["config"]["booklet_capacity_pages"] = 1
        self.assertEqual(24, generate_plan(data)["metrics"]["blocked_shipments"])

    def test_replacement_without_source_changes(self):
        replacement = json.loads((ROOT / "data/demo/replacement.json").read_text(encoding="utf-8"))
        self.assertEqual([], validate_dataset(replacement))
        baseline = generate_plan(replacement)
        proposed = generate_plan(replacement, parent=baseline, event=replacement["events"][1])
        self.assertEqual(6, baseline["metrics"]["countries"])
        self.assertEqual(["CL"], [c["country_code"] for c in compare_plans(baseline, proposed)["changes"]])
        self.assertTrue(set(s["country_code"] for s in baseline["shipments"]).isdisjoint(s["country_code"] for s in self.baseline["shipments"]))

    def test_validation_rejects_invalid_research(self):
        rule = self.dataset["rules"][0]
        for changes in ({"source_excerpt": ""}, {"operator": "guess"}, {"review_status": "verified"}, {"effective_to": "2025-01-01"}, {"confidence": 2}, {"value": "ja"}):
            self.assertTrue(validate_rule(dict(rule, **changes)), changes)
        data = deepcopy(self.dataset)
        data["rules"].append(dict(rule, id="duplicate-interval"))
        self.assertTrue(any("Overlapping" in e for e in validate_dataset(data)))

    def test_malformed_nested_inputs_return_errors(self):
        changes = [("config", []), ("trial", []), ("jurisdictions", [None]), ("events", [False]), ("rules", [None])]
        for key, value in changes:
            data = deepcopy(self.dataset)
            data[key] = value
            self.assertTrue(validate_dataset(data))

    def test_data_driven_thresholds_and_storage_event(self):
        data = deepcopy(self.dataset)
        data["config"]["low_slack_days"] = 5
        data["config"]["risk_model"]["synthetic_penalty"] = 15
        plan = generate_plan(data)
        self.assertEqual("at_risk", self.shipment(plan, "GB")["risk_band"])
        self.assertEqual(self.shipment(self.baseline, "GB")["risk_score"] + 10, self.shipment(plan, "GB")["risk_score"])
        event = dict(data["events"][0], id="storage-change", rework_days=0,
                     changes=[{"requirement_key": "storage.maximum_c", "operator": "equals", "value": 5}])
        proposed = generate_plan(data, parent=plan, event=event)
        self.assertFalse(self.shipment(proposed, "JP")["features"]["temperature_compatible"])
        self.assertEqual("blocked", self.shipment(proposed, "JP")["risk_band"])

    def test_new_keys_and_future_events(self):
        event = dict(self.dataset["events"][0], id="template-change", rework_days=0,
                     changes=[{"requirement_key": "label.exclusive_template", "operator": "equals", "value": "local"}])
        plan = generate_plan(self.dataset, parent=self.baseline, event=event)
        group = next(g for g in plan["label_groups"] if "JP" in g["country_codes"])
        self.assertEqual(["JP"], group["country_codes"])
        future = dict(event, effective_from="2027-01-01")
        plan = generate_plan(self.dataset, event=future)
        self.assertEqual([], plan["applied_event_ids"])
        self.assertEqual(self.baseline["shipments"], plan["shipments"])

    def test_event_rule_has_current_provenance_and_effective_intersection(self):
        data = deepcopy(self.dataset)
        event = dict(data["events"][0], retrieved_at="2026-10-18T12:00:00Z", confidence=0.65)
        key = event["changes"][0]["requirement_key"]
        plan = generate_plan(data, event=event)
        derived = next(r for r in plan["rules"] if r["jurisdiction"] == event["jurisdiction"] and r["requirement_key"] == key)
        for field in ("source_excerpt", "source_url", "retrieved_at", "detected_at", "confidence"):
            self.assertEqual(event[field], derived[field])
        self.assertEqual(event["title"], derived["source_title"])
        self.assertEqual(event["effective_from"], derived["effective_from"])
        self.assertEqual("2027-01-15", derived["effective_to"])
        self.assertEqual("official", derived["source_tier"])
        self.assertEqual("needs_review", derived["review_status"])
        self.assertEqual("candidate-JP-label.mandatory_fields-article16", derived["supersedes_id"])
        self.assertIsNone(derived["last_verified_at"])
        self.assertIsNone(derived["source_document_id"])
        data["as_of"] = "2027-01-15"
        later = generate_plan(data, event=event)
        future = next(r for r in later["rules"] if r.get("source_event_id") == event["id"])
        self.assertEqual("2027-01-15", future["effective_from"])
        self.assertEqual(event["effective_from"], future["event_effective_from"])
        self.assertEqual("demo-JP-label.mandatory_fields-v2", future["supersedes_id"])
        self.assertIn("future_study_contact", future["value"])
        self.assertIn("local_contact", future["value"])
        self.assertIsNone(future["effective_to"])
        real_event = dict(event, synthetic=False, source_tier="official", review_status="verified")
        real = generate_plan(self.dataset, event=real_event)
        candidate = next(r for r in real["rules"] if r.get("source_event_id") == event["id"])
        self.assertEqual("official", candidate["source_tier"])
        self.assertEqual("needs_review", candidate["review_status"])

    def test_sparse_malformed_event_returns_validation_error(self):
        data = deepcopy(self.dataset)
        data["events"] = [{"id": "bad", "jurisdiction": "JP", "changes": [{"requirement_key": "label.languages", "operator": "contains_all", "value": ["ja"]}]}]
        self.assertTrue(validate_dataset(data))
        for key, value in (("languages_per_page", 0), ("risk_model", {}), ("booklet_capacity_pages", "eight")):
            data = deepcopy(self.dataset)
            data["config"][key] = value
            self.assertTrue(validate_dataset(data))
        for field, value in (("storage_min_c", "cold"), ("shelf_life_days", 0), ("name", [])):
            data = deepcopy(self.dataset)
            data["trial"]["product"][field] = value
            self.assertTrue(validate_dataset(data))


if __name__ == "__main__":
    unittest.main()
