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

def cleanup_ingress(request):
 registry=Path('/var/lib/fanout-ingress/nodes.json')
 if registry.exists():
  helper=Path('/usr/local/libexec/fanout/ingress.py')
  if not helper.exists():raise ValueError('Ingress cleanup helper missing')
  subprocess.run(['python3',str(helper),json.dumps({**request,'operation':'remove'})],check=True,stdout=subprocess.DEVNULL)

def main(request):
 os.umask(0o077);api=call_api();view=api('/api/exits');store=json.loads(Path('/var/lib/fanout/native.json').read_text());operation=request['operation']
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
