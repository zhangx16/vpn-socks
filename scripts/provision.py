#!/usr/bin/env python3
import http.cookiejar,json,os,socket,subprocess,sys,time,urllib.parse,urllib.request
from pathlib import Path
request=json.loads(Path(sys.argv[1]).read_text());project=Path(sys.argv[2]);region=request['region']
def emit(step,state,message):print(json.dumps(dict(step=step,state=state,message=message),ensure_ascii=False),flush=True)
settings=json.loads(Path('/var/lib/fanout/settings.json').read_text())
base=''
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def api(path,params=None,post=False):
 if params:path+='?'+urllib.parse.urlencode(params)
 with opener.open(urllib.request.Request(base+path,method='POST' if post else 'GET'),timeout=15) as response:return json.load(response)
for attempt in range(60):
 try:
  base='http://127.0.0.1:'+str(settings['port'])+'/'+Path('/var/lib/fanout/basepath').read_text().strip()
  password=Path('/var/lib/fanout/password').read_text().strip()
  with opener.open(base+'/login',urllib.parse.urlencode({'password':password}).encode(),timeout=3) as response:json.load(response)
  break
 except Exception:time.sleep(2)
else:raise SystemExit('fanout API did not become ready')
with opener.open(urllib.request.Request(base+'/api/settings',data=json.dumps({'residential_only':False}).encode(),headers={'Content-Type':'application/json'},method='POST'),timeout=10) as response:json.load(response)
view=api('/api/exits')
if view.get('backend')!='native':raise SystemExit('Existing fanout backend is not native; refusing to change its mode')
store=json.loads(Path('/var/lib/fanout/native.json').read_text()) if Path('/var/lib/fanout/native.json').exists() else {'inbounds':[]}
public_port=request['port']
sys.path.insert(0,str(project/'libexec'))
from node_plan import plan
registry=Path('/var/lib/fanout-ingress/nodes.json');ingress=json.loads(registry.read_text()) if registry.exists() else {}
def available(port):
 with socket.socket() as probe:
  try:probe.bind(('0.0.0.0',port));return True
  except OSError:return False
request,inbound=plan(request,store['inbounds'],ingress,available)
emit('inbound','running','配置 VLESS WebSocket TLS 入站')
if inbound:
 if inbound['protocol']!='vless' or inbound['network']!='ws' or inbound['security']!='tls' or inbound['path']!=request['path'] or inbound.get('tls',{}).get('server_name')!=request['domain']:
  raise SystemExit('Selected port belongs to a different inbound; refusing to overwrite it')
 if not inbound['enable']:api('/api/panel/inbound/update',{'id':inbound['id'],'enable':1},True)
else:
 s=socket.socket()
 try:s.bind(('0.0.0.0',request['port']))
 except OSError:raise SystemExit('Selected node port is already used by another service')
 finally:s.close()
 api('/api/panel/inbound/new',{'protocol':'vless','network':'ws','security':'tls','port':request['port'],'path':request['path'],'sni':request['domain'],'remark':region+'-CF'},True)
emit('inbound','done','节点入站已就绪')
emit('exit','running','连接所选国家出口；失败候选会自动尝试替换')
tag='in-'+str(request['port'])+'-ws'
reserved=set()
legacy=Path('/etc/fanout-ha.json');legacy_slots=Path('/var/lib/fanout-speed/managed-slots.json')
if legacy.exists() and legacy_slots.exists() and json.loads(legacy.read_text()).get('primary_inbound_tag')!=tag:reserved.update(json.loads(legacy_slots.read_text()))
for file in Path('/var/lib/fanout-nodes').glob('*/speed/managed-slots.json'):
 if (file.parent.parent/'disabled').exists():continue
 if file.parent.parent.name!=str(request['port']):reserved.update(json.loads(file.read_text()))
def matching():return [r for r in api('/api/exits')['exits'] if r['region']==region and r['slot'] not in reserved and (not r.get('inbounds') or any(i['tag']==tag for i in r.get('inbounds') or []))]
rows=matching()
if len(rows)<2:
 try:api('/api/provision',{'region':region,'count':2-len(rows)},True)
 except Exception:
  if not rows:api('/api/provision',{'region':region,'count':1},True)
for attempt in range(125):
 rows=matching();up=[r for r in rows if r['status']=='up']
 if len(up)>=2:break
 if up and (attempt>=12 or len(rows)==1):break
 if rows and all(r['status']=='failed' for r in rows):break
 time.sleep(2)
up=[r for r in matching() if r['status']=='up']
if not up:raise SystemExit('No usable exit in selected country; other countries were not substituted')
tag='in-'+str(request['port'])+'-ws'
active=next((r for r in up if any(i['tag']==tag for i in r.get('inbounds') or [])),up[0])
api('/api/xui/bind',{'tag':tag,'host':active['host']},True)
emit('exit','done','出口 '+active['exit_ip']+'；独立热备 '+str(max(0,len(up)-1))+' 条')
emit('monitor','running','配置共享端口入口与独立守护')
subprocess.run(['python3',str(project/'scripts/install-ingress.py'),json.dumps(request)],check=True)
env={**os.environ,'ALLOW_SINGLE_EXIT':'1'}
with open(Path(sys.argv[1]).parent/'overlay-install.log','w') as output:
 result=subprocess.run(['python3',str(project/'scripts/install-node.py'),request['domain'],region,str(request['port'])],env=env,stdout=output,stderr=subprocess.STDOUT)
if result.returncode:
 detail='; '.join((Path(sys.argv[1]).parent/'overlay-install.log').read_text(errors='replace').splitlines()[-5:])
 raise SystemExit('Overlay service installation failed: '+detail)
emit('monitor','done','后台守护和开机自启已配置')
store=json.loads(Path('/var/lib/fanout/native.json').read_text())
inbound=next(r for r in store['inbounds'] if r['port']==request['port']);client=next(c for c in inbound['clients'] if c['enable'])
query=urllib.parse.urlencode({'encryption':'none','security':'tls','sni':request['domain'],'type':'ws','host':request['domain'],'path':request['path']})
name=region+'-CF-'+request['path'].strip('/').replace('/','-')[:40]
link='vless://'+client['id']+'@'+request['domain']+':443?'+query+'#'+urllib.parse.quote(name,safe='-')
node={'link':link,'domain':request['domain'],'region':region,'exit_ip':active['exit_ip'],'standby_ips':[r['exit_ip'] for r in up if r['slot']!=active['slot']],'port':public_port,'listen_port':request['port'],'warning':None if len(up)>1 else '所选地区当前只有一条可用出口，暂无独立热备'}
print(json.dumps({'kind':'node','data':node},ensure_ascii=False),flush=True)
