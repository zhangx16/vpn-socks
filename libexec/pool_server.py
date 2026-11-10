#!/usr/bin/env python3
import http.server,json,threading,time,http.cookiejar,urllib.request,urllib.parse
from pathlib import Path
from catalog_pool import collect,render
DIRECTORY='/var/lib/fanout-pool'
def refresh_fanout():
    try:
        settings=json.loads(Path('/var/lib/fanout/settings.json').read_text())
        base='http://127.0.0.1:'+str(settings['port'])+'/'+Path('/var/lib/fanout/basepath').read_text().strip()
        opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        password=Path('/var/lib/fanout/password').read_text().strip()
        with opener.open(base+'/login',urllib.parse.urlencode({'password':password}).encode(),timeout=5) as response:json.load(response)
        with opener.open(urllib.request.Request(base+'/api/refresh',method='POST'),timeout=35) as response:json.load(response)
    except Exception:pass
def update():
    while True:
        try:
            collect(DIRECTORY)
            refresh_fanout()
        except Exception:pass
        time.sleep(600)
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path not in ('/catalog.csv','/status'):self.send_error(404);return
        try:
            state=collect(DIRECTORY);body=(render(state['items']) if self.path=='/catalog.csv' else json.dumps({k:v for k,v in state.items() if k!='items'}|{'total':len(state['items'])})).encode()
            self.send_response(200);self.send_header('Content-Type','text/plain; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        except Exception:self.send_error(503)
if __name__=='__main__':
    threading.Thread(target=update,daemon=True).start();http.server.ThreadingHTTPServer(('127.0.0.1',35014),Handler).serve_forever()
