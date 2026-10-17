import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from apps.api.service import Service, APIError, ROOT
from apps.api.server import make_server
from packages.feature_provider.providers import LocalFeatureProvider, ChalkFeatureProvider
from packages.feature_provider.formulas import effective_transit, projected_delivery, delivery_slack, risk_score, risk_band
from packages.ingestion.adapters import GenericPageAdapter, EgovLawAdapter, parse_records
from packages.notifications.providers import PhotonNotificationProvider
from packages.calendar.providers import GoogleCalendarProvider, OutlookCalendarProvider
from packages.assistant.providers import OpenAIAssistantProvider
from packages.research.providers import OpenAIResearchProvider


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = Service(':memory:')
        self.base = self.service.bootstrap()['approved_scenario']

    def tearDown(self):
        self.service.repo.close()

    def post(self,path,body=None):
        return self.service.handle('POST',path,body=body or {})

    def analyze(self,index=0,parent=None,repair=None):
        event = self.service.repo.events()[index]
        return self.post('/api/change-events/'+event['id']+'/analyze',{'parent_scenario_id':parent or self.base['id'],'repair':repair})

    def test_seed_country_coverage_and_approval(self):
        self.assertGreaterEqual(len(self.base['shipments']),20)
        self.assertEqual(self.base['status'],'approved')
        audit = self.service.handle('GET','/api/audit')['events']
        self.assertTrue(any(e['action']=='scenario.approved' and e['actor']=='demo seed' for e in audit))

    def test_event_compare_human_approve_immutable_payload(self):
        proposal = self.analyze()
        self.assertEqual(proposal['status'],'proposed')
        self.assertEqual(self.service.bootstrap()['approved_scenario']['id'],self.base['id'])
        comparison = self.service.handle('GET',f"/api/scenarios/{self.base['id']}/compare/{proposal['id']}")
        self.assertGreater(comparison['summary']['changed_countries'],0)
        approved = self.post('/api/scenarios/'+proposal['id']+'/approve',{'approver':'Reviewer','note':'Reviewed synthetic scenario and evidence'})
        self.assertEqual(approved['status'],'approved')
        self.assertEqual(approved['content_hash'],proposal['content_hash'])
        self.assertEqual(self.service.repo.plan(self.base['id'])['content_hash'],self.base['content_hash'])
        self.assertEqual(self.service.bootstrap()['approved_scenario']['id'],proposal['id'])
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.repo.db.execute('UPDATE scenarios SET payload=? WHERE id=?',('{}',self.base['id']))

    def test_approval_requires_identity_and_note(self):
        proposal = self.analyze()
        with self.assertRaises(APIError):
            self.post('/api/scenarios/'+proposal['id']+'/approve',{'approver':'Reviewer'})
        self.assertEqual(self.service.repo.plan(proposal['id'])['status'],'proposed')

    def test_rejection_does_not_replace_baseline(self):
        proposal = self.analyze()
        rejected = self.post('/api/scenarios/'+proposal['id']+'/reject',{'approver':'Reviewer','note':'Try alternate route'})
        self.assertEqual(rejected['status'],'rejected')
        self.assertEqual(self.service.bootstrap()['approved_scenario']['id'],self.base['id'])
        with self.assertRaises(APIError):
            self.post('/api/scenarios/'+proposal['id']+'/approve',{'approver':'Reviewer','note':'Second decision'})

    def test_cumulative_events_and_repairs(self):
        one = self.analyze()
        two = self.analyze(1,parent=one['id'])
        self.assertEqual(len(two['applied_event_ids']),2)
        events = self.service.repo.events()
        repair = events[0]['repair_options'][0]['id']
        repaired = self.analyze(parent=two['id'],repair=repair)
        self.assertEqual(len(repaired['applied_event_ids']),2)
        self.assertEqual(repaired['selected_repairs'][events[0]['id']],repair)

    def test_custom_event_cumulative(self):
        seed = self.service.repo.events()[0]
        event = self.post('/api/change-events',{'title':'Custom delay','event_type':'logistics','jurisdiction':seed['jurisdiction'],'transit_delay_days':2})
        one = self.post('/api/change-events/'+event['id']+'/analyze')
        two = self.analyze(1,parent=one['id'])
        self.assertIn(event['id'],two['applied_event_ids'])

    def test_invalid_event_values_and_repairs_are_not_persisted(self):
        events = self.service.repo.events()
        base = {'title':'Invalid event','event_type':'regulatory','jurisdiction':events[0]['jurisdiction']}
        invalid_cases = [
            {'changes':[{'requirement_key':'label.languages','operator':'contains_all','value':17}]},
            {'changes':[{'requirement_key':'permit.lead_time_business_days','operator':'equals','value':-3}]},
            {'repair_options':[{'id':'bad-route','title':'Bad route','description':'Invalid route','tradeoffs':'None','action':'alternative_route','route_id':'nonexistent'}]},
            {'transit_delay_days':1.5},
            {'effective_from':'not-a-date'},
            {'synthetic':False},
        ]
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid), self.assertRaises(APIError) as raised:
                self.post('/api/change-events',{**base,**invalid})
            self.assertEqual(raised.exception.status,422)
            self.assertEqual(len(self.service.repo.events()),len(events))

    def test_review_regenerates_proposal_and_preserves_approved_baseline(self):
        rule = self.service.repo.dataset()['rules'][0]
        reviewed = self.post('/api/rules/'+rule['id']+'/review',{'reviewer':'Human reviewer','note':'Evidence requires further review','status':'needs_review'})
        self.assertNotEqual(reviewed['id'],rule['id'])
        self.assertEqual(reviewed['review_status'],'needs_review')
        proposal = self.service.repo.plan(reviewed['scenario_id'])
        self.assertEqual(proposal['status'],'proposed')
        self.assertEqual(proposal['parent_scenario_id'],self.base['id'])
        self.assertEqual(self.service.bootstrap()['approved_scenario']['content_hash'],self.base['content_hash'])

    def test_requirements_preserve_event_evidence_and_baseline_versions(self):
        event = self.service.repo.events()[0]
        proposal = self.analyze()
        self.post('/api/scenarios/'+proposal['id']+'/approve',{'approver':'Human','note':'Reviewed event proposal'})
        requirements = self.service.requirements(event['jurisdiction'],self.base['as_of'])['requirements']
        derived = [r for r in requirements if r.get('scenario_assumption')]
        self.assertTrue(derived)
        self.assertTrue(all(r['source_excerpt']==event['source_excerpt'] for r in derived))
        refs = set(proposal['evidence_refs'])
        self.assertTrue(all(r['id'] in refs for r in derived))
        baseline = self.service.requirements(event['jurisdiction'],self.base['as_of'],self.base['id'])['requirements']
        self.assertFalse(any(r.get('scenario_assumption') for r in baseline))

    def test_japan_article_16_candidates_are_linked_and_review_gated(self):
        requirements = self.service.requirements('JP', self.base['as_of'])['requirements']
        candidates = [r for r in requirements if r['id'].startswith('candidate-JP-')]
        self.assertEqual(6, len(candidates))
        self.assertTrue(all(r['source_tier'] == 'official' for r in candidates))
        self.assertTrue(all(r['review_status'] == 'needs_review' for r in candidates))
        self.assertTrue(all(r['source_url'].startswith('https://laws.e-gov.go.jp/law/409M50000100028') for r in candidates))
        self.assertTrue(all(r['source_excerpt'] for r in candidates))
        self.assertTrue(all(not r['active'] for r in candidates))
        keys = {r['requirement_key'] for r in candidates}
        self.assertEqual({
            'label.mandatory_fields', 'label.prohibited_fields', 'label.sponsor_constraint',
            'label.blinding_constraint', 'packaging.integrity_constraint', 'documents.required'
        }, keys)

    def test_calendar_gate_and_crlf(self):
        proposal = self.analyze()
        with self.assertRaises(APIError):
            self.service.handle('GET','/api/scenarios/'+proposal['id']+'/calendar.ics')
        kind,ical = self.service.handle('GET','/api/scenarios/'+self.base['id']+'/calendar.ics')
        self.assertIn('text/calendar',kind)
        self.assertTrue(ical.startswith('BEGIN:VCALENDAR\r\n'))
        self.assertEqual(ical.count('BEGIN:VEVENT'),sum(len(s['milestones']) for s in self.base['shipments']))
        self.assertTrue(all(len(line.encode())<=75 for line in ical.split('\r\n')))

    def test_assistant_read_only_cited_and_synthetic(self):
        result = self.post('/api/assistant/query',{'question':'Why are shipments at risk?','scenario_id':self.base['id']})
        self.assertTrue(result['citations'])
        self.assertIn('synthetic',result['answer'])
        result = self.post('/api/assistant/query',{'question':'Approve this plan','scenario_id':self.base['id']})
        self.assertIn('cannot approve',result['answer'])
        self.assertEqual(self.service.repo.plan(self.base['id'])['content_hash'],self.base['content_hash'])

    def test_assistant_country_name_does_not_match_common_word_as_code(self):
        proposal = self.analyze()
        result = self.post('/api/assistant/query',{'question':'Why is Argentina at risk?','scenario_id':proposal['id']})
        self.assertIn('Argentina is',result['answer'])
        self.assertNotIn('Austria is',result['answer'])
        self.assertNotIn('1 business days',result['answer'])
        self.assertEqual(result['answer'].count('Primary scenario drivers:'),1)

    def test_assistant_accepts_explicit_uppercase_country_code(self):
        result = self.post('/api/assistant/query',{'question':'Why is DE at risk?','scenario_id':self.base['id']})
        self.assertIn('Germany is',result['answer'])

    def test_assistant_describes_negative_slack_as_late_without_repetition(self):
        proposal = self.analyze()
        result = self.post('/api/assistant/query',{'question':'Why is Japan blocked?','scenario_id':proposal['id']})
        self.assertIn('2 business days late',result['answer'])
        self.assertNotIn('-2 business days',result['answer'])
        self.assertEqual(result['answer'].lower().count('misses target'),0)

    def test_conversational_what_if_is_calculated_and_never_persisted(self):
        before = len(self.service.repo.plans(self.base['trial_id']))
        result = self.post('/api/assistant/query',{'question':'What if Japan receives a separate label?','scenario_id':self.base['id']})
        self.assertTrue(result['temporary_scenario']['ephemeral'])
        self.assertFalse(result['temporary_scenario']['persisted'])
        self.assertEqual(result['temporary_scenario']['status'],'temporary')
        self.assertTrue(result['comparison']['changes'])
        self.assertIn('Cost proxy:',result['answer'])
        self.assertEqual(len(self.service.repo.plans(self.base['trial_id'])),before)
        with self.assertRaises(KeyError):
            self.service.repo.plan(result['temporary_scenario']['id'])

    def test_conversational_what_if_rejects_unsupported_action(self):
        with self.assertRaises(APIError) as raised:
            self.post('/api/assistant/query',{'question':'What if Germany uses a helicopter?','scenario_id':self.base['id']})
        self.assertEqual(raised.exception.status,422)

    def test_invalid_import_and_verified_synthetic_rejected(self):
        row = copy.deepcopy(self.service.repo.dataset()['rules'][0])
        row['id'] = 'bad-rule'
        row['review_status'] = 'verified'
        row['source_tier'] = 'synthetic'
        preview = self.post('/api/rules/import/preview',{'records':[row]})
        self.assertFalse(preview['valid'])
        with self.assertRaises(APIError):
            self.post('/api/rules/import/commit',{'preview_id':preview['preview_id'],'reviewer':'Human'})

    def test_import_versions_and_replay_prevention(self):
        row = copy.deepcopy(self.service.repo.dataset()['rules'][0])
        row.update(id='new-rule',supersedes_id=row['id'],effective_from='2027-01-01',effective_to=None)
        preview = self.post('/api/rules/import/preview',{'records':[row]})
        self.assertTrue(preview['valid'],preview['errors'])
        committed = self.post('/api/rules/import/commit',{'preview_id':preview['preview_id'],'reviewer':'Human'})
        self.assertEqual(committed['status'],'proposed')
        self.assertEqual(self.service.bootstrap()['approved_scenario']['id'],self.base['id'])
        with self.assertRaises(APIError):
            self.post('/api/rules/import/commit',{'preview_id':preview['preview_id'],'reviewer':'Human'})

    def test_stale_preview_rejected(self):
        replacement = json.loads((ROOT/'data/demo/replacement.json').read_text())
        a = self.post('/api/datasets/import/preview',{'dataset':replacement})
        b = self.post('/api/datasets/import/preview',{'dataset':replacement})
        self.post('/api/datasets/import/commit',{'preview_id':a['preview_id'],'reviewer':'Human'})
        with self.assertRaises(APIError):
            self.post('/api/datasets/import/commit',{'preview_id':b['preview_id'],'reviewer':'Human'})

    def test_replacement_fixture_data_driven(self):
        replaced = self.post('/api/demo/reset',{'fixture':'replacement'})
        new = replaced['approved_scenario']
        self.assertNotEqual(new['trial_id'],self.base['trial_id'])
        self.assertNotEqual(new['shipments'][0]['country_code'],self.base['shipments'][0]['country_code'])
        event = replaced['events'][0]
        proposal = self.post('/api/change-events/'+event['id']+'/analyze')
        self.assertTrue(self.service.handle('GET',f"/api/scenarios/{new['id']}/compare/{proposal['id']}")['changes'])
        self.assertEqual(self.service.repo.plan(self.base['id'])['content_hash'],self.base['content_hash'])

    def test_snapshot_change_detected_and_review_gated(self):
        a = self.post('/api/sources/snapshot',{'source_id':'page','content':'A first source'})
        b = self.post('/api/sources/snapshot',{'source_id':'page','content':'A new source'})
        self.assertFalse(a['changed'])
        self.assertTrue(b['changed'])
        self.assertEqual(b['review_status'],'needs_review')
        with self.assertRaises(APIError):
            self.post('/api/change-events/'+b['event_id']+'/analyze')

    def test_alert_acknowledgement(self):
        proposal = self.analyze()
        alert = self.service.alerts()[0]
        self.post('/api/alerts/'+alert['id']+'/acknowledge',{'actor':'Reviewer'})
        self.assertTrue(next(a for a in self.service.alerts() if a['id']==alert['id'])['acknowledged'])

    def test_future_requirements_flagged(self):
        rules = self.service.repo.dataset()['rules']
        future = next(r for r in rules if r['effective_from']>self.base['as_of'])
        result = self.service.requirements(future['jurisdiction'],self.base['as_of'])
        self.assertTrue(next(r for r in result['requirements'] if r['id']==future['id'])['future_effective'])

    def test_focused_official_evidence_slice_is_cited_and_verified(self):
        rules = self.service.repo.dataset()['rules']
        expected_hosts = {'US':'fda.gov','DE':'eur-lex.europa.eu','CA':'laws-lois.justice.gc.ca','JP':'laws.e-gov.go.jp'}
        for country,host in expected_hosts.items():
            verified = [r for r in rules if r['jurisdiction']==country and r['review_status']=='verified']
            self.assertTrue(verified,country)
            self.assertTrue(all(r['source_tier']=='official' for r in verified))
            self.assertTrue(all(host in r['source_url'] for r in verified))
            self.assertTrue(all(r['source_excerpt'] and r['last_verified_at'] for r in verified))

    def test_review_synthetic_evidence_cannot_be_verified(self):
        rule = next(r for r in self.service.repo.dataset()['rules'] if r['source_tier']=='synthetic')
        with self.assertRaises(APIError):
            self.post('/api/rules/'+rule['id']+'/review',{'reviewer':'Human','note':'Review','status':'verified'})

    def test_source_candidates_are_forced_to_needs_review(self):
        result = self.post('/api/sources/snapshot',{'source_id':'candidate','content':'Evidence','records':[{'review_status':'verified'}]})
        self.assertEqual(result['candidate_rules'][0]['review_status'],'needs_review')

    def test_import_summary_and_duplicate_conflict(self):
        row = copy.deepcopy(self.service.repo.dataset()['rules'][0])
        row.update(id='summary-rule',review_status='needs_review')
        preview = self.post('/api/rules/import/preview',{'records':[row]})
        self.assertEqual(preview['summary']['records'],1)
        self.assertEqual(preview['summary']['jurisdictions'],1)
        duplicate = self.post('/api/rules/import/preview',{'records':[row,{**row,'id':'summary-rule-2'}]})
        self.assertFalse(duplicate['valid'])
        self.assertTrue(duplicate['summary']['conflicts'])

    def test_source_registry_and_check(self):
        registry = self.service.handle('GET','/api/sources')['sources']
        cited_urls = {r['source_url'] for r in self.service.repo.dataset()['rules']}
        managed_urls = {s['url'] for s in registry if s.get('managed_by') == 'dataset'}
        self.assertTrue(cited_urls.issubset(managed_urls))
        japan = next(s for s in registry if s.get('url','').startswith('https://laws.e-gov.go.jp/law/409M50000100028'))
        self.assertEqual('official', japan['source_tiers'][0])
        self.assertIn('label.mandatory_fields', japan['requirement_keys'])
        source = self.post('/api/sources',{'title':'Official page','url':'https://official.example/rule','adapter':'generic'})
        self.assertIn(source['id'],[s['id'] for s in self.service.handle('GET','/api/sources')['sources']])
        with patch('packages.ingestion.adapters.GenericPageAdapter.fetch',return_value='Official evidence'):
            checked = self.post('/api/sources/'+source['id']+'/check')
        self.assertFalse(checked['changed'])
        self.assertEqual(checked['review_status'],'needs_review')

    def test_unreliable_regulatory_links_migrate_to_checkable_official_text(self):
        dataset = self.service.repo.dataset()
        japan = next(r for r in dataset['rules'] if r.get('jurisdiction') == 'JP' and r.get('requirement_key') == 'label.languages')
        japan_article = next(r for r in dataset['rules'] if r.get('id') == 'candidate-JP-label.mandatory_fields-article16')
        canada = next(r for r in dataset['rules'] if r.get('jurisdiction') == 'CA' and r.get('requirement_key') == 'label.languages')
        old_url = 'https://www.mhlw.go.jp/file/04-Houdouhappyou-11123000-Iyakushokuhinkyoku-Shinsakanrika/0000190647.pdf'
        legacy_mhlw = 'https://www.mhlw.go.jp/web/t_doc?dataId=81997396&dataType=0&pageNo=1#article16'
        legacy_canada = 'https://www.canada.ca/en/health-canada/services/drugs-health-products/compliance-enforcement/good-clinical-practices/guidance-documents/guidance-drugs-clinical-trials-human-subjects-gui-0100/labelling-records.html'
        japan['source_url'] = old_url
        japan['source_title'] = 'MHLW: Ministerial Ordinance on Good Clinical Practice for Drugs (English translation)'
        japan['source_excerpt'] = 'A sponsor shall indicate the following information in the Japanese language on the container or package of the investigational products'
        japan['notes'] = 'Legacy fixture source.'
        japan_article['source_url'] = legacy_mhlw
        japan_article['source_title'] = 'MHLW: Ministerial Ordinance on Good Clinical Practice for Drugs, Article 16(1)'
        canada['source_url'] = legacy_canada
        canada['source_title'] = 'Health Canada GUI-0100: Labelling and records'
        canada['source_excerpt'] = 'This information must be provided in both official languages.'
        canada['notes'] = 'Legacy fixture source.'
        self.service.repo.save_dataset(dataset)
        self.service.sync_sources(dataset)
        legacy_jp = next(s for s in self.service.repo.sources() if s.get('url') == old_url)
        legacy_mhlw_source = next(s for s in self.service.repo.sources() if s.get('url') == legacy_mhlw)
        legacy_ca = next(s for s in self.service.repo.sources() if s.get('url') == legacy_canada)

        self.assertTrue(self.service.migrate_legacy_official_sources())
        migrated = self.service.repo.dataset()
        updated_jp = next(r for r in migrated['rules'] if r['id'] == japan['id'])
        updated_ca = next(r for r in migrated['rules'] if r['id'] == canada['id'])
        self.assertIn('laws.e-gov.go.jp/law/409M50000100028', updated_jp['source_url'])
        self.assertIn('laws-lois.justice.gc.ca', updated_ca['source_url'])
        self.assertIn('both official languages', updated_ca['source_excerpt'])
        self.assertIn('邦文で記載', updated_jp['source_excerpt'])
        replaced_jp = next(s for s in self.service.repo.sources() if s['id'] == legacy_jp['id'])
        replaced_mhlw = next(s for s in self.service.repo.sources() if s['id'] == legacy_mhlw_source['id'])
        replaced_ca = next(s for s in self.service.repo.sources() if s['id'] == legacy_ca['id'])
        self.assertFalse(replaced_jp['enabled'])
        self.assertTrue(replaced_jp['superseded_by_source_id'])
        self.assertFalse(replaced_mhlw['enabled'])
        self.assertTrue(replaced_mhlw['superseded_by_source_id'])
        self.assertFalse(replaced_ca['enabled'])
        self.assertTrue(replaced_ca['superseded_by_source_id'])
        current_jp = next(s for s in self.service.repo.sources() if s['url'] == updated_jp['source_url'])
        self.assertEqual(current_jp['adapter'],'egov')
        self.assertFalse(self.service.migrate_legacy_official_sources(), 'Migration should be idempotent')

    def test_startup_migration_supersedes_stale_registry_when_dataset_is_already_updated(self):
        # This is the partial-migration state found in a user's persisted database:
        # rule citations and replacement sources are current, but the old registry
        # rows remain enabled and visible with fetch errors.
        legacy_urls = [
            'https://www.canada.ca/en/health-canada/services/drugs-health-products/compliance-enforcement/good-clinical-practices/guidance-documents/guidance-drugs-clinical-trials-human-subjects-gui-0100/labelling-records.html',
            'https://www.mhlw.go.jp/file/04-Houdouhappyou-11123000-Iyakushokuhinkyoku-Shinsakanrika/0000190647.pdf',
            'https://www.mhlw.go.jp/web/t_doc?dataId=81997396&dataType=0&pageNo=1',
        ]
        for index, url in enumerate(legacy_urls):
            self.service.repo.save_source({
                'id':f'legacy-stale-{index}', 'title':f'Legacy source {index}',
                'url':url, 'enabled':True, 'last_check_error':'stale failure'
            })

        self.assertTrue(self.service.migrate_legacy_official_sources())
        sources = {source['id']:source for source in self.service.repo.sources()}
        for index in range(len(legacy_urls)):
            source = sources[f'legacy-stale-{index}']
            self.assertFalse(source['enabled'])
            self.assertTrue(source['superseded_by_source_id'])
            self.assertIsNone(source.get('last_check_error'))
        self.assertFalse(self.service.migrate_legacy_official_sources(), 'Registry-only migration should be idempotent')

    def test_recalculate_freshness_check_detects_changes_and_skips_synthetic_sources(self):
        source = self.post('/api/sources',{'title':'Official change test','url':'https://official.example/change','adapter':'generic'})
        self.post('/api/sources/snapshot',{'source_id':source['id'],'content':'Old official text'})
        with patch('packages.ingestion.adapters.GenericPageAdapter.fetch',return_value='New official text') as fetch:
            result = self.post('/api/sources/check-all')
        self.assertGreater(result['checked'],0)
        self.assertEqual(result['changed'],1)
        self.assertEqual(result['failed'],0)
        self.assertTrue(all('cleared-synthetic' not in call.args[0] for call in fetch.call_args_list))
        refreshed = next(s for s in self.service.repo.sources() if s['id']==source['id'])
        self.assertTrue(refreshed['last_check_changed'])
        self.assertIsNone(refreshed['last_check_error'])

    def test_recalculate_freshness_check_reports_unreachable_sources(self):
        self.post('/api/sources',{'title':'Unreachable test','url':'https://official.example/unreachable','adapter':'generic'})
        with patch('packages.ingestion.adapters.GenericPageAdapter.fetch',side_effect=TimeoutError('timed out')):
            result = self.post('/api/sources/check-all')
        self.assertGreater(result['failed'],0)
        self.assertEqual(result['failed'],result['checked'])

    def test_ai_research_extracts_exact_quote_needs_review_candidates(self):
        source = self.post('/api/sources',{'title':'Official regulation','url':'https://official.example/rule','adapter':'generic','jurisdiction':'DE'})
        text = 'Sponsors must include the protocol number on the outer label.'
        self.post('/api/sources/snapshot',{'source_id':source['id'],'content':text,'jurisdiction':'DE'})
        class FakeResearch:
            name, model = 'test-ai', 'test-model'
            def extract(self, **kwargs):
                return {'document_note':'One supported rule','candidates':[{
                    'rule_type':'label','requirement_key':'label.mandatory_fields','operator':'contains_all',
                    'value':['protocol_number'],'effective_from':'2026-10-17','effective_to':None,
                    'source_excerpt':text,'confidence':0.91,'ambiguity_note':'None',
                }]}
        self.service.research = FakeResearch()
        result = self.post('/api/research/extract',{'source_id':source['id']})
        self.assertTrue(result['valid'],result['errors'])
        self.assertEqual(result['candidates'][0]['review_status'],'needs_review')
        self.assertEqual(result['candidates'][0]['source_excerpt'],text)
        preview = self.post('/api/rules/import/preview',{'records':result['candidates']})
        self.assertTrue(preview['valid'],preview['errors'])

    def test_ai_research_rejects_hallucinated_quote(self):
        source = self.post('/api/sources',{'title':'Official regulation','url':'https://official.example/rule','adapter':'generic','jurisdiction':'DE'})
        self.post('/api/sources/snapshot',{'source_id':source['id'],'content':'Actual text','jurisdiction':'DE'})
        class FakeResearch:
            name = 'test-ai'
            def extract(self, **kwargs):
                return {'document_note':'','candidates':[{'rule_type':'label','requirement_key':'label.expiry_format','operator':'equals','value':'YYYY-MM','effective_from':'2026-10-17','effective_to':None,'source_excerpt':'Invented quote','confidence':0.5,'ambiguity_note':'uncertain'}]}
        self.service.research = FakeResearch()
        result = self.post('/api/research/extract',{'source_id':source['id']})
        self.assertFalse(result['valid'])
        self.assertFalse(result['candidates'])
        self.assertIn('verbatim',result['errors'][0]['message'])

    def test_ai_change_analysis_requires_human_confirmation(self):
        source = self.post('/api/sources',{'title':'Official regulation','url':'https://official.example/rule','adapter':'generic','jurisdiction':'DE'})
        self.post('/api/sources/snapshot',{'source_id':source['id'],'content':'Permit review takes 10 business days.','jurisdiction':'DE'})
        self.post('/api/sources/snapshot',{'source_id':source['id'],'content':'Permit review takes 20 business days.','jurisdiction':'DE'})
        class FakeResearch:
            name, model = 'test-ai', 'test-model'
            def compare(self, **kwargs):
                return {'summary':'Permit review increased by ten business days.','materiality':'material',
                        'affected_jurisdictions':['DE'],'likely_requirement_keys':['permit.lead_time_business_days'],
                        'old_excerpt':'Permit review takes 10 business days.','new_excerpt':'Permit review takes 20 business days.',
                        'ambiguity_note':'Human must confirm applicability.','event':{
                            'title':'German permit review extension','description':'Permit review lead time increased.',
                            'effective_from':'2026-10-17','changes':[{'requirement_key':'permit.lead_time_business_days','operator':'equals','value':20}]}}
        self.service.research = FakeResearch()
        analysis = self.post('/api/sources/'+source['id']+'/analyze-change')
        self.assertTrue(analysis['valid'])
        self.assertTrue(analysis['raw_diff'])
        self.assertFalse(any(e.get('source_analysis_id')==analysis['analysis_id'] for e in self.service.repo.events()))
        with self.assertRaises(APIError):
            self.post('/api/change-analyses/'+analysis['analysis_id']+'/confirm',{'reviewer':'Reviewer'})
        event = self.post('/api/change-analyses/'+analysis['analysis_id']+'/confirm',{'reviewer':'Reviewer','note':'Confirmed against both cited snapshots'})
        self.assertEqual(event['review_status'],'confirmed')
        self.assertEqual(event['raw_diff'],analysis['raw_diff'])
        proposal = self.post('/api/change-events/'+event['id']+'/analyze')
        self.assertEqual(proposal['trigger_event_id'],event['id'])


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.service = Service(':memory:')
        self.shipment = self.service.bootstrap()['approved_scenario']['shipments'][0]

    def tearDown(self):
        self.service.repo.close()

    def test_chalk_resolves_primitives_and_parity(self):
        provider = ChalkFeatureProvider()
        def remote(url,payload,token=None):
            inputs = payload['inputs']
            self.assertFalse(set(payload['outputs']) & set(inputs))
            f = {k.split('.',1)[1]:v for k,v in inputs.items()}
            projected = projected_delivery(f['ready_date'],f['duration_days_json'],f['holidays_json'])
            slack = delivery_slack(projected,f['target_delivery'],f['holidays_json'])
            values = {'projected_delivery_at':projected,'slack_days':slack,'effective_transit_days':effective_transit(f['baseline_transit_days'],f['disruption_delay_days'],f['customs_buffer_days']),'risk_score':risk_score(slack,f['constraint_blocked'],f['synthetic_count'],f['risk_model_json']),'risk_band':risk_band(slack,f['constraint_blocked'],f['low_slack_days'])}
            return {'data':[{'field':'shipment.'+k,'value':v} for k,v in values.items()],'meta':{'query_id':'test-query'}}
        with patch.object(provider,'authenticate'), patch.object(provider,'_post',side_effect=remote):
            result = provider.shipment(self.shipment,'2026-10-17')
        self.assertEqual(result['provider'],'chalk')
        self.assertEqual(result['features'],LocalFeatureProvider().shipment(self.shipment,'2026-10-17')['features'])

    def test_chalk_failure_explicit_local_fallback(self):
        provider = ChalkFeatureProvider()
        with patch.object(provider,'authenticate',side_effect=TimeoutError):
            result = provider.shipment(self.shipment)
        self.assertEqual(result['provider'],'local')
        self.assertTrue(result['fallback_reason'])

    def test_scraped_candidates_cannot_self_verify(self):
        candidates = GenericPageAdapter().normalize_candidate_rules([{'review_status':'verified','source_excerpt':'Text'}])
        self.assertEqual(candidates[0]['review_status'],'needs_review')

    def test_egov_adapter_fetches_law_api_from_official_page_url(self):
        url = 'https://laws.e-gov.go.jp/law/409M50000100028'
        with patch.object(GenericPageAdapter,'fetch',return_value='official law data') as fetch:
            self.assertEqual(EgovLawAdapter().fetch(url),'official law data')
        fetch.assert_called_once_with('https://laws.e-gov.go.jp/api/2/law_data/409M50000100028')
        with self.assertRaises(ValueError):
            EgovLawAdapter().fetch('https://attacker.example/law/409M50000100028')

    def test_photon_stub_is_honest(self):
        result = PhotonNotificationProvider().send({'id':'test'})
        self.assertFalse(result['delivered'])

    def test_photon_sends_user_space_and_message_with_idempotency(self):
        provider = PhotonNotificationProvider(api_key='secret',project_id='project',agent_user_id='agent',recipient='+14155550123')
        responses = [(201,{'id':'user'}),(201,{'id':'space'}),(202,{'id':'message'})]
        with patch.object(provider,'_post',side_effect=responses) as post:
            result = provider.send({'id':'review:scenario','title':'Review change','cause':'Weather delay','consequence':'Germany is late','review_status':'proposed','deep_link':'https://app.example/#scenarios'})
        self.assertTrue(result['accepted'])
        self.assertFalse(result['delivered'])
        self.assertEqual(result['delivery_status'],'accepted')
        self.assertEqual([call.args[0] for call in post.call_args_list],['/users','/spaces','/messages'])
        self.assertIn('Projected consequence: Germany is late',post.call_args_list[2].args[1]['content']['text'])

    def test_photon_follow_up_returns_grounded_answer_and_delivery_result(self):
        class FakePhoton:
            name = 'photon'
            def reply(self,**kwargs): return {'accepted':True,'delivered':False,'space_id':kwargs['space_id']}
        self.service.notifications = FakePhoton()
        base = self.service.bootstrap()['approved_scenario']
        result = self.service.handle('POST','/api/photon/follow-up',body={'space_id':'space','question':'Why is Germany at risk?','scenario_id':base['id']})
        self.assertIn('Germany is',result['answer']['answer'])
        self.assertTrue(result['delivery']['accepted'])

    def test_google_calendar_sync_uses_all_day_events_and_stable_ids(self):
        provider = GoogleCalendarProvider(token='token')
        plan = self.service.bootstrap()['approved_scenario']
        with patch.object(provider,'_post',return_value=(200,{'id':'event','htmlLink':'https://calendar.google.com/event'})) as post:
            result = provider.sync(plan)
        self.assertEqual(result['created'],sum(len(s['milestones']) for s in plan['shipments']))
        body = post.call_args_list[0].args[1]
        self.assertEqual(len(body['id']),32)
        self.assertIn('date',body['start'])

    def test_outlook_calendar_sync_uses_graph_contract(self):
        provider = OutlookCalendarProvider(token='token')
        plan = self.service.bootstrap()['approved_scenario']
        with patch.object(provider,'_post',return_value=(201,{'id':'event','webLink':'https://outlook.office.com/event'})) as post:
            result = provider.sync(plan)
        self.assertEqual(result['provider'],'outlook')
        self.assertEqual(post.call_args_list[0].args[0],'https://graph.microsoft.com/v1.0/me/calendar/events')
        self.assertTrue(post.call_args_list[0].args[1]['isAllDay'])

    def test_openai_assistant_uses_read_only_context_tool(self):
        provider = OpenAIAssistantProvider(api_key='test',model='test-model')
        first = {'id':'resp_1','output':[{'type':'function_call','name':'get_planning_context','call_id':'call_1','arguments':'{}'}]}
        second = {'id':'resp_2','output':[{'type':'message','content':[{'type':'output_text','text':'Grounded model answer.'}]}]}
        with patch.object(provider,'_post',side_effect=[first,second]) as post:
            result = provider.answer('Why is this at risk?',self.service.bootstrap()['approved_scenario'],self.service.repo.dataset())
        self.assertEqual(result['provider'],'openai')
        self.assertIn('Grounded model answer',result['answer'])
        self.assertEqual(post.call_args_list[0].args[0]['tool_choice']['name'],'get_planning_context')
        self.assertEqual(post.call_args_list[1].args[0]['input'][0]['type'],'function_call_output')

    def test_openai_research_uses_strict_structured_output(self):
        provider = OpenAIResearchProvider(api_key='test',model='test-model')
        response = {'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'candidates':[],'document_note':'No supported rules'})}]}]}
        with patch.object(provider,'_post',return_value=response) as post:
            result = provider.extract(content='No operative requirement.',jurisdiction='DE',source={'title':'Test'},requirement_keys=set())
        self.assertEqual(result['candidates'],[])
        format_config = post.call_args.args[0]['text']['format']
        self.assertEqual(format_config['type'],'json_schema')
        self.assertTrue(format_config['strict'])
        self.assertFalse(post.call_args.args[0]['store'])
        self.assertIn('untrusted evidence',post.call_args.args[0]['instructions'])


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(port=0,db_path=':memory:')
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.service.repo.close()

    def test_health_and_json_errors(self):
        with urlopen(self.url+'/api/health') as response:
            self.assertEqual(json.load(response)['status'],'ok')
        with self.assertRaises(HTTPError) as result:
            urlopen(self.url+'/api/no-such-endpoint')
        self.assertEqual(result.exception.code,404)
        self.assertIn('error',json.load(result.exception))

    def test_external_origin_and_bad_json_rejected(self):
        with self.assertRaises(HTTPError) as result:
            urlopen(Request(self.url+'/api/demo/reset',data=b'{}',headers={'Origin':'https://evil.example','Content-Type':'application/json'}))
        self.assertEqual(result.exception.code,403)
        with self.assertRaises(HTTPError) as result:
            urlopen(Request(self.url+'/api/demo/reset',data=b'no json',headers={'Content-Type':'application/json'}))
        self.assertEqual(result.exception.code,400)


if __name__ == '__main__':
    unittest.main()
