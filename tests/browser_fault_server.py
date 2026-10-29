"""Local-only HTTP fault and opaque-origin storage-denial browser test host."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MODES = {'off': '停用故障', 'model-fail': '模擬模型載入失敗', 'replay-fail': '模擬回放載入失敗',
         'replay-delay': '模擬回放延遲'}


class FaultServer(ThreadingHTTPServer):
    def __init__(self, address, site):
        self.site = str(site); self.mode = 'off'; self.guard = threading.Lock()
        super().__init__(address, Handler)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=args[2].site, **kwargs)

    def log_message(self, *args): pass

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', 'null')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def html(self, body):
        raw = ('<!doctype html><html lang="zh-Hant"><meta charset="utf-8">' + body).encode('utf8')
        self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def do_POST(self):
        if urlsplit(self.path).path != '/__qa__/controls': return self.send_error(404)
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size < 1024: return self.send_error(400)
        mode = parse_qs(self.rfile.read(size).decode('utf8')).get('mode', [''])[0]
        if mode not in MODES: return self.send_error(400)
        with self.server.guard: self.server.mode = mode
        self.send_response(303); self.send_header('Location', '/__qa__/controls'); self.end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/__qa__/controls':
            with self.server.guard: mode = self.server.mode
            return self.html('<title>本機故障驗收控制</title><h1>本機故障驗收</h1><p>目前：' + MODES[mode] + '</p>' +
                ''.join(f'<form method="post" action="/__qa__/controls"><button name="mode" value="{key}">{label}</button></form>'
                    for key, label in MODES.items()) + '<p><a href="/">測試網站</a> · <a href="/__qa__/storage-denied">儲存拒絕測試</a></p>')
        if path == '/__qa__/storage-denied':
            return self.html('<title>本機儲存拒絕驗收</title><p>以下網站位於不允許同源的 sandbox，瀏覽器會拒絕其本機儲存。</p>'
                '<iframe title="儲存被拒絕的網站" sandbox="allow-scripts allow-forms" src="/" style="width:100%;height:900px;border:1px solid #ccc"></iframe>')
        with self.server.guard: mode = self.server.mode
        fail = (mode == 'model-fail' and path == '/data/model.json') or (mode == 'replay-fail' and path.startswith('/data/replay/'))
        if fail:
            raw = json.dumps({'error': 'controlled local QA failure'}).encode()
            self.send_response(503); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw))); self.end_headers(); return self.wfile.write(raw)
        if mode == 'replay-delay' and path.startswith('/data/replay/'): time.sleep(1)
        return super().do_GET()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--port', type=int, default=8030)
    args = parser.parse_args()
    FaultServer(('127.0.0.1', args.port), ROOT/'docs').serve_forever()
