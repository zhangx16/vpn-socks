#!/usr/bin/env python3
"""Bounded health checks and service repair for verified, managed native nodes."""
import concurrent.futures,http.cookiejar,json,shutil,socket,subprocess,sys,time,urllib.parse,urllib.request
from pathlib import Path

def read(path,default=None):
 try:return json.loads(Path(path).read_text())
 except (OSError,ValueError):return default

def owned(config,native):
 return next((r for r in native if r.get('port')==config.get('listenPort',config['port']) and r.get('path')==config['path'] and r.get('tls',{}).get('server_name')==config['domain'] and config['uuid'] in [c.get('id') for c in r.get('clients',[])]),None)

def service(name,action):
 command=['rc-service',name,action] if shutil.which('rc-service') else ['systemctl',action,name]
 try:return subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20).returncode==0
 except (OSError,subprocess.TimeoutExpired):return False

def listening(port):
 try:
  with socket.create_connection(('127.0.0.1',port),timeout=1):return True
 except OSError:return False

def trace(port):
 try:
  p=subprocess.run(['curl','-4','-fsS','--connect-timeout','3','--max-time','8','--socks5-hostname','127.0.0.1:'+str(port),'https://www.cloudflare.com/cdn-cgi/trace'],capture_output=True,text=True,timeout=10)
  return dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line) if p.returncode==0 else {}
 except (OSError,subprocess.TimeoutExpired):return {}

def manager_snapshot(path='/api/exits',post=False):
 try:
  config=read('/var/lib/fanout/settings.json',{});base='http://127.0.0.1:'+str(config['port'])+'/'+Path('/var/lib/fanout/basepath').read_text().strip();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
  with opener.open(base+'/login',urllib.parse.urlencode({'password':Path('/var/lib/fanout/password').read_text().strip()}).encode(),timeout=4) as response:json.load(response)
  with opener.open(urllib.request.Request(base+path,method='POST' if post else 'GET'),timeout=12) as response:
   value=json.load(response);return value.get('exits') if path=='/api/exits' else value
 except Exception:return None

def manager_ready():return isinstance(manager_snapshot(),list)

def inspect(config):
 port=config.get('listenPort',config['port']);node=Path('/var/lib/fanout-nodes')/str(port);probe=read(node/'node.json',{});heartbeat=read(node/'ha/status.json',{});state='degraded';reason='完整代理链路不可用';cf=trace(probe['cf_port']) if probe.get('cf_port') else {};origin={}
 fresh=False
 try:fresh=time.time()-(node/'ha/status.json').stat().st_mtime<60
 except OSError:pass
 guard=service('fanout-node-'+str(port),'status')
 if cf.get('loc')==config['region'] and cf.get('ip'):
  state='healthy' if guard and fresh else 'guard_degraded';reason='完整代理链路正常' if state=='healthy' else '代理链路正常，但守护未运行或心跳已过期'
 elif cf.get('ip'):reason='实际出口国家不符合节点地区'
 elif probe.get('origin_port'):
  origin=trace(probe['origin_port'])
  if origin.get('ip') and origin.get('loc')==config['region']:state='cf_unavailable';reason='本地代理与出口正常，域名入口不可用'
 return {'state':state,'reason':reason,'exit_ip':cf.get('ip'),'country':cf.get('loc'),'guard_running':guard,'heartbeat_fresh':fresh,'probe_listening':bool(probe.get('cf_port') and listening(probe['cf_port'])),'port':port}

def main(request):
 store=read('/var/lib/fanout/native.json',{});native=store.get('inbounds',[]);configs=request['nodes'];valid=[r for r in configs if owned(r['config'],native)];results=[];actions=[]
 # Verify every requested identity before any shared-service operation.
 repair=request.get('repair',False) and len(valid)==len(configs) and bool(valid)
 refresh=Path('/var/lib/fanout/control-health-refresh.json')
 if len(valid)==len(configs) and valid and time.time()-read(refresh,{}).get('at',0)>(120 if repair else 600):
  updated=manager_snapshot('/api/refresh',True)
  if isinstance(updated,dict) and updated.get('count',0)>0:refresh.write_text(json.dumps({'at':time.time()}))
 if repair:
  if not service('fanout','status'):
   if service('fanout','start'):actions.append('start fanout')
  elif not manager_ready() and service('fanout','restart'):actions.append('restart unresponsive fanout')
  if not service('fanout-shared-probe','status') and service('fanout-shared-probe','start'):actions.append('start shared probe')
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  observed=list(pool.map(lambda r:inspect(r['config']) if r in valid else {'state':'identity_changed','reason':'节点身份变化或已被删除，停止自动修复'},configs))
 if repair:
  need_probe=any(not row.get('probe_listening',True) for row in observed)
  if need_probe and service('fanout-shared-probe','restart'):actions.append('restart shared probe');time.sleep(3)
  for node,row in zip(configs,observed):
   if row['state']=='healthy':continue
   if row['state']=='cf_unavailable':
    if not service('nginx','status') and service('nginx','start'):actions.append('start nginx')
    helper=Path('/usr/local/libexec/fanout/ingress-rules')
    if helper.exists():
     p=subprocess.run([str(helper)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
     if p.returncode==0:actions.append('restore ingress rules')
    continue
   name='fanout-node-'+str(row['port'])
   if service(name,'restart'):actions.append('restart '+name)
  if actions:
   time.sleep(5)
   with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:observed=list(pool.map(lambda r:inspect(r['config']),configs))
 snapshot=manager_snapshot()
 for node,row in zip(configs,observed):
  if row['state']!='identity_changed':
   port=node['config'].get('listenPort',node['config']['port']);tag='in-'+str(port)+'-ws';slots=read(Path('/var/lib/fanout-nodes')/str(port)/'speed/managed-slots.json',[])
   if snapshot is None and row['state']=='healthy':row.update(state='guard_degraded',reason='代理链路正常，但管理接口不可用')
   elif snapshot is not None:
    active=next((r for r in snapshot if any(i['tag']==tag for i in r.get('inbounds') or [])),None)
    row['standby_ips']=[r['exit_ip'] for r in snapshot if r['slot'] in slots and r.get('status')=='up' and r.get('region')==node['config']['region'] and not r.get('inbounds') and r.get('exit_ip')]
    if row['state']=='healthy' and (not active or active.get('exit_ip')!=row.get('exit_ip')):row.update(state='degraded',reason='测活出口与节点绑定不一致')
  results.append({'id':node['id'],**row})
 return {'nodes':results,'actions':actions}
if __name__=='__main__':
 try:print(json.dumps(main(json.loads(sys.stdin.read()))))
 except Exception as e:print(json.dumps({'error':str(e)}));sys.exit(1)
