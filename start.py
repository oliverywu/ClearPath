"""Start the whole Cleared for Takeoff application with one command.

    python start.py            # validate, migrate the database, start API + website
    python start.py --check    # validate prerequisites and configuration only
    python start.py --reset    # re-seed the synthetic demo dataset (plans and audit are kept)

Website: http://localhost:3000   (Garima's frontend; the only user-facing UI)
API:     http://localhost:8000   (unified planner API; the browser reaches it via /api on :3000)
Ctrl+C stops both processes.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLANNER = ROOT / 'planner'
FRONTEND = ROOT / 'cleared-for-takeoff' / 'cleared-for-takeoff-app'
MESSAGING = ROOT / 'messaging'
STATE_DIR = ROOT / '.local'


def fail(message):
    print(f'\n[start] ERROR: {message}', file=sys.stderr, flush=True)
    raise SystemExit(1)


def load_env_file(path):
    """Server-side configuration only (Chalk, Photon, Google keys). Never served to the browser."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def port_free(host, port):
    with socket.socket() as probe:
        try:
            probe.bind((host, port))
            return True
        except OSError:
            return False


def node_version(node):
    try:
        out = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=10).stdout.strip()
        return tuple(int(x) for x in out.lstrip('v').split('.')[:2])
    except Exception:
        return None


def validate(args):
    problems = []
    if sys.version_info < (3, 11):
        problems.append(f'Python 3.11+ is required (found {sys.version.split()[0]}).')
    node = shutil.which('node')
    version = node_version(node) if node else None
    if not node or not version or version < (18, 0):
        problems.append('Node.js 18+ is required for the website server (https://nodejs.org).')
    for path in (PLANNER / 'apps/api/server.py', FRONTEND / 'server.js', MESSAGING / 'planner_conversation.py', Path(args.fixture)):
        if not path.exists():
            problems.append(f'Missing {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}.')
    if args.web_port == args.api_port:
        problems.append('Website and API ports must differ.')
    for port, name in ((args.web_port, 'website'), (args.api_port, 'API')):
        if not port_free(args.host, port):
            problems.append(f'Port {port} ({name}) is already in use. Stop the other process or pass --{"web" if name == "website" else "api"}-port.')
    if os.getenv('PHOTON_BRIDGE_ENABLED', 'false').lower() == 'true':
        try:
            import photon_api  # noqa: F401
        except ImportError:
            problems.append('PHOTON_BRIDGE_ENABLED=true needs the Photon SDK: pip install -r messaging/requirements.txt')
        for key in ('PHOTON_API_KEY', 'PHOTON_PROJECT_ID'):
            if not os.getenv(key):
                problems.append(f'PHOTON_BRIDGE_ENABLED=true but {key} is not set.')
    if problems:
        fail('\n  - ' + '\n  - '.join(problems))
    chalk = 'Chalk online queries' if (os.getenv('CHALK_ACCESS_TOKEN') or (os.getenv('CHALK_CLIENT_ID') and os.getenv('CHALK_CLIENT_SECRET'))) else 'local deterministic fallback (Chalk not configured)'
    print(f'[start] Python {sys.version.split()[0]}, Node {".".join(map(str, version))}; features: {chalk}; '
          f'Google route analysis: {"configured" if os.getenv("GOOGLE_MAPS_API_KEY") else "not configured"}; '
          f'Photon bridge: {"on" if os.getenv("PHOTON_BRIDGE_ENABLED", "false").lower() == "true" else "off"}', flush=True)
    return node


def wait_for(url, process, name, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            fail(f'{name} exited during startup with status {process.returncode}.')
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return json.load(response)
        except (OSError, urllib.error.URLError, ValueError):
            time.sleep(0.2)
    fail(f'{name} did not become ready at {url} within {timeout} seconds.')


def stop(processes):
    for process in processes:
        if process.poll() is None:
            if os.name == 'nt':
                process.terminate()
            else:
                process.send_signal(signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()


def main():
    load_env_file(ROOT / '.env')
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host', default=os.getenv('HOST', '127.0.0.1'))
    parser.add_argument('--web-port', type=int, default=int(os.getenv('WEB_PORT', '3000')))
    parser.add_argument('--api-port', type=int, default=int(os.getenv('API_PORT', '8000')))
    parser.add_argument('--db', default=os.getenv('DATABASE_PATH', str(STATE_DIR / 'cleared.sqlite3')))
    parser.add_argument('--fixture', default=os.getenv('FIXTURE', str(PLANNER / 'data/demo/trial_logistics.json')))
    parser.add_argument('--reset', action='store_true', help='Re-seed the synthetic demo dataset before starting')
    parser.add_argument('--check', action='store_true', help='Validate prerequisites and exit')
    args = parser.parse_args()
    node = validate(args)
    if args.check:
        print('[start] Configuration OK.')
        return

    STATE_DIR.mkdir(exist_ok=True)
    env = {**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'MESSAGING_DIR': str(MESSAGING)}
    print('[start] Initializing / migrating the canonical database…', flush=True)
    init = subprocess.run([sys.executable, '-m', 'apps.api.init_db', '--db', args.db, '--fixture', args.fixture]
                          + (['--reset'] if args.reset else []), cwd=PLANNER, env=env, capture_output=True, text=True)
    if init.returncode != 0:
        fail('Database initialization failed:\n' + (init.stderr or init.stdout)[-3000:])
    summary = json.loads(init.stdout.strip().splitlines()[-1])
    print(f"[start] Database {summary['database']} · schema v{summary['schema_version']} · current plan v{summary['current_plan_version']} "
          f"({summary['current_plan_id']}) · {summary['events']} disruption event(s)", flush=True)

    processes = []
    try:
        api = subprocess.Popen([sys.executable, '-m', 'apps.api.server', '--integrated', '--host', args.host, '--port', str(args.api_port),
                                '--db', args.db, '--fixture', args.fixture, '--state-dir', str(STATE_DIR)], cwd=PLANNER, env=env)
        processes.append(api)
        api_url = f'http://{args.host}:{args.api_port}'
        health = wait_for(api_url + '/api/health', api, 'Unified API')
        if not health.get('integrated'):
            fail('The process on the API port is not the integrated planner API.')
        web = subprocess.Popen([node, 'server.js'], cwd=FRONTEND,
                               env={**env, 'PORT': str(args.web_port), 'HOST': args.host, 'API_ORIGIN': api_url})
        processes.append(web)
        web_url = f'http://{args.host}:{args.web_port}'
        wait_for(web_url + '/api/health', web, 'Website (proxy check)')
        display = 'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host
        print(f'\n  Cleared for Takeoff is running.\n'
              f'  Website: http://{display}:{args.web_port}\n'
              f'  API:     http://{display}:{args.api_port}   (browser uses /api on the website origin)\n'
              f'  Data:    {args.db}\n  Press Ctrl+C to stop.\n', flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
        failed = next(p for p in processes if p.poll() is not None)
        fail(f"{'API' if failed is api else 'Website'} stopped unexpectedly (status {failed.returncode}).")
    except KeyboardInterrupt:
        print('\n[start] Stopping…', flush=True)
    finally:
        stop(processes)
        print('[start] All processes stopped.', flush=True)


if __name__ == '__main__':
    main()
