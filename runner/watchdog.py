#!/usr/bin/env python3
"""Independent control-server monitoring; never infer healthy from an open WS alone."""
import argparse,concurrent.futures,hashlib,http.client,json,os,secrets,shlex,sqlite3,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent));import service as runner
sys.path.insert(0,str(runner.PROJECT/'portal'));import vault
PORTAL_ROOT=Path(os.environ.get('VPN_PORTAL_DIR','/var/lib/vpn-control'))

def init():
 with runner.db() as c:c.execute('CREATE TABLE IF NOT EXISTS node_health(id TEXT PRIMARY KEY,state TEXT,checked REAL,failures INTEGER,repaired REAL,detail TEXT)')

def websocket(config):
 try:
  c=http.client.HTTPSConnection(config['domain'],timeout=8);c.request('GET',config['path'],headers={'User-Agent':'Mozilla/5.0 VPN-Health','Upgrade':'websocket','Connection':'Upgrade','Sec-WebSocket-Version':'13','Sec-WebSocket-Key':__import__('base64').b64encode(secrets.token_bytes(16)).decode()});response=c.getresponse();status=response.status;c.close();return {'ok':status==101,'status':status}
 except Exception:return {'ok':False,'status':0}

def previous(identity):
 with runner.db() as c:row=c.execute('SELECT * FROM node_health WHERE id=?',(identity,)).fetchone()
 return dict(row) if row else {'failures':0,'repaired':0}

def should_repair(old,now=None):return old['failures']>=1 and (now or time.time())-old['repaired']>=180

def record(node,state,detail,repaired=False):
 old=previous(node['id'])
 prior=json.loads(old.get('detail','{}'))
 if detail.get('actions'):detail['last_repair_actions']=detail['actions']
 elif prior.get('last_repair_actions'):detail['last_repair_actions']=prior['last_repair_actions']
 failures=0 if state=='healthy' else old['failures'] if state=='maintenance' else old['failures']+1
 with runner.db() as c:
  c.execute('INSERT OR REPLACE INTO node_health VALUES(?,?,?,?,?,?)',(node['id'],state,time.time(),failures,time.time() if repaired else old['repaired'],json.dumps(detail,ensure_ascii=False)))
  if state=='healthy' and detail.get('exit_ip'):
   row=c.execute('SELECT result FROM nodes WHERE id=?',(node['id'],)).fetchone()
   if row:
    result=json.loads(row['result']);result.update(exit_ip=detail['exit_ip'],country=detail.get('country'))
    if 'standby_ips' in detail:result['standby_ips']=detail['standby_ips'];result['warning']=None if detail['standby_ips'] else '当前暂无已连接热备，后台持续恢复候选'
    c.execute('UPDATE nodes SET result=? WHERE id=?',(json.dumps(result),node['id']))

def busy(ip):
 with runner.db() as c:return any(json.loads(row['config']).get('ip')==ip for row in c.execute("SELECT config FROM jobs WHERE status IN ('queued','running')"))

def ensure_pin(config):
 keys=runner.paramiko.HostKeys()
 try:keys.load(str(runner.ROOT/'known_hosts'))
 except OSError:raise ValueError('SSH 主机密钥尚未登记，请先完成一次人工部署或连接') from None
 address=config['ip'] if config['sshPort']==22 else '['+config['ip']+']:'+str(config['sshPort'])
 if not keys.lookup(address):raise ValueError('SSH 主机密钥尚未登记，停止自动连接')

def check_group(nodes):
 ip=nodes[0]['config']['ip'];client=None;lease=None;checks={n['id']:websocket(n['config']) for n in nodes}
 if busy(ip):
  for node in nodes:record(node,'maintenance',{'reason':'节点任务正在执行，暂停自动修复','websocket':checks[node['id']]})
  return
 try:
  config=nodes[0]['config'];lease=runner.server_lock(config,blocking=False)
  if lease is None:
   for node in nodes:record(node,'maintenance',{'reason':'服务器任务持有连接锁，暂停自动修复','websocket':checks[node['id']]})
   return
  ensure_pin(config)
  credentials=vault.resolve(PORTAL_ROOT,{'username':'root'},config)
  if not credentials.get('password') and not credentials.get('privateKey'):raise ValueError('SSH 信息未保存，无法验收出口与执行自动修复')
  credentials.update(ip=config['ip'],sshPort=config['sshPort'],username=credentials.get('username','root'))
  client=runner.connect(credentials)
  # No repair is allowed before the remote helper verifies domain, path, port and UUID.
  code,_=runner.ssh_run(client,'test -d /var/lib/fanout-nodes && test -d /usr/local/libexec/fanout',timeout=10)
  if code:raise ValueError('未发现受管节点安装，停止自动修复')
  helper=runner.PROJECT/'scripts/control-health.py';remote='/usr/local/libexec/fanout/control-health.py'
  expected=hashlib.sha256(helper.read_bytes()).hexdigest();_,value=runner.ssh_run(client,'sha256sum '+remote+' 2>/dev/null',timeout=10)
  if not value.startswith(expected):
   with client.open_sftp() as f:f.put(str(helper),remote);f.chmod(remote,0o700)
  repair=not busy(ip) and any(should_repair(previous(n['id'])) for n in nodes)
  request={'nodes':[{'id':n['id'],'config':n['config']} for n in nodes],'repair':repair}
  # Only public node parameters cross this channel. SSH credentials never enter command text.
  command='printf %s '+shlex.quote(json.dumps(request))+' | python3 '+shlex.quote(remote)
  code,output=runner.ssh_run(client,command,timeout=100)
  result=json.loads(output.strip().splitlines()[-1])
  if code:raise ValueError(result.get('error','远程测活失败'))
  rows={r['id']:r for r in result['nodes']}
  for node in nodes:
   row=rows[node['id']];check=checks[node['id']];state=row['state']
   if state=='healthy' and not check['ok']:state='cf_unavailable';row['reason']='源站完整链路正常，但控制台到域名入口验收失败'
   record(node,state,{**row,'websocket':check,'actions':result.get('actions',[])},bool(result.get('actions')))
 except Exception as e:
  message='SSH 主机密钥变化，自动修复已停止' if isinstance(e,runner.paramiko.BadHostKeyException) else 'SSH 认证失败，请更新已保存的凭据' if isinstance(e,runner.paramiko.AuthenticationException) else str(e)
  for node in nodes:record(node,'unreachable',{'reason':message,'websocket':checks[node['id']]})
 finally:
  if client:client.close()
  if lease:lease.close()
  if 'credentials' in locals():
   for name in ('password','privateKey'):credentials[name]=''

def tick():
 with runner.db() as c:nodes=[{**dict(row),'config':json.loads(row['config'])} for row in c.execute("SELECT * FROM nodes WHERE status='active'")]
 groups={}
 for node in nodes:groups.setdefault((node['config']['ip'],node['config']['sshPort']),[]).append(node)
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(check_group,groups.values()))
if __name__=='__main__':
 os.umask(0o077);init();parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
 while True:
  started=time.monotonic()
  try:tick()
  except Exception as e:print('Health cycle failed: '+str(e),flush=True)
  if args.once:break
  time.sleep(max(10,60-(time.monotonic()-started)))
