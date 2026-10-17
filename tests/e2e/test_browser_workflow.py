"""End-to-end: the real application started by start.py, driven in Chromium.

    python -m unittest tests.e2e.test_browser_workflow        (from the repository root)

Requires Node 18+ and Playwright for Python with Chromium
(pip install playwright && python -m playwright install chromium); skipped otherwise.
Screenshots of each step are written to test-results/e2e/.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / 'test-results' / 'e2e'

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def http(method, url, body=None):
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def start_app(tmp, web_port, api_port):
    process = subprocess.Popen([sys.executable, 'start.py', '--web-port', str(web_port), '--api-port', str(api_port),
                                '--db', str(Path(tmp) / 'e2e.sqlite3')], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               **({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {}))
    deadline, lines = time.time() + 60, []
    while time.time() < deadline:
        line = process.stdout.readline()
        lines.append(line)
        if 'is running' in line:
            # Read the rest of the startup banner (URLs) before handing the process back.
            while 'Press Ctrl+C' not in lines[-1] and process.poll() is None:
                lines.append(process.stdout.readline())
            return process, lines
        if process.poll() is not None:
            break
    process.kill()
    raise AssertionError('start.py did not start:\n' + ''.join(lines))


def stop_app(process):
    process.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGINT)
    try:
        output, _ = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
    return output


@unittest.skipIf(sync_playwright is None or not shutil.which('node'), 'Playwright for Python and Node are required')
class BrowserWorkflow(unittest.TestCase):
    def test_required_end_to_end_workflow(self):
        SHOTS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            web_port, api_port = free_port(), free_port()
            process, _ = start_app(tmp, web_port, api_port)
            web = f'http://127.0.0.1:{web_port}'
            try:
                self.run_workflow(web, api_port)
            finally:
                output = stop_app(process)
            self.assertIn('All processes stopped', output)

    def run_workflow(self, web, api_port):
        api = web + '/api'
        status, before = http('GET', api + '/current-plan')
        self.assertEqual((status, before['version']), (200, 1))
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1400, 'height': 900})
            errors, urls = [], []
            page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: urls.append(r.url))
            shot = lambda name: page.screenshot(path=str(SHOTS / f'{name}.png'))

            # 1. A logistics disruption is introduced.
            status, warning = http('POST', api + '/change-events', {
                'id': 'jp-port-closure', 'title': 'Japan · Narita cargo terminal closure', 'event_type': 'logistics', 'jurisdiction': 'JP',
                'synthetic': True, 'description': 'Simulated NRT cargo terminal closure adds 6 business days.', 'transit_delay_days': 6,
                'repair_options': [{'id': 'jp-express', 'action': 'alternative_route', 'route_id': 'demo-JP-express', 'title': 'Use the priority direct lane',
                                    'description': 'Ship on the express lane.', 'tradeoffs': 'Higher transport cost.'}]})
            self.assertEqual(status, 200, warning)
            # 2-5. The warning appears; impact and immutable proposals exist; current plan unchanged.
            page.goto(web + '/#/warnings')
            card = page.locator('.wcard', has_text='Narita cargo terminal closure')
            card.wait_for()
            self.assertIn('in review', card.inner_text().lower())
            card.click()
            page.locator('.wopt').first.wait_for()
            detail = page.locator('#wdetail').inner_text()
            self.assertIn('Use the priority direct lane', detail)
            self.assertIn('PROPOSED', detail.upper())
            self.assertIn('v1', detail)
            shot('1-warning-in-review')
            self.assertEqual(http('GET', api + '/current-plan')[1]['planId'], before['planId'])

            # 6-8. Photon/Max shows the warning and options; selecting previews only; unauthorized approval refused.
            page.goto(web + '/#/max/max-kenji')
            page.locator('.b.them', has_text='Narita cargo terminal closure').first.wait_for()
            page.locator('#qr button', has_text='1').first.click()
            page.locator('.b.them', has_text='Nothing has changed yet').wait_for()
            self.assertEqual(http('GET', api + '/current-plan')[1]['version'], 1)
            page.fill('#msg', 'APPROVE'); page.press('#msg', 'Enter')
            page.locator('.b.them', has_text='only an authorized supply lead').wait_for()
            shot('2-kenji-refused')
            self.assertEqual(http('GET', api + '/current-plan')[1]['version'], 1)

            # 9-10. Authorized approval moves the pointer exactly once.
            page.goto(web + '/#/max/max-maya')
            page.locator('.b.them', has_text='Narita cargo terminal closure').first.wait_for()
            page.locator('#qr button', has_text='1').first.click()
            page.locator('.b.them', has_text='Nothing has changed yet').wait_for()
            page.locator('#qr button', has_text='APPROVE').click()
            page.locator('.b.them', has_text='moved the current plan to version 2').wait_for()
            shot('3-maya-approved')
            after = http('GET', api + '/current-plan')[1]
            self.assertEqual((after['version'], after['appliedEventIds']), (2, ['jp-port-closure']))

            # 11-12. The decision is in the audit history and the website shows the approved result.
            page.goto(web + '/#/warnings')
            page.goto(web + '/#/warnings/wrn-jp-port-closure')
            page.locator('.wopt.approved').wait_for()
            detail = page.locator('#wdetail').inner_text()
            self.assertIn('APPROVED · CURRENT', detail.upper())
            self.assertIn('Current plan changed', detail)
            self.assertIn('v2', detail)
            self.assertIn('resolved', page.locator('.wcard', has_text='Narita').inner_text().lower())
            shot('4-warning-resolved')
            shipments = http('GET', api + '/shipments')[1]
            self.assertTrue(all(s['currentPlanId'] == after['planId'] for s in shipments))

            # 13. Post-approval notification reached the other chat.
            page.goto(web + '/#/max/max-kenji')
            page.locator('.b.them', has_text='Plan update: Maya approved option 1').wait_for()

            # 14. Replaying the same Photon/web message does not duplicate anything.
            last_maya = http('GET', api + '/photon/chats/max-maya/messages')[1]
            replay = page.evaluate("""async () => {
                const send = t => fetch('/api/photon/chats/max-maya/messages', {method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({text: t, clientMessageId: 'replay-1'})}).then(r => r.json());
                const a = await send('APPROVE'); const b = await send('APPROVE'); return [a, b]; }""")
            self.assertFalse(replay[0]['replayed'])
            self.assertTrue(replay[1]['replayed'])
            self.assertEqual(replay[0]['replies'][0]['id'], replay[1]['replies'][0]['id'])
            self.assertEqual(len(http('GET', api + '/photon/chats/max-maya/messages')[1]), len(last_maya) + 2)
            self.assertEqual(http('GET', api + '/current-plan')[1]['version'], 2)
            audit = http('GET', api + '/audit-history')[1]
            self.assertEqual(sum(a['action'] == 'current_plan.changed' for a in audit), 1)

            # Landing: modeled tracking, honest inventory state, Chalk insight provenance.
            page.goto(web + '/#/')
            page.locator('.foot span', has_text='current plan v2').wait_for()
            page.locator('#inventory').scroll_into_view_if_needed()
            page.locator('#grid .state', has_text='Inventory data is not configured').wait_for()
            page.locator('#calg .cd.has').first.click()
            page.locator('#dai .chalk .cap').wait_for()
            self.assertIn('Local deterministic fallback', page.locator('#dai .chalk .cap').inner_text())
            shot('5-landing-calendar-insight')

            browser.close()
        self.assertEqual(errors, [])
        same_origin = [u for u in urls if '/api/' in u]
        self.assertTrue(same_origin)
        self.assertTrue(all(u.startswith(web + '/api/') for u in same_origin), 'browser called another API origin')
        self.assertFalse([u for u in urls if '/mock/' in u], 'mock JSON was requested in the integrated app')
        self.assertFalse([u for u in urls if f':{api_port}' in u], 'browser called the API port directly')


@unittest.skipIf(sync_playwright is None or not shutil.which('node'), 'Playwright for Python and Node are required')
class FrontendIsolation(unittest.TestCase):
    def test_api_failure_shows_error_state_and_mock_mode_still_works(self):
        dead_api = free_port()
        port = free_port()
        node = subprocess.Popen(['node', 'server.js'], cwd=ROOT / 'cleared-for-takeoff' / 'cleared-for-takeoff-app',
                                env={**os.environ, 'PORT': str(port), 'API_ORIGIN': f'http://127.0.0.1:{dead_api}'},
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1); break
                except OSError:
                    time.sleep(0.1)
            status, body = http('GET', f'http://127.0.0.1:{port}/api/warnings')
            self.assertEqual(status, 502)
            self.assertIn('Planner API unavailable', body['error'])
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{port}/#/warnings')
                page.locator('#wlist .state.err', has_text='Planner API unavailable').wait_for()
                page.locator('#wlist .chip', has_text='Retry').wait_for()
                page.goto(f'http://127.0.0.1:{port}/?mock=1#/warnings')
                page.locator('.wcard').first.wait_for()
                browser.close()
        finally:
            node.terminate()
            node.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
