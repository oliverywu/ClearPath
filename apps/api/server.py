"""Run: python -m apps.api.server --host 127.0.0.1 --port 8000 --db data/local.sqlite3"""
import argparse
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote
from .service import Service, APIError


def make_server(host='127.0.0.1',port=8000,db_path='data/local.sqlite3',fixture=None):
    service = Service(db_path,fixture)
    class Handler(BaseHTTPRequestHandler):
        server_version = 'ClearedForTakeoff/1'

        def log_message(self, format, *args):
            logging.info('%s %s',self.address_string(),format % args)

        def cors(self):
            origin = self.headers.get('Origin')
            if origin:
                self.send_header('Access-Control-Allow-Origin',origin)
                self.send_header('Vary','Origin')

        def respond(self, status, data, content_type='application/json; charset=utf-8', allow_cors=True):
            content = (json.dumps(data,ensure_ascii=False) if content_type.startswith('application/json') else data).encode('utf-8')
            self.send_response(status)
            if allow_cors:
                self.cors()
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(content)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            if content_type.startswith('text/calendar'):
                self.send_header('Content-Disposition','attachment; filename="approved-milestones.ics"')
            self.end_headers()
            self.wfile.write(content)

        def allowed(self):
            host_name = urlsplit('//' + self.headers.get('Host','')).hostname
            allowed_hosts = {'localhost','127.0.0.1','::1',host}
            if host_name not in allowed_hosts:
                return False
            origin = self.headers.get('Origin')
            if origin:
                parsed = urlsplit(origin)
                extra = set(filter(None,os.getenv('ALLOWED_ORIGINS','').split(',')))
                if origin not in extra and not (parsed.scheme=='http' and parsed.hostname in {'localhost','127.0.0.1','::1'}):
                    return False
            return True

        def do_OPTIONS(self):
            if not self.allowed():
                self.respond(403,{'error':'Local origin required'},allow_cors=False)
                return
            self.send_response(204)
            self.cors()
            self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers','Content-Type')
            self.end_headers()

        def do_GET(self):
            self.execute('GET')

        def do_POST(self):
            self.execute('POST')

        def execute(self, method):
            if not self.allowed():
                # Never grant CORS on a rejected cross-origin request.
                self.respond(403,{'error':'Local origin required'},allow_cors=False)
                return
            try:
                parsed = urlsplit(self.path)
                body = {}
                if method == 'POST':
                    if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                        raise APIError('Use application/json content type',415)
                    length = int(self.headers.get('Content-Length','0'))
                    if length < 0 or length > 5_000_000:
                        raise APIError('Request body exceeds 5 MB limit',413)
                    body = json.loads(self.rfile.read(length) or b'{}')
                    if not isinstance(body,dict):
                        raise APIError('JSON body must be an object')
                result = service.handle(method,unquote(parsed.path),parse_qs(parsed.query),body)
                if isinstance(result,tuple):
                    self.respond(200,result[1],result[0])
                else:
                    self.respond(200,result)
            except APIError as exc:
                self.respond(exc.status,{'error':str(exc),**({'details':exc.details} if exc.details else {})})
            except (json.JSONDecodeError,UnicodeDecodeError,ValueError):
                self.respond(400,{'error':'Malformed request body'})
            except Exception:
                logging.exception('API request failed')
                self.respond(500,{'error':'Internal operation failed; approved plans are preserved'})
    server = ThreadingHTTPServer((host,port),Handler)
    server.service = service
    return server


def main():
    parser = argparse.ArgumentParser(description='Cleared for Takeoff local API')
    parser.add_argument('--host',default=os.getenv('API_HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.getenv('API_PORT','8000')))
    parser.add_argument('--db',default=os.getenv('DATABASE_PATH','data/local.sqlite3'))
    parser.add_argument('--fixture')
    args = parser.parse_args()
    server = make_server(args.host,args.port,args.db,args.fixture)
    print(f'Cleared for Takeoff API http://{args.host}:{server.server_port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.service.repo.close()


if __name__ == '__main__':
    main()
