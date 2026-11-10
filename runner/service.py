#!/usr/bin/env python3
"""Authenticated HTTPS-adjacent SSH job runner. Passwords and CF tokens stay in RAM."""
import concurrent.futures, csv, hashlib, hmac, http.server, io, ipaddress, json, os, re
import secrets, shlex, sqlite3, subprocess, tarfile, threading, time, urllib.parse, urllib.request
from pathlib import Path
import paramiko

ROOT=Path(os.environ.get('VPN_RUNNER_DIR','/var/lib/vpn-runner'))
PROJECT=Path(os.environ.get('VPN_RUNNER_PROJECT','/root/vpn-socks'))
CONFIG=Path(os.environ.get('VPN_RUNNER_CONFIG','/etc/vpn-runner.json'))
LOCK=threading.Lock()
EXECUTOR=concurrent.futures.ThreadPoolExecutor(max_workers=1)
CATALOG={}

def db():
    connection=sqlite3.connect(ROOT/'jobs.sqlite',timeout=30)
    connection.row_factory=sqlite3.Row
    return connection

def init():
    os.umask(0o077);ROOT.mkdir(parents=True,exist_ok=True)
    with db() as c:
        c.executescript('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,actor TEXT,status TEXT,created REAL,config TEXT,result TEXT,error TEXT); CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,job TEXT,time REAL,step TEXT,state TEXT,message TEXT);')
        c.execute("UPDATE jobs SET status='interrupted',error='执行器重启，凭据未持久化；请重新提交任务' WHERE status IN ('queued','running')")

def event(job,step,state,message):
    with db() as c:c.execute('INSERT INTO events(job,time,step,state,message) VALUES(?,?,?,?,?)',(job,time.time(),step,state,str(message)[:2000]))

def regions(force=False):
    global CATALOG
    with LOCK:
        if not force and CATALOG and CATALOG.get('scope')=='all' and time.time()-CATALOG['updated_at']<600:return CATALOG
        try:
            response=subprocess.run(['curl','-4','-fsSL','--connect-timeout','5','--max-time','20','https://www.vpngate.net/api/iphone/'],capture_output=True,timeout=25)
            if response.returncode:raise ValueError('catalog fetch failed')
            text=response.stdout[:8_000_000].decode('utf-8-sig')
            start=text.index('#HostName,')+1
            counts={}
            for row in csv.DictReader(io.StringIO(text[start:])):
                code=row.get('CountryShort') or ''
                if not re.fullmatch('[A-Z]{2}',code):continue
                value=counts.setdefault(code,{'code':code,'name':row.get('CountryLong',code),'count':0});value['count']+=1
            if not counts:raise ValueError('empty catalog')
            CATALOG={'scope':'all','updated_at':time.time(),'stale':False,'regions':sorted(counts.values(),key=lambda r:(-r['count'],r['code']))}
            (ROOT/'catalog.json').write_text(json.dumps(CATALOG));return CATALOG
        except Exception:
            if force:raise ValueError('获取最新出口列表失败，原候选列表未被替换，请稍后重试') from None
            previous=CATALOG
            if not previous and (ROOT/'catalog.json').exists():previous=json.loads((ROOT/'catalog.json').read_text())
            if previous and previous.get('scope')=='all' and time.time()-previous['updated_at']<86400:return {**previous,'stale':True}
            raise ValueError('出口列表暂时不可用，请稍后刷新') from None

def validate(data,require_secret=True):
    ip=ipaddress.ip_address(data.get('ip',''))
    if ip.version!=4 or not ip.is_global:raise ValueError('SSH 服务器必须是公网 IPv4')
    domain=str(data.get('domain','')).lower().rstrip('.')
    if len(domain)>253 or '.' not in domain or not all(re.fullmatch('[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',s) for s in domain.split('.')):raise ValueError('节点域名无效')
    settings=json.loads(CONFIG.read_text())
    if domain in [settings.get('hostname'),*settings.get('reserved_hosts',[])]:raise ValueError('不能将控制台或执行器域名覆盖为节点域名')
    for key in ('port','sshPort'):
        value=data.get(key,22 if key=='sshPort' else 0)
        if isinstance(value,bool) or not str(value).isdigit() or not 1<=int(value)<=65535:raise ValueError(key+' 端口无效')
        data[key]=int(value)
    user=data.get('username','root')
    if not re.fullmatch('[a-zA-Z_][a-zA-Z0-9_-]{0,63}',user):raise ValueError('SSH 用户名无效')
    code=str(data.get('region','')).upper()
    if not re.fullmatch('[A-Z]{2}',code):raise ValueError('出口地区无效')
    if not re.fullmatch('/[a-zA-Z0-9/_~.%-]*',str(data.get('path','/'))) or len(data.get('path','/'))>200:raise ValueError('WebSocket 路径无效')
    if require_secret and not (data.get('password') or data.get('privateKey')):raise ValueError('请提供 SSH 密码或私钥')
    if len(data.get('privateKey',''))>24000 or len(data.get('password',''))>512:raise ValueError('SSH 凭据过长')
    if require_secret and not data.get('cfToken'):raise ValueError('后台尚未配置 Cloudflare Token')
    data.update(ip=str(ip),domain=domain,region=code,username=user)
    return data

def key_for(data):
    if not data.get('privateKey'):return None
    for kind in (paramiko.Ed25519Key,paramiko.RSAKey,paramiko.ECDSAKey):
        try:return kind.from_private_key(io.StringIO(data['privateKey']),password=data.get('password') or None)
        except (paramiko.SSHException,ValueError):continue
    raise ValueError('无法读取 SSH 私钥；若已加密，请在密码栏提供私钥口令')

def bundle(path):
    with tarfile.open(path,'w:gz') as archive:
        for name in ('bin','config','libexec','scripts','openrc','systemd','install.sh'):
            source=PROJECT/name
            if source.exists():archive.add(source,arcname='vpn-socks/'+name,filter=lambda info:None if '__pycache__' in info.name or info.name.endswith('.pyc') else info)

def ssh_run(client,command,timeout=900,on_line=None):
    channel=client.get_transport().open_session();channel.set_combine_stderr(True);channel.exec_command(command)
    deadline=time.monotonic()+timeout;buffer='';output=[]
    while True:
        if time.monotonic()>deadline:channel.close();raise ValueError('服务器步骤执行超时')
        if channel.recv_ready():
            buffer+=channel.recv(65536).decode(errors='replace')
            while '\n' in buffer:
                line,buffer=buffer.split('\n',1);output.append(line)
                if on_line:on_line(line)
        elif channel.exit_status_ready():break
        else:time.sleep(.1)
    if buffer:
        output.append(buffer)
        if on_line:on_line(buffer)
    return channel.recv_exit_status(),'\n'.join(output)

def job_worker(job,data):
    client=None;package=ROOT/(job+'.tar.gz');node=None
    try:
        with db() as c:c.execute("UPDATE jobs SET status='running' WHERE id=?",(job,))
        event(job,'ssh','running','连接 SSH 并检查主机密钥')
        client=paramiko.SSHClient();known=ROOT/'known_hosts'
        if not known.exists():known.touch(mode=0o600)
        client.load_host_keys(str(known));client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(data['ip'],port=data['sshPort'],username=data['username'],password=data.get('password') or None,pkey=key_for(data),timeout=15,auth_timeout=20,banner_timeout=20,allow_agent=False,look_for_keys=False)
        fingerprint=hashlib.sha256(client.get_transport().get_remote_server_key().asbytes()).hexdigest()
        event(job,'ssh','done','SSH 已连接，主机密钥 SHA256 '+fingerprint)
        code,out=ssh_run(client,'id -u; uname -m; cat /etc/os-release',timeout=20)
        if code or out.splitlines()[0]!='0':raise ValueError('自动部署需要 root 权限，请使用 root SSH 账户')
        if not any(line in ('ID=alpine','ID=debian','ID=ubuntu') for line in out.splitlines()):raise ValueError('当前自动安装支持 Alpine、Debian 和 Ubuntu')
        event(job,'upload','running','上传固定版本的部署脚本')
        remote='/root/.vpn-socks-jobs/'+job
        ssh_run(client,'umask 077; mkdir -p '+shlex.quote(remote),timeout=20)
        bundle(package)
        parameters={k:data[k] for k in ('domain','ip','port','path','region')}
        with client.open_sftp() as sftp:
            sftp.put(str(package),remote+'/source.tar.gz')
            with sftp.file(remote+'/request.json','w') as f:f.write(json.dumps(parameters))
            sftp.chmod(remote+'/request.json',0o600)
        code,_=ssh_run(client,'tar -xzf '+shlex.quote(remote+'/source.tar.gz')+' -C '+shlex.quote(remote),timeout=30)
        if code:raise ValueError('服务器无法解压部署包')
        result=[]
        def progress(line):
            try:
                item=json.loads(line)
                if item.get('kind')=='node':result.append(item['data'])
                elif item.get('step'):event(job,item['step'],item.get('state','running'),item.get('message',''))
            except (ValueError,TypeError):pass
        command='sh '+shlex.quote(remote+'/vpn-socks/scripts/bootstrap.sh')+' '+shlex.quote(remote)
        code,_=ssh_run(client,command,timeout=1000,on_line=progress)
        if code or not result:raise ValueError('服务器部署未完成，请查看上方步骤；原有入站不会被自动删除')
        node=result[-1]
        event(job,'cloudflare','running','自动配置橙云 DNS、回源端口与域名 TLS')
        payload={**parameters,'token':data['cfToken'],'ssl':data.get('ssl','full')}
        cf=subprocess.Popen(['node',str(PROJECT/'runner'/'cf-task.mjs')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:output,error=cf.communicate(json.dumps(payload)+'\n',timeout=120)
        except subprocess.TimeoutExpired:cf.kill();cf.communicate();raise ValueError('Cloudflare 配置超时') from None
        if cf.returncode:raise ValueError('Cloudflare 配置失败：'+error[-1000:].replace(data['cfToken'],'[redacted]'))
        event(job,'cloudflare','done','DNS 和回源规则已保存')
        event(job,'verify','running','验证完整 CF → VLESS → 所选国家出口链路')
        encoded=json.dumps({'region':data['region'],'port':data['port']})
        verifier=str(Path(remote)/'vpn-socks/scripts/verify-node.py')
        for attempt in range(12):
            code,out=ssh_run(client,'python3 '+shlex.quote(verifier)+' '+shlex.quote(encoded),timeout=30)
            if code==0:
                verified=json.loads(out.strip().splitlines()[-1]);node.update(verified);break
            time.sleep(5)
        else:raise ValueError('节点已安装，但完整链路或出口国家验收未通过；请检查域名生效状态和出口可用性')
        event(job,'verify','done','实际出口 '+node['exit_ip']+'，国家 '+node['country'])
        event(job,'complete','done','部署完成，节点链接已生成')
        with db() as c:c.execute("UPDATE jobs SET status='succeeded',result=? WHERE id=?",(json.dumps(node),job))
    except Exception as error:
        message='SSH 认证失败，请检查用户名和凭据' if isinstance(error,paramiko.AuthenticationException) else 'SSH 主机密钥发生变化，已停止连接' if isinstance(error,paramiko.BadHostKeyException) else str(error)
        for field in ('password','privateKey','cfToken'):
            if data.get(field):message=message.replace(data[field],'[redacted]')
        event(job,'error','error',message)
        with db() as c:c.execute("UPDATE jobs SET status='failed',error=?,result=? WHERE id=?",(message,json.dumps(node) if node else None,job))
    finally:
        if client:client.close()
        package.unlink(missing_ok=True)
        for field in ('password','privateKey','cfToken'):data[field]=''

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,data):
        raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def authorized(self):
        token=self.headers.get('Authorization','').removeprefix('Bearer ')
        expected=json.loads(CONFIG.read_text())['auth_sha256']
        return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),expected)
    def do_GET(self):
        if not self.authorized():return self.send(401,{'error':'Unauthorized'})
        actor=self.headers.get('X-Actor','');path=urllib.parse.urlparse(self.path).path
        if path=='/health':return self.send(200,{'ok':True})
        if path=='/regions':
            try:return self.send(200,regions())
            except Exception as error:return self.send(503,{'error':str(error)})
        if not actor:return self.send(403,{'error':'Actor required'})
        with db() as c:
            if path=='/jobs':
                rows=c.execute('SELECT id,status,created,config,result,error FROM jobs WHERE actor=? ORDER BY created DESC LIMIT 20',(actor,)).fetchall()
                return self.send(200,{'jobs':[{**dict(r),'config':json.loads(r['config']),'result':json.loads(r['result']) if r['result'] else None} for r in rows]})
            if re.fullmatch('/jobs/[a-f0-9]{32}',path):
                job=path.rsplit('/',1)[1];row=c.execute('SELECT * FROM jobs WHERE id=? AND actor=?',(job,actor)).fetchone()
                if not row:return self.send(404,{'error':'Task not found'})
                events=[dict(r) for r in c.execute('SELECT seq,time,step,state,message FROM events WHERE job=? ORDER BY seq',(job,))]
                return self.send(200,{'id':job,'status':row['status'],'config':json.loads(row['config']),'result':json.loads(row['result']) if row['result'] else None,'error':row['error'],'events':events})
        self.send(404,{'error':'Not found'})
    def do_POST(self):
        if not self.authorized():return self.send(401,{'error':'Unauthorized'})
        actor=self.headers.get('X-Actor','')
        if not re.fullmatch('[a-zA-Z0-9_-]{1,120}',actor):return self.send(403,{'error':'Actor required'})
        if self.path=='/regions/refresh':
            try:return self.send(200,regions(force=True))
            except Exception as error:return self.send(503,{'error':str(error)})
        if self.path!='/jobs':return self.send(404,{'error':'Not found'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=65536:raise ValueError('请求大小无效')
            data=validate(json.loads(self.rfile.read(length)))
            if data['region'] not in {r['code'] for r in regions()['regions']}:raise ValueError('该国家当前没有候选出口')
            with db() as c:
                count=c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
                if count>=4:return self.send(429,{'error':'部署队列已满，请等待已有任务结束'})
                job=secrets.token_hex(16);public={k:data[k] for k in ('ip','domain','port','path','region','sshPort')}
                c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',(job,actor,'queued',time.time(),json.dumps(public),None,None))
            event(job,'queue','running','任务已进入队列；关闭网页不会中断后台部署')
            EXECUTOR.submit(job_worker,job,data)
            return self.send(202,{'id':job,'status':'queued'})
        except Exception as error:return self.send(400,{'error':str(error)})

if __name__=='__main__':
    init();http.server.ThreadingHTTPServer(('127.0.0.1',35013),Handler).serve_forever()
