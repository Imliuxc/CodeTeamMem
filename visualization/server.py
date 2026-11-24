"""Loopback HTTP status service. Browser UI is strictly read-only."""
import argparse
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .control import Controller, Conflict
from .store import Store, DEFAULT_ROOT
from .recordings import Recordings, DATASETS

STATIC = Path(__file__).parent/'static'


def make_handler(controller, recordings=None):
    recordings = recordings or Recordings()
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, data, content_type='application/json; charset=utf-8'):
            raw = data if isinstance(data, bytes) else json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            try:
                parsed = urlsplit(self.path)
                path = parsed.path
                if path == '/api/runs': return self.reply(200, controller.store.runs())
                parts = path.strip('/').split('/')
                if path == '/api/recordings': return self.reply(200, recordings.list())
                if len(parts) >= 3 and parts[:2] == ['api','recordings']:
                    id = parts[2]
                    if len(parts) == 3: return self.reply(200, recordings.summary(id))
                    if len(parts) == 4 and parts[3] == 'calls':
                        q = parse_qs(parsed.query)
                        return self.reply(200,recordings.calls(id,**{k:q.get(k,[None])[0] for k in ('anchor','context','outcome')}))
                    if len(parts) == 5 and parts[3] == 'calls':
                        return self.reply(200,recordings.call(id,int(parts[4])))
                if len(parts) in {3,4} and parts[:2] == ['api','runs']:
                    run = parts[2]
                    if len(parts) == 3: return self.reply(200, controller.store.view(run))
                    if parts[3] == 'events':
                        q = parse_qs(parsed.query)
                        return self.reply(200,controller.store.events(run,int(q.get('after',['0'])[0])))
                files = {'/':('index.html','text/html; charset=utf-8'),
                         '/app.js':('app.js','text/javascript; charset=utf-8'),
                         '/records':('records.html','text/html; charset=utf-8'),
                         '/records.js':('records.js','text/javascript; charset=utf-8'),
                         '/style.css':('style.css','text/css; charset=utf-8')}
                if path not in files: return self.reply(404, {'error':'not found'})
                name, content_type = files[path]
                self.reply(200,(STATIC/name).read_bytes(),content_type)
            except KeyError: self.reply(404,{'error':'unknown run'})
            except (ValueError,TypeError): self.reply(400,{'error':'invalid request or saved recording'})
            except OSError: self.reply(404,{'error':'saved recording unavailable'})

        def do_POST(self):
            if self.path != '/control': return self.reply(404,{'error':'not found'})
            # CLI-only control: reject requests from browser origins, including same origin.
            if self.headers.get('Origin') or self.headers.get('Sec-Fetch-Site'):
                return self.reply(403,{'error':'browser control is disabled; use conversation CLI'})
            if self.headers.get_content_type() != 'application/json': return self.reply(415,{'error':'JSON required'})
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 16384: raise ValueError('invalid request size')
                payload = json.loads(self.rfile.read(length))
                action = payload.pop('action')
                self.reply(200,controller.command(action, **payload))
            except Conflict as exc: self.reply(409,{'error':str(exc)})
            except KeyError: self.reply(404,{'error':'unknown run, Case or action'})
            except (ValueError,TypeError,AttributeError) as exc: self.reply(400,{'error':str(exc)})

        def log_message(self, format, *args): pass
    return Handler


def serve(host='127.0.0.1', port=8764, root=DEFAULT_ROOT, datasets=DATASETS):
    if host not in {'127.0.0.1','localhost'}: raise ValueError('service must bind loopback')
    store = Store(root)
    # Prevent a second service from misclassifying the first service's active command.
    with (store.root/'service.lock').open('a') as owner:
        try: fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('another service owns this runtime directory')
        server = ThreadingHTTPServer((host,port),make_handler(Controller(store),Recordings(datasets)))
        store.recover()
        print(f'CodeTeamMem read-only dashboard: http://{host}:{server.server_port}',flush=True)
        try: server.serve_forever()
        except KeyboardInterrupt: pass
        finally: server.server_close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',default='127.0.0.1'); p.add_argument('--port',type=int,default=8764)
    p.add_argument('--data-dir',type=Path,default=DEFAULT_ROOT)
    p.add_argument('--datasets-dir',type=Path,default=DATASETS)
    a=p.parse_args(); serve(a.host,a.port,a.data_dir,a.datasets_dir)


if __name__ == '__main__': main()
