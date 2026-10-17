"""Startup from a fresh clone of the committed tree (no local state, no generated files).

    python -m unittest tests.e2e.test_fresh_clone
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

from .test_browser_workflow import free_port, start_app, stop_app

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = ('.env', '.conversation_state.json', '.notification_manager_state.json', '.photon_bridge_state.json', '.DS_Store')


@unittest.skipIf(not shutil.which('git') or not shutil.which('node'), 'git and Node are required')
class FreshClone(unittest.TestCase):
    def test_clone_contains_no_secrets_or_state_and_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp) / 'clone'
            subprocess.run(['git', 'clone', '-q', '--no-hardlinks', str(ROOT), str(clone)], check=True)
            tracked = subprocess.run(['git', 'ls-files'], cwd=clone, capture_output=True, text=True, check=True).stdout.split()
            self.assertFalse([f for f in tracked if Path(f).name in FORBIDDEN or f.endswith(('.sqlite3', '.sqlite', '.db'))])
            self.assertFalse((clone / '.local').exists())
            check = subprocess.run([sys.executable, 'start.py', '--check', '--web-port', str(free_port()), '--api-port', str(free_port())],
                                   cwd=clone, capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            web_port, api_port = free_port(), free_port()
            process, lines = start_app_in(clone, tmp, web_port, api_port)
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{web_port}/api/health', timeout=10) as response:
                    health = json.load(response)
                self.assertTrue(health['integrated'])
                with urllib.request.urlopen(f'http://127.0.0.1:{web_port}/api/warnings', timeout=10) as response:
                    self.assertEqual(len(json.load(response)), 3)
                with urllib.request.urlopen(f'http://127.0.0.1:{web_port}/', timeout=10) as response:
                    self.assertIn(b'Cleared for Takeoff', response.read())
            finally:
                output = stop_app(process)
            self.assertIn('Website: http://localhost', ''.join(lines))
            self.assertIn('All processes stopped', output)


def start_app_in(root, tmp, web_port, api_port):
    import tests.e2e.test_browser_workflow as browser
    original = browser.ROOT
    browser.ROOT = Path(root)
    try:
        return start_app(tmp, web_port, api_port)
    finally:
        browser.ROOT = original


if __name__ == '__main__':
    unittest.main()
