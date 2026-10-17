"""Exercise the actual launcher, HTTP proxy, API, SQLite and demo workflow."""
from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def available_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class LocalWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / '.local').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / '.local')
        cls.web_port, cls.api_port = available_port(), available_port()
        cls.base = f'http://127.0.0.1:{cls.web_port}'
        cls.log = open(Path(cls.temp.name) / 'server.log', 'w+', encoding='utf-8')
        cls.process = subprocess.Popen([
            sys.executable, str(ROOT / 'start.py'), '--web-port', str(cls.web_port),
            '--api-port', str(cls.api_port), '--db', str(Path(cls.temp.name) / 'test.sqlite3')],
            cwd=ROOT, stdout=cls.log, stderr=subprocess.STDOUT)
        cls.addClassCleanup(cls.cleanup)
        for _ in range(120):
            if cls.process.poll() is not None:
                cls.log.seek(0)
                raise RuntimeError(cls.log.read())
            try:
                with urllib.request.urlopen(cls.base + '/api/health', timeout=1) as res:
                    if res.status == 200:
                        return
            except OSError:
                time.sleep(.1)
        raise RuntimeError('Local launcher did not start')

    @classmethod
    def cleanup(cls):
        # Terminate the whole Windows child tree; POSIX launcher is interrupted for cleanup.
        if sys.platform == 'win32':
            subprocess.run(['taskkill', '/PID', str(cls.process.pid), '/T', '/F'], capture_output=True)
        else:
            import signal
            cls.process.send_signal(signal.SIGINT)
        cls.process.wait(timeout=10)
        cls.log.close()
        cls.temp.cleanup()

    def request(self, path, body=None, raw=False):
        request = urllib.request.Request(self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read().decode('utf-8')
            return content if raw else json.loads(content)

    def test_complete_demo_and_replacement(self):
        html = self.request('/', raw=True)
        self.assertIn('Cleared for Takeoff', html)
        self.assertIn('app.js', html)
        health = self.request('/api/health')
        self.assertEqual(health['status'], 'ok')
        bootstrap = self.request('/api/bootstrap')
        baseline = bootstrap['approved_scenario']
        self.assertGreaterEqual(len(baseline['shipments']), 20)
        self.assertLessEqual(len(baseline['shipments']), 30)
        snapshot = self.request('/api/scenarios/' + baseline['id'])
        events = bootstrap['events']
        jp_event = next(e for e in events if e.get('jurisdiction') == 'JP')
        jp = self.request('/api/change-events/' + jp_event['id'] + '/analyze', {})
        comparison = self.request(f"/api/scenarios/{baseline['id']}/compare/{jp['id']}")
        self.assertTrue(comparison['changes'])
        before_jp = next(s for s in baseline['shipments'] if s['country_code'] == 'JP')
        after_jp = next(s for s in jp['shipments'] if s['country_code'] == 'JP')
        self.assertGreater(after_jp['projected_delivery'], before_jp['projected_delivery'])
        self.assertLess(after_jp['slack_days'], before_jp['slack_days'])
        self.assertTrue(jp['repair_options'])
        repair = next((r for r in jp['repair_options'] if r.get('recommended')), jp['repair_options'][0])
        repaired = self.request('/api/change-events/' + jp_event['id'] + '/analyze', {'repair': repair['id']})
        self.assertEqual(self.request('/api/scenarios/' + baseline['id']), snapshot)
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request('/api/scenarios/' + repaired['id'] + '/calendar.ics', raw=True)
        self.assertIn(denied.exception.code, (400, 409, 422))
        approved = self.request('/api/scenarios/' + repaired['id'] + '/approve',
                                {'approver': 'Acceptance tester', 'note': 'Reviewed synthetic label repair.'})
        self.assertEqual(approved['status'], 'approved')
        calendar = self.request('/api/scenarios/' + repaired['id'] + '/calendar.ics', raw=True)
        self.assertTrue(calendar.startswith('BEGIN:VCALENDAR'))
        self.assertIn('VERSION:2.0', calendar)
        self.assertEqual(calendar.count('BEGIN:VEVENT'), calendar.count('END:VEVENT'))
        self.assertGreaterEqual(calendar.count('BEGIN:VEVENT'), len(baseline['shipments']) * 10)
        self.assertIn('UID:', calendar)
        self.assertIn('DTSTART;VALUE=DATE:', calendar)
        de_event = next(e for e in events if e.get('jurisdiction') == 'DE')
        delayed = self.request('/api/change-events/' + de_event['id'] + '/analyze', {})
        de_before = next(s for s in approved['shipments'] if s['country_code'] == 'DE')
        de_after = next(s for s in delayed['shipments'] if s['country_code'] == 'DE')
        self.assertGreater(de_after['projected_delivery'], de_before['projected_delivery'])
        self.assertTrue(delayed['repair_options'])
        route_repairs = [r for r in delayed['repair_options'] if r['event_id'] == de_event['id']]
        route_repair = next((r for r in route_repairs if r.get('recommended')), route_repairs[0])
        rerouted = self.request('/api/change-events/' + de_event['id'] + '/analyze', {'repair': route_repair['id']})
        rerouted_de = next(s for s in rerouted['shipments'] if s['country_code'] == 'DE')
        self.assertNotEqual(de_before['route_id'], rerouted_de['route_id'])
        self.assertEqual(self.request('/api/bootstrap')['approved_scenario']['id'], approved['id'])
        answer = self.request('/api/assistant/query', {'question': 'Why is Germany at risk?',
                    'scenario_id': delayed['id'], 'trial_id': baseline['trial_id']})
        self.assertTrue(answer['answer'])
        self.assertTrue(answer['citations'])
        audit = self.request('/api/audit')['events']
        self.assertGreater(len(audit), 3)
        replacement = self.request('/api/demo/reset', {'fixture': 'replacement'})
        current = self.request('/api/bootstrap')
        self.assertNotEqual(current['trial']['id'], bootstrap['trial']['id'])
        self.assertTrue(current['approved_scenario']['shipments'])
        event = current['events'][0]
        other = self.request('/api/change-events/' + event['id'] + '/analyze', {})
        self.assertTrue(self.request(f"/api/scenarios/{current['approved_scenario']['id']}/compare/{other['id']}")['changes'])


if __name__ == '__main__':
    unittest.main()
