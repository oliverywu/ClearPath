"""Regression tests for calculations that overlapped across the three planners.

Canonical owner of each result (see docs/integration.md, "Planner feature comparison"):
  * schedule, slack (business days), risk band, label groups, proposals  -> Oliver's engine
  * best/likely/worst delivery, likely/safe ship-by, worst-case slack     -> Chihiro's ranges,
    computed in the engine and mirrored by feature_provider/logistics.py (Chalk resolvers)
  * calendar-day arrival/buffer, risk transitions, conversational preview -> Anna's functions,
    applied to planner shipments as cross-checks; they never produce a schedule themselves.
"""
import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT.parent / 'messaging'))

from packages.planner.engine import generate_plan, business_add, delivery_range, compare_plans  # noqa: E402
from packages.feature_provider import logistics  # noqa: E402
from packages.feature_provider.providers import LocalFeatureProvider, ChalkFeatureProvider  # noqa: E402
import planner_conversation  # noqa: E402
from shipment_planner import calculate_shipment  # noqa: E402
from impact_analyzer import analyze_disruption_impact  # noqa: E402

DATASET = json.loads((ROOT / 'data/demo/trial_logistics.json').read_text(encoding='utf-8'))


def baseline():
    plan = generate_plan(copy.deepcopy(DATASET))
    LocalFeatureProvider().enrich(plan)
    return plan


def with_event(parent, event, repair=None):
    data = copy.deepcopy(DATASET)
    data['events'] = [event]
    plan = generate_plan(data, parent=parent, event=event, repair=repair)
    LocalFeatureProvider().enrich(plan)
    return plan


DELAY_EVENT = {'id': 'reg-delay', 'title': 'Japan · lane delay', 'description': 'Lane delay', 'event_type': 'logistics',
               'jurisdiction': 'JP', 'synthetic': True, 'effective_from': DATASET['as_of'], 'transit_delay_days': 6,
               'source_url': 'https://example.org/x', 'source_excerpt': 'x',
               'repair_options': [{'id': 'express', 'action': 'alternative_route', 'route_id': 'demo-JP-express',
                                   'title': 'Express', 'description': 'x', 'tradeoffs': 'x'}]}


class ArrivalAndBufferRegression(unittest.TestCase):
    """Anna's calculate_shipment vs Oliver's milestone chain."""

    def test_anna_arrival_matches_planner_projection_and_risk_sign(self):
        for shipment in baseline()['shipments']:
            with self.subTest(country=shipment['country_code']):
                anna = calculate_shipment(planner_conversation.anna_record(shipment))
                self.assertEqual(anna['estimated_arrival_date'].isoformat(), shipment['projected_delivery'])
                self.assertEqual(anna['at_risk'], shipment['slack_days'] < 0)
                self.assertEqual(anna['buffer_days'] >= 0, shipment['slack_days'] >= 0)

    def test_disruption_shift_is_business_days_and_anna_transitions_agree(self):
        parent = baseline()
        after = with_event(parent, DELAY_EVENT)
        jp_before = next(s for s in parent['shipments'] if s['country_code'] == 'JP')
        jp_after = next(s for s in after['shipments'] if s['country_code'] == 'JP')
        self.assertEqual(jp_after['projected_delivery'], business_add(jp_before['projected_delivery'], 6, jp_before['features']['calendar_holidays']))
        flipped = {r['shipment_id'] for r in planner_conversation.risk_transitions(parent['shipments'], after['shipments'], 'reg-delay')}
        expected = {s['id'] for s in after['shipments'] for b in parent['shipments']
                    if b['id'] == s['id'] and b['slack_days'] >= 0 and s['slack_days'] < 0}
        self.assertEqual(flipped, expected)

    def test_anna_impact_analyzer_semantics_preserved_for_calendar_days(self):
        record = planner_conversation.anna_record(baseline()['shipments'][0])
        result = analyze_disruption_impact([record], {'event_id': 'E', 'label': 'SIMULATED', 'description': 'x',
                                                      'affected_shipment_ids': [record['shipment_id']], 'additional_delay_days': 3})[0]
        self.assertEqual((result['updated_arrival_date'] - result['original_arrival_date']).days, 3)


class UncertaintyRegression(unittest.TestCase):
    """Chihiro's ranges: engine.delivery_range vs logistics.outlook (Chalk resolvers)."""

    def test_engine_and_chalk_formula_agree_for_every_shipment(self):
        for shipment in baseline()['shipments']:
            with self.subTest(country=shipment['country_code']):
                f = shipment['features']
                values = logistics.outlook(f['dispatch_date'], shipment['target_delivery'], f['leg_ranges_json'],
                                           f['disruption_delay_days'], json.dumps(f['calendar_holidays']))
                self.assertEqual(shipment['delivery_range'], {'best': values['delivery_best_at'], 'likely': values['delivery_likely_at'],
                                                              'worst': values['delivery_worst_at']})
                self.assertEqual(shipment['ship_by'], {'likely': values['ship_by_likely'], 'safe': values['ship_by_safe']})
                self.assertEqual(float(shipment['worst_case_slack_days']), values['worst_case_slack_days'])

    def test_likely_delivery_is_the_main_schedule(self):
        for shipment in baseline()['shipments']:
            self.assertEqual(shipment['delivery_range']['likely'], shipment['projected_delivery'])
            self.assertLessEqual(shipment['delivery_range']['best'], shipment['delivery_range']['likely'])
            self.assertLessEqual(shipment['delivery_range']['likely'], shipment['delivery_range']['worst'])

    def test_safe_ship_by_absorbs_worst_case(self):
        route = {'transit_days': 3, 'customs_days': 2, 'depot_days': 1, 'last_mile_days': 1,
                 'transit_days_range': {'best': 2, 'worst': 6}, 'customs_days_range': {'best': 1, 'worst': 5}}
        result = delivery_range(route, 0, '2026-11-02', '2026-11-30')
        safe = delivery_range(route, 0, result['ship_by']['safe'], '2026-11-30')
        self.assertEqual(safe['worst_case_slack_days'], 0)


class ProposalRegression(unittest.TestCase):
    def test_proposals_are_deterministic_and_parent_unchanged(self):
        parent = baseline()
        snapshot = json.dumps(parent, sort_keys=True)
        first, second = with_event(parent, DELAY_EVENT, 'express'), with_event(parent, DELAY_EVENT, 'express')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(json.dumps(parent, sort_keys=True), snapshot)
        change = next(c for c in compare_plans(parent, first)['changes'] if c['country_code'] == 'JP')
        self.assertEqual(change['after']['route_id'], 'demo-JP-express')


class ChalkParity(unittest.TestCase):
    def test_matching_chalk_response_is_used_and_changes_nothing(self):
        local = baseline()

        class Fake(ChalkFeatureProvider):
            def authenticate(self):
                self.token = 't'

            def _post(self, url, payload, token=None):
                shipment = next(s for s in local['shipments'] if s['id'] == payload['inputs']['shipment.id'])
                return {'data': {key: shipment['features'][key.split('.', 1)[1]] for key in payload['outputs']}, 'meta': {'query_id': 'q'}}
        plan = generate_plan(copy.deepcopy(DATASET))
        Fake().enrich(plan)
        self.assertEqual(plan['provider']['active'], 'chalk')
        for a, b in zip(plan['shipments'], local['shipments']):
            self.assertEqual((a['projected_delivery'], a['slack_days'], a['ship_by']), (b['projected_delivery'], b['slack_days'], b['ship_by']))
            self.assertEqual(a['features']['agent_answer'], b['features']['agent_answer'])

    def test_mismatching_or_failing_chalk_falls_back_without_changing_results(self):
        local = baseline()

        class Wrong(ChalkFeatureProvider):
            def authenticate(self):
                self.token = 't'

            def _post(self, url, payload, token=None):
                return {'data': {key: 'wrong' for key in payload['outputs']}}

        class Down(ChalkFeatureProvider):
            def authenticate(self):
                raise OSError('unreachable')
        for provider in (Wrong(), Down()):
            plan = generate_plan(copy.deepcopy(DATASET))
            provider.enrich(plan)
            self.assertEqual(plan['provider']['active'], 'local')
            self.assertTrue(plan['provider']['fallback'])
            for a, b in zip(plan['shipments'], local['shipments']):
                self.assertEqual(a['features']['agent_answer'], b['features']['agent_answer'])
                self.assertEqual(a['features']['ship_by_safe'], b['features']['ship_by_safe'])


class AnnaPlannerFormulaCopies(unittest.TestCase):
    def test_anna_record_uses_planner_dispatch_and_target(self):
        shipment = baseline()['shipments'][0]
        record = planner_conversation.anna_record(shipment)
        dispatch = next(m['projected_date'] for m in shipment['milestones'] if m['type'] == 'dispatch')
        self.assertEqual(record['shipping_date'], dispatch)
        self.assertEqual(record['required_delivery_date'], shipment['target_delivery'])
        self.assertEqual(date.fromisoformat(record['shipping_date']).toordinal() + record['estimated_transit_days'],
                         date.fromisoformat(shipment['projected_delivery']).toordinal())


if __name__ == '__main__':
    unittest.main()
