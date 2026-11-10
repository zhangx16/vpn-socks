#!/usr/bin/env python3
"""Self-hosted administrator console. All credentials remain server-side or in RAM."""
import sys
import hashlib,hmac,http.cookies,http.server,json,os,secrets,sqlite3,subprocess,time,urllib.request,urllib.error,urllib.parse
from pathlib import Path
PROJECT=Path(os.environ.get('VPN_RUNNER_PROJECT',Path(__file__).resolve().parents[1]))
ROOT=Path(os.environ.get('VPN_PORTAL_DIR','/var/lib/vpn-control'))
CONFIG=Path(os.environ.get('VPN_PORTAL_CONFIG','/etc/vpn-control.json'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import vault
COOKIE='__Host-vpn_session'

def settings():return json.loads(CONFIG.read_text())
def db():return sqlite3.connect(ROOT/'auth.sqlite',timeout=15)
def init():
 os.umask(0o077);ROOT.mkdir(parents=True,exist_ok=True)
 vault.cipher(ROOT)
 with vault.connection(ROOT) as c:pass
 with db() as c:c.executescript('CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,expires REAL);CREATE TABLE IF NOT EXISTS attempts(ip TEXT PRIMARY KEY,count INTEGER,start REAL);')
def password_hash(password,salt):return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
def run_cf(data):
 result=subprocess.run(['node',str(PROJECT/'portal/cf.mjs')],input=json.dumps(data),capture_output=True,text=True,timeout=150)
 if result.returncode:raise ValueError(result.stderr[-1200:])
 return json.loads(result.stdout)
def runner(path,body=None):
 cfg=settings();request=urllib.request.Request('http://127.0.0.1:35013'+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+cfg['runner_token'],'X-Actor':'admin','Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(request,timeout=40) as r:return json.load(r)
 except urllib.error.HTTPError as e:raise ValueError(json.load(e).get('error','执行器请求失败')) from None
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,status,data,ctype='application/json; charset=utf-8',extra=None):
  raw=json.dumps(data,ensure_ascii=False).encode() if ctype.startswith('application/json') else data.encode()
  self.send_response(status)
  for k,v in {'Content-Type':ctype,'Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',**(extra or {})}.items():self.send_header(k,v)
  self.end_headers();self.wfile.write(raw)
 def authenticated(self):
  cookie=http.cookies.SimpleCookie()
  try:cookie.load(self.headers.get('Cookie',''));token=cookie[COOKIE].value
  except (KeyError,http.cookies.CookieError):return False
  with db() as c:return c.execute('SELECT 1 FROM sessions WHERE hash=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone() is not None
 def do_GET(self):
  path=urllib.parse.urlparse(self.path).path
  if path=='/health':return self.send(200,{'ok':True})
  if path=='/login.js':return self.send(200,(PROJECT/'portal/login.js').read_text(),'text/javascript; charset=utf-8')
  if not self.authenticated():
   if path.startswith('/api/'):return self.send(401,{'error':'管理员会话已过期，请重新登录'})
   if path not in ('/','/login'):return self.send(404,{'error':'Not found'})
   return self.send(200,(PROJECT/'portal/login.html').read_text(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"})
  try:
   if path=='/login':return self.send(303,'','text/plain',{'Location':'/'})
   if path=='/':
    nonce=secrets.token_hex(16);return self.send(200,(PROJECT/'web/control/worker/page.html').read_text().replace('__NONCE__',nonce),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'self'; script-src 'nonce-"+nonce+"'; style-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"})
   if path=='/api/config':return self.send(200,{'nodes':settings().get('nodes',[]),'hasToken':bool(settings().get('cf_token')),'runnerReady':True,'selfHosted':True,'resetEpoch':settings().get('reset_epoch',0)})
   if path=='/api/regions':return self.send(200,runner('/regions'))
   if path=='/api/jobs':
    ident=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('id',[''])[0]
    import re
    if ident and not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('任务 ID 无效')
    return self.send(200,runner('/jobs/'+ident if ident else '/jobs'))
   if path=='/api/servers':return self.send(200,{'servers':vault.list_servers(ROOT)})
   if path=='/api/nodes':return self.send(200,runner('/nodes'))
   return self.send(404,{'error':'Not found'})
  except Exception as e:return self.send(400,{'error':str(e)})
 def do_POST(self):
  cfg=settings();origin='https://'+cfg['hostname']
  if self.headers.get('Origin')!=origin:return self.send(403,{'error':'请求来源不匹配'})
  try:
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<=65536:raise ValueError('请求大小无效')
   data=json.loads(self.rfile.read(length));path=urllib.parse.urlparse(self.path).path
   if not isinstance(data,dict):raise ValueError('请求格式无效')
   if path=='/api/login':
    address=self.client_address[0] # nginx replaces this with a validated single client address
    address=self.headers.get('X-Real-IP',address)
    with db() as c:
     row=c.execute('SELECT count,start FROM attempts WHERE ip=?',(address,)).fetchone()
     if row and row[0]>=8 and time.time()-row[1]<900:return self.send(429,{'error':'尝试过多，请 15 分钟后重试'})
     supplied=str(data.get('password',''))
     valid=len(supplied)<=512 and hmac.compare_digest(password_hash(supplied,cfg['password_salt']),cfg['password_hash'])
     if not hmac.compare_digest(str(data.get('username','')),cfg['username']) or not valid:
      count,start=(row[0]+1,row[1]) if row and time.time()-row[1]<900 else (1,time.time())
      c.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(address,count,start));return self.send(401,{'error':'管理员账号或密码错误'})
     token=secrets.token_urlsafe(48);c.execute('DELETE FROM attempts WHERE ip=?',(address,));c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),));c.execute('INSERT INTO sessions VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),time.time()+43200))
    return self.send(200,{'ok':True},extra={'Set-Cookie':COOKIE+'='+token+'; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=43200'})
   if not self.authenticated():return self.send(401,{'error':'请先使用管理员账号登录'})
   if path=='/api/logout':
    cookies=http.cookies.SimpleCookie(self.headers.get('Cookie',''));token=cookies[COOKIE].value
    with db() as c:c.execute('DELETE FROM sessions WHERE hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
    return self.send(200,{'ok':True},extra={'Set-Cookie':COOKIE+'=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0'})
   if path=='/api/password':
    if not hmac.compare_digest(password_hash(str(data.get('oldPassword','')),cfg['password_salt']),cfg['password_hash']):raise ValueError('原密码错误')
    new=str(data.get('newPassword',''))
    if not 14<=len(new)<=128:raise ValueError('新密码长度应为 14–128 位')
    cfg['password_salt']=secrets.token_hex(24);cfg['password_hash']=password_hash(new,cfg['password_salt']);temp=CONFIG.with_suffix('.tmp');temp.write_text(json.dumps(cfg));temp.chmod(0o600);temp.replace(CONFIG)
    with db() as c:c.execute('DELETE FROM sessions')
    return self.send(200,{'ok':True})
   if path=='/api/servers/save':
    identity=vault.save(ROOT,data);return self.send(200,{'id':identity,'saved':True})
   if path=='/api/servers/delete':
    vault.delete(ROOT,data.get('serverId',''));return self.send(200,{'deleted':True})
   if path=='/api/regions/refresh':return self.send(200,runner('/regions/refresh',{}))
   if path in ('/api/deploy','/api/delete','/api/discover','/api/exit-options','/api/switch'):
    target=data
    if path in ('/api/delete','/api/exit-options','/api/switch'):
     node=next((n for n in runner('/nodes')['nodes'] if n['id']==data.get('nodeId')),None)
     if not node:raise ValueError('节点不存在')
     target=node['config']
    data=vault.resolve(ROOT,data,target)
    if data.get('saveSSH') and (data.get('password') or data.get('privateKey')):vault.save(ROOT,{**data,'ip':target['ip'],'sshPort':target['sshPort']})
    data['cfToken']=data.pop('token',None) or cfg.get('cf_token','')
    return self.send(202,runner({'/api/deploy':'/jobs','/api/delete':'/delete','/api/discover':'/discover','/api/exit-options':'/exit-options','/api/switch':'/switch'}[path],data))
   if path not in ('/api/task','/api/verify'):return self.send(404,{'error':'Not found'})
   if data.get('domain','').lower().rstrip('.') in [cfg['hostname'],*cfg.get('protected_hosts',[])]:raise ValueError('不能覆盖控制台或执行器域名')
   data['token']=data.get('token') or cfg.get('cf_token','');data['operation']='verify' if path=='/api/verify' else 'configure'
   value=run_cf(data)
   if path=='/api/verify':return self.send(200,value)
   return self.send(200,''.join(json.dumps(item,ensure_ascii=False)+'\n' for item in value),'application/x-ndjson; charset=utf-8')
  except subprocess.TimeoutExpired:return self.send(504,{'error':'Cloudflare 请求超时，请检查配置后重试'})
  except Exception as e:return self.send(400,{'error':str(e)})
if __name__=='__main__':init();http.server.ThreadingHTTPServer(('127.0.0.1',35015),Handler).serve_forever()
