#!/usr/bin/env python3
import http.cookiejar,json,subprocess,sys,urllib.parse,urllib.request
from pathlib import Path
expected=json.loads(sys.argv[1]);node_config=Path('/var/lib/fanout-nodes')/str(expected['port'])/'node.json';probe=json.loads(node_config.read_text())['cf_port'] if node_config.exists() else 10809;run=subprocess.run(['curl','-4','-fsS','--connect-timeout','4','--max-time','18','--socks5-hostname','127.0.0.1:'+str(probe),'https://www.cloudflare.com/cdn-cgi/trace'],capture_output=True,text=True)
values=dict(line.split('=',1) for line in run.stdout.splitlines() if '=' in line)
if run.returncode or values.get('loc')!=expected['region']:raise SystemExit(1)
settings=json.loads(Path('/var/lib/fanout/settings.json').read_text());base='http://127.0.0.1:'+str(settings['port'])+'/'+Path('/var/lib/fanout/basepath').read_text().strip()
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
with opener.open(base+'/login',urllib.parse.urlencode({'password':Path('/var/lib/fanout/password').read_text().strip()}).encode(),timeout=5) as r:json.load(r)
with opener.open(base+'/api/exits',timeout=8) as r:view=json.load(r)
tag='in-'+str(expected['port'])+'-ws'
active=next((r for r in view['exits'] if any(i['tag']==tag for i in r.get('inbounds') or [])),None)
if not active or active['status']!='up' or active['region']!=expected['region'] or active['exit_ip']!=values.get('ip'):raise SystemExit(1)
print(json.dumps({'exit_ip':values['ip'],'country':values['loc']}))
