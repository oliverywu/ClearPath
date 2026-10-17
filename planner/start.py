"""One-command local launcher: database, API, browser assets, and API proxy."""
from __future__ import annotations

import argparse
import functools
import http.client
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent


def load_environment():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"').strip("'"))


def free_port(host, port):
    with socket.socket() as probe:
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise SystemExit(f'Port {port} is in use. Stop the existing app or choose --web-port/--api-port.') from exc


class WebHandler(http.server.SimpleHTTPRequestHandler):
    api_port = 8000
    api_host = '127.0.0.1'

    def log_message(self, fmt, *args):
        if args and str(args[0]).startswith('GET /api/health'):
            return
        super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_GET(self):
        if self.path.startswith('/api/'):
            self.proxy()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith('/api/'):
            self.proxy()
        else:
            self.send_error(405)

    def do_OPTIONS(self):
        self.proxy()

    def proxy(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 10_000_000:
                self.send_error(413)
                return
            body = self.rfile.read(length) if length else None
            connection = http.client.HTTPConnection(self.api_host, self.api_port, timeout=60)
            headers = {key: value for key, value in self.headers.items()
                       if key.lower() not in {'host', 'connection', 'transfer-encoding'}}
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in {'connection', 'transfer-encoding', 'content-length', 'server', 'date'}:
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            connection.close()
        except (OSError, ValueError, http.client.HTTPException) as exc:
            data = json.dumps({'error': f'Local API unavailable: {exc}'}).encode()
            self.send_response(502)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)


def main():
    if sys.version_info < (3, 11):
        raise SystemExit('Python 3.11 or later is required.')
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default=os.getenv('HOST', '127.0.0.1'))
    parser.add_argument('--web-port', type=int, default=int(os.getenv('WEB_PORT', '3000')))
    parser.add_argument('--api-port', type=int, default=int(os.getenv('API_PORT', '8000')))
    parser.add_argument('--db', default=str(ROOT / '.local' / 'cleared.sqlite3'))
    parser.add_argument('--fixture', default=str(ROOT / 'data' / 'demo' / 'trial.json'))
    parser.add_argument('--reset', action='store_true', help='Explicitly replace demo records with the selected fixture')
    args = parser.parse_args()
    if args.web_port == args.api_port:
        parser.error('Website and API ports must differ.')
    free_port(args.host, args.web_port)
    free_port(args.host, args.api_port)
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen([sys.executable, '-m', 'apps.api.server', '--host', args.host,
                                '--port', str(args.api_port), '--db', args.db, '--fixture', args.fixture],
                               cwd=ROOT)
    server = None
    try:
        api_url = f'http://{args.host}:{args.api_port}'
        for _ in range(100):
            if process.poll() is not None:
                raise SystemExit(f'API exited with status {process.returncode}.')
            try:
                with urllib.request.urlopen(api_url + '/api/health', timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            raise SystemExit('API did not become ready within 10 seconds.')
        if args.reset:
            # The reset endpoint accepts a complete dataset, preserving one validation boundary.
            with urllib.request.urlopen(urllib.request.Request(
                api_url + '/api/demo/reset',
                data=json.dumps({'dataset': json.loads(Path(args.fixture).read_text(encoding='utf-8'))}).encode(),
                headers={'Content-Type': 'application/json'}), timeout=30) as response:
                response.read()
        WebHandler.api_port, WebHandler.api_host = args.api_port, args.host
        handler = functools.partial(WebHandler, directory=str(ROOT / 'apps' / 'web'))
        server = http.server.ThreadingHTTPServer((args.host, args.web_port), handler)
        display_host = 'localhost' if args.host == '127.0.0.1' else args.host
        print(f'\nCleared for Takeoff is ready.\nWebsite: http://{display_host}:{args.web_port}\nAPI: http://{display_host}:{args.api_port}\nDatabase: {args.db}\nPress Ctrl+C to stop both services.\n', flush=True)
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print('\nStopping Cleared for Takeoff.', flush=True)
    finally:
        if server:
            server.server_close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == '__main__':
    main()
