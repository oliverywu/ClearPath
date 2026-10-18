"""Proactive Photon alerts for newly detected events (transportation disruptions
and regulatory labeling changes), reusing the existing event/governance/messaging
pipeline. Mocked Photon transport only -- no live network calls."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.api.server import make_server

FIXTURE = str(Path(__file__).resolve().parents[2] / 'data/demo/trial_logistics.json')

NEW_LOGISTICS_EVENT = {
    'id': 'ca-weather-delay', 'title': 'Canada · SIMULATED severe weather on the Toronto lane',
    'event_type': 'logistics', 'jurisdiction': 'CA', 'synthetic': True,
    'description': 'SIMULATED DEMO EVENT: simulated severe weather adds 3 business days to Canadian shipments.',
    'transit_delay_days': 3,
    'repair_options': [{'id': 'ca-alt-route', 'action': 'alternative_route', 'route_id': 'demo-CA-express',
                        'title': 'Reroute via priority lane', 'description': 'x', 'tradeoffs': 'Higher cost.'}],
}

NEW_REGULATORY_EVENT = {
    'id': 'jp-label-demo-change', 'title': 'Japan · SIMULATED labeling requirement change',
    'event_type': 'regulatory', 'jurisdiction': 'JP', 'synthetic': True,
    'description': 'SIMULATED DEMO EVENT: a new storage-condition statement is required on the Japan label.',
    'transit_delay_days': 0, 'rework_days': 2,
    'review_status': 'synthetic', 'source_tier': 'synthetic',
    'source_title': 'SIMULATED demo regulatory notice', 'source_url': 'https://example.org/cleared-synthetic/jp-label-demo',
    'source_excerpt': 'SIMULATED EVENT: for the hackathon walkthrough only.',
    'effective_from': '2026-11-01',
    'repair_options': [{'id': 'jp-label-demo-fix', 'action': 'split_label', 'title': 'Update the Japan label',
                        'description': 'x', 'tradeoffs': 'One more artwork revision.', 'rework_days': 2}],
}


class PhotonAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ.pop('PHOTON_ENABLED', None)
        self.server = make_server('127.0.0.1', 0, os.path.join(self.tmp.name, 'db.sqlite3'), FIXTURE, integrated=True)
        self.service = self.server.service

        import photon_bridge
        self.photon_bridge = photon_bridge
        self.mock_client = MagicMock()
        self.sent = self.mock_client.projects.send_message
        original_build_client = photon_bridge.build_photon_client
        original_required_env = photon_bridge._required_env
        self.addCleanup(setattr, photon_bridge, 'build_photon_client', original_build_client)
        self.addCleanup(setattr, photon_bridge, '_required_env', original_required_env)
        photon_bridge.build_photon_client = lambda: self.mock_client
        photon_bridge._required_env = lambda name: {'PHOTON_PROJECT_ID': 'proj1'}[name]
        os.environ['PHOTON_ALERT_SENDER_ID'] = 'pho_usr_agent_test'
        self.addCleanup(os.environ.pop, 'PHOTON_ALERT_SENDER_ID', None)

        # Give one existing chat a real Photon space, like the live app's human conversation.
        self.service.messaging.store.seed(self.service.governance.roles)
        self.service.repo.db.execute("UPDATE chats SET photon_space_id='pho_spc_demo' WHERE id='max-maya'")

    def tearDown(self):
        # No serve_forever() loop is ever started in these tests (the service is
        # driven in-process), so HTTPServer.shutdown() would block forever waiting
        # for a serving loop that never ran. Nothing to stop here but the db/temp dir.
        self.service.repo.close()
        self.tmp.cleanup()

    def test_new_transportation_disruption_sends_one_real_photon_alert(self):
        self.service.ingest_event(NEW_LOGISTICS_EVENT)
        self.sent.assert_called_once()
        body = self.sent.call_args[0][0].body
        self.assertEqual(body.spaceId, 'pho_spc_demo')
        self.assertIn('SIMULATED', body.content.text)
        self.assertIn('Canada', body.content.text)
        self.assertIn('Reroute via priority lane', body.content.text)

    def test_new_regulatory_change_alert_includes_source_and_effective_date_and_is_marked_synthetic(self):
        self.service.ingest_event(NEW_REGULATORY_EVENT)
        self.sent.assert_called_once()
        text = self.sent.call_args[0][0].body.content.text
        self.assertIn('SIMULATED', text)
        self.assertIn('https://example.org/cleared-synthetic/jp-label-demo', text)
        self.assertIn('effective Nov 1', text)  # effective date surfaced (short() renders no year, matching the rest of the app)
        self.assertIn('Update the Japan label', text)

    def test_duplicate_ingest_does_not_resend(self):
        self.service.ingest_event(NEW_LOGISTICS_EVENT)
        self.sent.reset_mock()
        # open_conversations is idempotent per (chat, event) -- a second alert attempt
        # for the same already-seen event must not resend.
        self.service.messaging.open_conversations('ca-weather-delay', notify_photon=True)
        self.sent.assert_not_called()

    def test_startup_backfill_never_sends_real_photon_messages(self):
        """Preserves the existing demo flow: restarting the app must not re-blast
        already-registered events (including de-route-delay) to a real phone."""
        self.sent.reset_mock()
        # Mirrors what IntegratedService.__init__/reset actually do: backfill with
        # no notify_photon, even though max-maya now has a real photon_space_id.
        for event in self.service.repo.events():
            self.service.messaging.open_conversations(event['id'])
        self.sent.assert_not_called()

    def test_approval_still_requires_explicit_authorized_approve(self):
        """The new alert path never approves or touches the plan itself."""
        before = self.service.governance.current_plan_id()
        self.service.ingest_event(NEW_LOGISTICS_EVENT)
        self.assertEqual(self.service.governance.current_plan_id(), before)


if __name__ == '__main__':
    unittest.main()
