#!/usr/bin/env python3
"""Inspect/delete one exact native inbound; preserve unrelated inbounds and tunnels."""
import http.cookiejar,json,os,subprocess,sys,urllib.parse,urllib.request
from pathlib import Path

def matching(inbound,request):
 return inbound.get('port')==request['port'] and inbound.get('protocol')=='vless' and inbound.get('network')=='ws' and inbound.get('security')=='tls' and inbound.get('path')==request['path'] and inbound.get('tls',{}).get('server_name')==request['domain']
def call_api():
 settings=json.loads(Path('/var/lib/fanout/settings.json').read_text());base='http://127.0.0.1:'+str(settings['port'])+'/'+Path('/var/lib/fanout/basepath').read_text().strip();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 def api(path,params=None,post=False):
  if params:path+='?'+urllib.parse.urlencode(params)
  with opener.open(urllib.request.Request(base+path,method='POST' if post else 'GET'),timeout=20) as r:return json.load(r)
 with opener.open(base+'/login',urllib.parse.urlencode({'password':Path('/var/lib/fanout/password').read_text().strip()}).encode(),timeout=10) as r:json.load(r)
 return api

def exit_options(view,request):
 region=request['region'];tag='in-'+str(request['port'])+'-ws';reserved=set()
 for file in Path('/var/lib/fanout-nodes').glob('*/speed/managed-slots.json'):
  if file.parent.parent.name==str(request['port']) or (file.parent.parent/'disabled').exists():continue
  reserved.update(json.loads(file.read_text()))
 legacy=Path('/etc/fanout-ha.json');slots=Path('/var/lib/fanout-speed/managed-slots.json')
 if legacy.exists() and slots.exists() and json.loads(legacy.read_text()).get('primary_inbound_tag')!=tag:reserved.update(json.loads(slots.read_text()))
 options={}
 for row in view['exits']:
  if row['region']!=region:continue
  other=any(i['tag']!=tag for i in row.get('inbounds') or []) or row['slot'] in reserved
  options[row['host']]={'host':row['host'],'ip':row.get('exit_ip',''),'slot':row['slot'],'connected':row['status']=='up','available':not other,'current':any(i['tag']==tag for i in row.get('inbounds') or []),'region':region}
 pool=Path('/var/lib/fanout-pool/pool.json')
 if pool.exists():
  for item in json.loads(pool.read_text()).get('items',{}).values():
   row=item['row']
   if row.get('CountryShort')==region and row.get('HostName') not in options:options[row['HostName']]={'host':row['HostName'],'ip':row['IP'],'connected':False,'available':True,'current':False,'region':region}
 return sorted(options.values(),key=lambda r:(not r['current'],not r['available'],not r['connected'],r['host']))

def actual_exit(inbound):
 import socket,tempfile,time
 with tempfile.TemporaryDirectory(prefix='vpn-node-check-') as tmp:
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
  client=next(c for c in inbound['clients'] if c.get('enable'))
  config={'log':{'loglevel':'none'},'inbounds':[{'listen':'127.0.0.1','port':port,'protocol':'socks','settings':{'auth':'noauth'}}],'outbounds':[{'protocol':'vless','settings':{'vnext':[{'address':inbound['tls']['server_name'],'port':443,'users':[{'id':client['id'],'encryption':'none'}]}]},'streamSettings':{'network':'ws','security':'tls','tlsSettings':{'serverName':inbound['tls']['server_name']},'wsSettings':{'path':inbound['path'],'host':inbound['tls']['server_name']}}}]}
  file=Path(tmp)/'probe.json';file.write_text(json.dumps(config));process=subprocess.Popen(['/var/lib/fanout/bin/xray','run','-config',str(file)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:
   for attempt in range(4):
    time.sleep(1)
    result=subprocess.run(['curl','-4','-fsS','--connect-timeout','3','--max-time','12','--socks5-hostname','127.0.0.1:'+str(port),'https://www.cloudflare.com/cdn-cgi/trace'],capture_output=True,text=True)
    values=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode==0 and values.get('ip'):return values
   raise ValueError('切换后完整代理链路未通过验证')
  finally:
   process.terminate()
   try:process.wait(timeout=5)
   except subprocess.TimeoutExpired:process.kill();process.wait()

def switch_exit(api,view,store,request):
 import time
 inbound=next((r for r in store['inbounds'] if r['port']==request['port']),None)
 if not inbound or not matching(inbound,request) or request['uuid'] not in [c.get('id') for c in inbound.get('clients',[])]:raise ValueError('节点身份变化，拒绝切换，请重新读取节点')
 selected=next((r for r in exit_options(view,request) if r['host']==request.get('targetHost') and r['ip']==request.get('targetIP') and r['available']),None)
 if not selected:raise ValueError('所选出口已变化或被其他节点占用，请重新读取')
 tag='in-'+str(request['port'])+'-ws';original=next((r for r in view['exits'] if any(i['tag']==tag for i in r.get('inbounds') or [])),None)
 if not original:raise ValueError('当前节点没有绑定出口，请先重新部署')
 created=False;paused=[];new=None;applied=False
 def service(name,action):
  return subprocess.run(['rc-service',name,action] if Path('/sbin/rc-service').exists() else ['systemctl',action,name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
 try:
  existing=next((r for r in view['exits'] if r['host']==selected['host']),None)
  if existing and existing['status']!='up':raise ValueError('该出口尚未上线，请选择其他候选')
  if not existing:
   result=api('/api/start',{'host':selected['host']},True);slot=result['slot'];created=True
   for attempt in range(45):
    existing=next((r for r in api('/api/exits')['exits'] if r['slot']==slot),None)
    if existing and existing['status']=='up':break
    if not existing or existing['status']=='failed':raise ValueError('候选出口连接失败，请选择其他出口')
    time.sleep(2)
  if not existing or existing['status']!='up' or existing['region']!=request['region'] or existing['host']!=selected['host']:raise ValueError('候选出口未通过国家和身份检查')
  new=existing;node=Path('/var/lib/fanout-nodes')/str(request['port']);legacy=Path('/etc/fanout-ha.json')
  if node.exists() and not (node/'disabled').exists():
   name='fanout-node-'+str(request['port'])
   if service(name,'stop'):paused.append(name)
   managed=node/'speed/managed-slots.json';state=node/'speed/state.json'
  elif legacy.exists() and json.loads(legacy.read_text()).get('primary_inbound_tag')==tag:
   for name in ('fanout-speed','fanout-ha'):
    if service(name,'stop'):paused.append(name)
   managed=Path('/var/lib/fanout-speed/managed-slots.json');state=Path('/var/lib/fanout-speed/state.json')
  else:managed=None;state=None
  api('/api/xui/bind',{'tag':tag,'host':new['host']},True)
  try:
   trace=actual_exit(inbound)
   if trace['ip']!=new['exit_ip'] or trace.get('loc')!=request['region']:raise ValueError('切换后的出口 IP 或国家不匹配')
  except Exception:
   api('/api/xui/bind',{'tag':tag,'host':original['host']},True);raise
  if managed:
   old=json.loads(managed.read_text()) if managed.exists() else [];keep=list(dict.fromkeys([new['slot']]+old+[original['slot']]))
   temporary=managed.with_suffix('.tmp');temporary.write_text(json.dumps(keep));temporary.replace(managed)
   state.write_text(json.dumps({'phase':'monitoring','low_count':0,'manual_switch_at':time.time(),'sample_host':new['host']}))
  applied=True
  return {'exit_ip':trace['ip'],'country':trace['loc'],'host':new['host'],'manual_switch':True}
 except Exception:
  if new:
   try:api('/api/xui/bind',{'tag':tag,'host':original['host']},True)
   except Exception:pass
  raise
 finally:
  for name in paused:service(name,'start')
  if created and not applied:
   try:
    candidate=next((r for r in api('/api/exits')['exits'] if r.get('host')==selected['host']),None)
    if candidate and not candidate.get('inbounds') :api('/api/stop',{'slot':candidate['slot']},True)
   except Exception:pass

def cleanup_ingress(request):
 registry=Path('/var/lib/fanout-ingress/nodes.json')
 if registry.exists():
  helper=Path('/usr/local/libexec/fanout/ingress.py')
  if not helper.exists():raise ValueError('Ingress cleanup helper missing')
  subprocess.run(['python3',str(helper),json.dumps({**request,'operation':'remove'})],check=True,stdout=subprocess.DEVNULL)

def main(request):
 os.umask(0o077);api=call_api();view=api('/api/exits');store=json.loads(Path('/var/lib/fanout/native.json').read_text());operation=request['operation']
 if operation=='exits':return {'options':exit_options(view,request)}
 if operation=='switch':return switch_exit(api,view,store,request)
 if operation=='discover':
  result=[]
  for inbound in store['inbounds']:
   if inbound.get('protocol')!='vless' or inbound.get('network')!='ws' or inbound.get('security')!='tls':continue
   domain=inbound.get('tls',{}).get('server_name','');client=next((c for c in inbound.get('clients',[]) if c.get('enable')),None)
   if not domain or not client:continue
   tag='in-'+str(inbound['port'])+'-ws';row=next((r for r in view['exits'] if any(i['tag']==tag for i in r.get('inbounds') or [])),None)
   query=urllib.parse.urlencode({'encryption':'none','security':'tls','sni':domain,'type':'ws','host':domain,'path':inbound['path']})
   registry=Path('/var/lib/fanout-ingress/nodes.json');mappings=json.loads(registry.read_text()) if registry.exists() else {};mapping=mappings.get(domain+'|'+inbound['path'],mappings.get(domain,{}))
   result.append({'domain':domain,'port':mapping.get('public_port',inbound['port']),'listen_port':inbound['port'],'path':inbound['path'],'region':row['region'] if row else 'ZZ','uuid':client['id'],'link':'vless://'+client['id']+'@'+domain+':443?'+query,'exit_ip':row.get('exit_ip','') if row else ''})
  return {'nodes':result}
 inbound=next((r for r in store['inbounds'] if r.get('port')==request['port']),None)
 if not inbound:
  cleanup_ingress(request)
  return {'node_deleted':True,'already_absent':True,'remaining_domain_nodes':sum(i.get('tls',{}).get('server_name')==request['domain'] for i in store['inbounds'])}
 if not matching(inbound,request) or request.get('uuid') not in [c.get('id') for c in inbound.get('clients',[])]:raise ValueError('节点身份已变化，拒绝删除。请先重新读取服务器节点')
 port=request['port'];warning=None;node=Path('/var/lib/fanout-nodes')/str(port)
 service='fanout-node-'+str(port)
 def stop(name):
  if Path('/sbin/rc-service').exists():
   subprocess.run(['rc-service',name,'stop'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);subprocess.run(['rc-update','del',name,'default'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  else:subprocess.run(['systemctl','disable','--now',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 if node.exists():
  stop(service);marker=node/'disabled';marker.touch(mode=0o600)
 legacy=Path('/etc/fanout-ha.json')
 if legacy.exists():
  cfg=json.loads(legacy.read_text());tag='in-'+str(port)+'-ws'
  if cfg.get('primary_inbound_tag')==tag:
   for name in ('fanout-speed','fanout-ha','fanout-probe'):stop(name)
   if len(cfg.get('inbound_tags',[]))>1:warning='旧共享守护已停用；其余入站保留，可重新部署以启用独立守护'
  elif tag in cfg.get('inbound_tags',[]):
   cfg['inbound_tags'].remove(tag);legacy.write_text(json.dumps(cfg))
 api('/api/xui/delete',{'ids':inbound['id']},True)
 after=json.loads(Path('/var/lib/fanout/native.json').read_text())
 if any(r.get('id')==inbound['id'] for r in after['inbounds']):raise ValueError('入站仍存在，删除验收失败')
 cleanup_ingress(request)
 return {'node_deleted':True,'warning':warning,'kept_tunnels':True,'remaining_domain_nodes':sum(i.get('tls',{}).get('server_name')==request['domain'] for i in after['inbounds'])}
if __name__=='__main__':
 try:print(json.dumps(main(json.loads(Path(sys.argv[1]).read_text()))))
 except Exception as e:print(str(e),file=sys.stderr);sys.exit(1)
