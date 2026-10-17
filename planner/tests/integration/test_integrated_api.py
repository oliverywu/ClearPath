"""Contract, governance and messaging tests for the integrated /api surface.

Runs the real integrated HTTP server on an ephemeral port with a temporary database.
"""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from apps.api.server import make_server
from apps.api import schemas

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = str(ROOT / 'data/demo/trial_logistics.json')
MAYA, KENJI = 'pho_usr_maya', 'pho_usr_kenji'


class IntegratedCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ.pop('PHOTON_ENABLED', None)
        self.server = make_server('127.0.0.1', 0, os.path.join(self.tmp.name, 'db.sqlite3'), FIXTURE, integrated=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.service = self.server.service

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.service.repo.close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, expect=200):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base + path, data=data, method=method, headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=30) as response:
                status, payload = response.status, json.load(response)
        except HTTPError as exc:
            status, payload = exc.code, json.load(exc)
        self.assertEqual(status, expect, f'{method} {path} -> {status}: {payload}')
        return payload

    get = lambda self, path, expect=200: self.call('GET', path, expect=expect)
    post = lambda self, path, body, expect=200: self.call('POST', path, body, expect)

    def say(self, chat, text, client_id=None):
        return self.post(f'/api/photon/chats/{chat}/messages', {'text': text, 'clientMessageId': client_id})

    def current(self):
        return self.get('/api/current-plan')

    def introduce(self, **overrides):
        event = {'id': 'jp-port-closure', 'title': 'Japan · Narita cargo terminal closure', 'event_type': 'logistics',
                 'jurisdiction': 'JP', 'synthetic': True, 'description': 'Simulated NRT cargo terminal closure adds 6 business days.',
                 'transit_delay_days': 6, 'repair_options': [{'id': 'jp-express', 'action': 'alternative_route', 'route_id': 'demo-JP-express',
                                                              'title': 'Use the priority direct lane', 'description': 'Ship on the express lane.', 'tradeoffs': 'Higher transport cost.'}]}
        event.update(overrides)
        return self.post('/api/change-events', event)


class ContractTests(IntegratedCase):
    ENDPOINTS = [
        ('/api/context', schemas.CONTEXT), ('/api/warnings', schemas.list_of(schemas.WARNING)),
        ('/api/warnings/wrn-jp-label-field', schemas.WARNING_DETAIL), ('/api/warnings/wrn-de-route-delay/options', schemas.list_of(schemas.OPTION)),
        ('/api/shipments', schemas.list_of(schemas.SHIPMENT)), ('/api/inventory', schemas.INVENTORY),
        ('/api/photon/chats', schemas.list_of(schemas.CHAT)), ('/api/photon/chats/max-maya/messages', schemas.list_of(schemas.MESSAGE)),
        ('/api/calendar?month=2026-11', schemas.CALENDAR), ('/api/schedule/2026-11-17', schemas.SCHEDULE),
        ('/api/chalk/insights?date=2026-11-17', schemas.INSIGHT), ('/api/tracking', schemas.list_of(schemas.TRACKING)),
        ('/api/tracking/SHIP-002', schemas.TRACKING), ('/api/proposals', schemas.list_of(schemas.PROPOSAL)),
        ('/api/current-plan', schemas.CURRENT_PLAN), ('/api/audit-history', schemas.list_of(schemas.AUDIT_ENTRY)),
        ('/api/evidence?warningId=wrn-jp-label-field', schemas.list_of(schemas.EVIDENCE)),
        ('/api/evidence?country=JP', schemas.list_of(schemas.EVIDENCE)),
    ]

    def test_every_frontend_endpoint_matches_its_contract(self):
        for path, schema in self.ENDPOINTS:
            with self.subTest(path=path):
                self.assertEqual(schemas.validate(self.get(path), schema), [])

    def test_proposal_detail_and_comparison(self):
        proposal = self.get('/api/proposals')[0]
        self.assertEqual(schemas.validate(self.get(f"/api/proposals/{proposal['id']}"), schemas.PROPOSAL), [])
        comparison = self.get(f"/api/proposals/{proposal['id']}/comparison")
        self.assertEqual(comparison['beforeId'], proposal['parentPlanId'])
        self.assertIn('changes', comparison)

    def test_send_and_decision_contracts(self):
        self.assertEqual(schemas.validate(self.say('max-maya', 'DETAILS', 'c1'), schemas.SEND_RESULT), [])
        option = self.get('/api/warnings/wrn-de-route-delay/options')[0]
        result = self.post(f"/api/proposals/{option['proposalId']}/approve", {'actorId': MAYA, 'actorRole': 'supply_lead', 'rationale': 'Reroute',
                           'channel': 'api', 'idempotencyKey': 'contract-1', 'expectedCurrentPlanId': option['parentPlanId']})
        self.assertEqual(schemas.validate(result, schemas.DECISION_RESULT), [])

    def test_unknown_resources_return_404(self):
        self.get('/api/warnings/wrn-nope', expect=404)
        self.get('/api/tracking/nope', expect=404)
        self.get('/api/proposals/scenario_nope', expect=404)
        self.post('/api/photon/chats/nope/messages', {'text': 'hi'}, expect=404)

    def test_bad_inputs_return_4xx(self):
        self.get('/api/calendar?month=November', expect=422)
        self.get('/api/schedule/not-a-date', expect=422)
        self.post('/api/photon/chats/max-maya/messages', {'text': ''}, expect=422)


class AdapterTests(IntegratedCase):
    def test_shipment_fields_are_renamed_not_recalculated(self):
        plan = self.service.repo.plan(self.current()['planId'])
        canonical = {s['id']: s for s in plan['shipments']}
        for row in self.get('/api/shipments'):
            source = canonical[row['id']]
            self.assertEqual(row['slackDays'], source['slack_days'])
            self.assertEqual(row['targetDelivery'], source['target_delivery'])
            self.assertEqual(row['projectedDelivery'], source['projected_delivery'])
            self.assertEqual(row['labelGroup'], source['label_group_id'])
            self.assertEqual(row['status'], source['risk_band'])
            self.assertEqual(row['shipBy'], source['ship_by'])
            self.assertEqual(row['deliveryRange'], source['delivery_range'])
            self.assertEqual(row['worstCaseSlackDays'], source['worst_case_slack_days'])
            self.assertEqual(row['currentPlanId'], plan['id'])

    def test_warning_and_audit_fields_are_camel_case(self):
        warning = self.get('/api/warnings')[0]
        for key in ('createdAt', 'shipmentIds', 'shipmentsAffected', 'recommendedAction', 'evidenceStatus'):
            self.assertIn(key, warning)
        self.assertFalse(any('_' in key for key in warning))
        entry = self.get('/api/audit-history?limit=5')[0]
        self.assertIn('createdAt', entry)
        self.assertIn('entityId', entry)

    def test_camelize_helper(self):
        from apps.api.frontend import camelize
        self.assertEqual(camelize({'slack_days': 1, 'shipment_ids': ['a'], 'nested': [{'created_at': 'x'}]}),
                         {'slackDays': 1, 'shipmentIds': ['a'], 'nested': [{'createdAt': 'x'}]})


class SchemaValidationTests(unittest.TestCase):
    def test_validator_reports_missing_wrong_type_bad_enum_and_bad_date(self):
        errors = schemas.validate({'id': 1, 'status': 'late', 'targetDelivery': '2026-13-01'}, schemas.SHIPMENT)
        text = ' '.join(errors)
        self.assertIn('$.id: expected string', text)
        self.assertIn("'late' not in", text)
        self.assertIn('not an ISO date', text)
        self.assertIn('$.country: required', text)

    def test_contract_violation_becomes_500_not_bad_data(self):
        from apps.api.schemas import check, ContractError
        with self.assertRaises(ContractError):
            check('GET /x', {'month': '2026-11'}, schemas.CALENDAR)


class GovernanceTests(IntegratedCase):
    def options(self, warning='wrn-jp-port-closure'):
        return self.get(f'/api/warnings/{warning}/options')

    def approve(self, option, actor=MAYA, role='supply_lead', key='k1', expected=None, expect=200):
        return self.post(f"/api/proposals/{option['proposalId']}/approve", {
            'actorId': actor, 'actorRole': role, 'rationale': 'test', 'channel': 'api', 'idempotencyKey': key,
            'expectedCurrentPlanId': expected or option['parentPlanId']}, expect)

    def test_disruption_creates_immutable_proposals_without_touching_current_plan(self):
        before = self.current()
        warning = self.introduce()
        self.assertEqual(warning['status'], 'in_review')
        self.assertEqual(len(warning['proposalIds']), 2)
        self.assertEqual(self.current(), before)
        with self.assertRaises(Exception):
            self.service.repo.db.execute("UPDATE scenarios SET payload='{}' WHERE id=?", (warning['proposalIds'][0],))

    def test_unauthorized_and_role_mismatch_are_refused_and_audited(self):
        self.introduce()
        option = self.options()[0]
        refused = self.approve(option, actor=KENJI, role='affiliate', expect=403)
        self.assertEqual(refused['details']['code'], 'unauthorized')
        self.approve(option, actor=MAYA, role='affiliate', key='k2', expect=403)
        self.approve(option, actor='pho_usr_nobody', role='supply_lead', key='k3', expect=403)
        self.assertEqual(self.current()['version'], 1)
        actions = [a['action'] for a in self.get('/api/audit-history?entityId=' + option['proposalId'])]
        self.assertEqual(actions.count('proposal.approve_refused'), 3)

    def test_approval_moves_pointer_exactly_once_and_is_idempotent(self):
        self.introduce()
        option = self.options()[0]
        first = self.approve(option)
        self.assertEqual((first['beforePlanId'], first['afterPlanId']), (option['parentPlanId'], option['proposalId']))
        self.assertEqual(self.current()['planId'], option['proposalId'])
        self.assertEqual(self.current()['version'], 2)
        replay = self.approve(option)
        self.assertTrue(replay['replayed'])
        self.assertEqual(self.current()['version'], 2)
        changes = [a for a in self.get('/api/audit-history') if a['action'] == 'current_plan.changed']
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['payload']['beforePlanId'], option['parentPlanId'])
        # Same proposal, new key: already decided.
        self.assertEqual(self.approve(option, key='k-new', expected=option['proposalId'], expect=409)['details']['code'], 'already_decided')
        # Key reused for a different proposal.
        other = self.options('wrn-de-route-delay')[0]
        self.assertEqual(self.approve(other, key='k1', expect=409)['details']['code'], 'idempotency_conflict')

    def test_stale_and_conflicting_approvals(self):
        self.introduce()
        jp, de = self.options()[0], self.options('wrn-de-route-delay')[0]
        self.approve(jp)
        # A proposal computed from the old plan is refused even with a fresh expected id.
        stale = self.approve(de, key='k2', expected=jp['proposalId'], expect=409)
        self.assertEqual(stale['details']['code'], 'stale_proposal')
        # Expected plan id that is no longer current is refused.
        self.assertEqual(self.approve(de, key='k3', expect=409)['details']['code'], 'stale_expected_plan')
        # Rebased proposals exist for the still-open event and can be approved.
        fresh = self.options('wrn-de-route-delay')[0]
        self.assertEqual(fresh['parentPlanId'], jp['proposalId'])
        self.approve(fresh, key='k4')
        self.assertEqual(self.current()['version'], 3)
        self.assertEqual(sorted(self.current()['appliedEventIds']), ['de-route-delay', 'jp-port-closure'])

    def test_conflicting_options_for_same_event_only_one_wins(self):
        self.introduce()
        first, second = self.options()
        self.approve(first)
        self.assertEqual(self.approve(second, key='k2', expect=409)['details']['code'], 'stale_expected_plan')
        statuses = {o['proposalId']: o['status'] for o in self.options()}
        self.assertEqual(statuses[first['proposalId']], 'approved')

    def test_rejection_does_not_move_pointer(self):
        self.introduce()
        option = self.options()[0]
        result = self.post(f"/api/proposals/{option['proposalId']}/reject", {'actorId': MAYA, 'actorRole': 'supply_lead',
                           'rationale': 'Too costly', 'channel': 'api', 'idempotencyKey': 'r1'})
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(self.current()['version'], 1)
        self.assertEqual([o['status'] for o in self.options()], ['rejected', 'proposed'])

    def test_unverified_evidence_blocks_approval_until_reviewed(self):
        self.introduce(id='jp-gcp-change', synthetic=False, review_status='needs_review', source_tier='official',
                       source_url='https://laws.e-gov.go.jp/law/409M50000100028', source_excerpt='治験依頼者は',
                       title='Japan · GCP labelling amendment', event_type='regulatory', transit_delay_days=0, rework_days=4,
                       repair_options=[{'id': 'jp-split', 'action': 'split_label', 'title': 'Separate Japan label', 'description': 'Separate artwork for Japan.', 'tradeoffs': 'One more artwork.', 'rework_days': 2}])
        warning = self.get('/api/warnings/wrn-jp-gcp-change')
        self.assertEqual((warning['evidenceStatus'], warning['provenance']), ('needs_review', 'needs_review'))
        option = warning['options'][0]
        self.assertEqual(self.approve(option, expect=422)['details']['code'], 'unverified_evidence')
        self.post('/api/warnings/wrn-jp-gcp-change/evidence/review', {'actorId': KENJI, 'status': 'verified', 'note': 'checked'}, expect=403)
        reviewed = self.post('/api/warnings/wrn-jp-gcp-change/evidence/review', {'actorId': MAYA, 'status': 'verified', 'note': 'Checked e-Gov text'})
        self.assertEqual(reviewed['evidenceStatus'], 'verified')
        self.approve(option, key='k2')
        self.assertEqual(self.get('/api/warnings/wrn-jp-gcp-change')['status'], 'resolved')

    def test_event_without_source_evidence_is_rejected(self):
        self.post('/api/change-events', {'id': 'nosrc', 'title': 'No source', 'event_type': 'logistics', 'jurisdiction': 'JP',
                                         'synthetic': False, 'description': 'x', 'transit_delay_days': 2}, expect=422)

    def test_no_feasible_plan_is_stated(self):
        warning = self.introduce(id='jp-strike', title='Japan · customs strike', transit_delay_days=25, repair_options=[])
        detail = self.get('/api/warnings/wrn-jp-strike')
        self.assertFalse(detail['feasible'])
        self.assertTrue(detail['recommendedAction'].startswith('No option meets every target date'))
        self.assertEqual(warning['severity'], 'critical')
        alert = self.get('/api/photon/chats/max-maya/messages')[-3]['text']
        self.assertIn('No option keeps every affected shipment on its target date', alert)

    def test_legacy_direct_approval_route_is_disabled(self):
        option = self.options('wrn-de-route-delay')[0]
        self.post(f"/api/scenarios/{option['proposalId']}/approve", {'approver': 'x', 'note': 'y'}, expect=410)


class MessagingTests(IntegratedCase):
    def test_required_workflow_over_chat(self):
        before = self.current()
        warning = self.introduce()
        alert = self.get('/api/photon/chats/max-kenji/messages')
        self.assertIn('Narita cargo terminal closure', alert[-3]['text'])
        self.assertEqual(alert[-1]['quickReplies'][:2], ['1', '2'])
        preview = self.say('max-kenji', '1', 'k-1')
        self.assertIn('Nothing has changed yet', preview['replies'][0]['text'])
        self.assertEqual(self.current(), before)
        refused = self.say('max-kenji', 'APPROVE', 'k-2')
        self.assertIn('only an authorized supply lead', refused['replies'][0]['text'])
        self.assertEqual(self.current(), before)
        self.say('max-maya', '1', 'm-1')
        approved = self.say('max-maya', 'APPROVE', 'm-2')
        self.assertIn('version 2', approved['replies'][0]['text'])
        after = self.current()
        self.assertEqual(after['planId'], warning['proposalIds'][0])
        self.assertEqual(self.get('/api/warnings/wrn-jp-port-closure')['status'], 'resolved')
        shipment = next(s for s in self.get('/api/shipments') if s['id'] == 'SHIP-002')
        self.assertEqual(shipment['currentPlanId'], after['planId'])
        # Post-approval notification to the other chat, and once via the notification provider.
        self.assertIn('Plan update: Maya approved option 1', self.get('/api/photon/chats/max-kenji/messages')[-1]['text'])
        notes = self.service.repo.db.execute('SELECT key FROM notifications').fetchall()
        self.assertEqual([n[0] for n in notes], ['approved:' + after['planId']])
        # Replaying the same inbound message changes nothing and returns the original reply.
        replay = self.say('max-maya', 'APPROVE', 'm-2')
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['replies'][0]['id'], approved['replies'][0]['id'])
        self.assertEqual(self.current()['version'], 2)
        self.assertEqual(len(self.service.repo.db.execute('SELECT key FROM notifications').fetchall()), 1)

    def test_conversation_stores_only_proposal_ids(self):
        self.introduce()
        self.say('max-maya', '1', 'm-1')
        self.say('max-maya', 'APPROVE', 'm-2')
        row = dict(self.service.repo.db.execute("SELECT * FROM conversations WHERE key='max-maya:jp-port-closure'").fetchone())
        self.assertEqual(set(row), {'key', 'chat_id', 'event_id', 'status', 'selected_option', 'selected_proposal_id',
                                    'approved_proposal_id', 'created_at', 'updated_at'})
        self.assertEqual(row['approved_proposal_id'], self.current()['planId'])

    def test_stale_selection_in_chat_is_refused_and_reset(self):
        self.introduce()
        self.say('max-kenji', 'DETAILS')
        self.say('max-maya', '1', 'm-1')                       # Maya previews option 1 for JP (parent v1)
        option = self.get('/api/warnings/wrn-de-route-delay/options')[0]
        self.post(f"/api/proposals/{option['proposalId']}/approve", {'actorId': MAYA, 'actorRole': 'supply_lead', 'rationale': 'x',
                  'channel': 'api', 'idempotencyKey': 'api-1', 'expectedCurrentPlanId': option['parentPlanId']})
        reply = self.say('max-maya', 'APPROVE', 'm-2')['replies'][0]
        self.assertIn('superseded', reply['text'])
        self.assertEqual(self.current()['version'], 2)
        self.say('max-maya', '1', 'm-3')
        self.assertIn('version 3', self.say('max-maya', 'APPROVE', 'm-4')['replies'][0]['text'])

    def test_cancel_reject_and_free_text(self):
        self.introduce()
        self.assertIn('Cancelled', self.say('max-maya', 'CANCEL')['replies'][0]['text'])
        self.assertEqual(self.current()['version'], 1)
        self.introduce(id='jp-2', title='Japan · second closure')
        self.say('max-maya', '1')
        rejected = self.say('max-maya', 'REJECT')['replies'][0]
        self.assertIn('Rejected option 1', rejected['text'])
        self.assertEqual(rejected['quickReplies'], ['2'])
        answer = self.say('max-maya', 'When should Japan ship?')['replies'][0]
        self.assertIn('Japan: dispatch by', answer['text'])
        self.assertIn('Grounded planner answer', answer['caption'])


class ProvenanceTests(IntegratedCase):
    def test_synthetic_and_modeled_data_stay_labeled(self):
        warnings = self.get('/api/warnings')
        japan = next(w for w in warnings if w['country'] == 'JP')
        self.assertEqual((japan['provenance'], japan['source']), ('sample', 'Japan GCP Ordinance, Article 16'))
        self.assertTrue(all(w['provenance'] == 'synthetic' for w in warnings if w['country'] != 'JP'))
        shipments = self.get('/api/shipments')
        self.assertEqual(4, sum(s['provenance'] == 'sample' for s in shipments))
        self.assertEqual(20, sum(s['provenance'] == 'synthetic' for s in shipments))
        self.assertTrue(all(s['planningProvenance'] == 'modeled' for s in shipments))
        for row in self.get('/api/tracking'):
            self.assertEqual((row['telemetry'], row['temperatureC'], row['synthetic']), ('none', None, True))
            self.assertTrue(row['statusLabel'].startswith('Planned'))
        inventory = self.get('/api/inventory')
        self.assertEqual((inventory['configured'], len(inventory['items']), inventory['provenance']), (True, 32, 'sample'))
        insight = self.get('/api/chalk/insights?date=2026-11-17')
        self.assertEqual(insight['source']['provider'], 'local')
        self.assertIn('fallback', insight['source']['label'].lower())

    def test_evidence_statuses_use_the_four_lifecycle_values(self):
        statuses = {e['status'] for e in self.get('/api/evidence?country=JP')}
        self.assertTrue(statuses <= {'needs_review', 'verified', 'retired', 'synthetic'})


class ProviderFailureTests(IntegratedCase):
    def test_photon_notification_failure_does_not_block_approval(self):
        from packages.notifications.providers import PhotonNotificationProvider
        self.service.notifications = PhotonNotificationProvider(api_key='k', project_id='p', agent_user_id='a', recipient='+1',
                                                                base_url='https://127.0.0.1:9', timeout=1)
        self.introduce()
        self.say('max-maya', '1', 'm-1')
        self.assertIn('version 2', self.say('max-maya', 'APPROVE', 'm-2')['replies'][0]['text'])
        result = json.loads(self.service.repo.db.execute('SELECT result FROM notifications').fetchone()[0])
        self.assertFalse(result['delivered'])
        self.assertTrue(result['external'])


if __name__ == '__main__':
    unittest.main()
