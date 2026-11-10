"""Server-side SSH credential vault; APIs return metadata only."""
import hashlib,ipaddress,json,os,re,sqlite3,time
from pathlib import Path
from cryptography.fernet import Fernet

def connection(root):
 c=sqlite3.connect(Path(root)/'ssh-vault.sqlite',timeout=15);c.row_factory=sqlite3.Row;c.execute('PRAGMA secure_delete=ON');c.execute("CREATE TABLE IF NOT EXISTS servers(id TEXT PRIMARY KEY,ip TEXT,port INTEGER,username TEXT,secret BLOB,updated REAL,remark TEXT DEFAULT '')")
 if 'remark' not in [row[1] for row in c.execute('PRAGMA table_info(servers)')]:c.execute("ALTER TABLE servers ADD COLUMN remark TEXT DEFAULT ''");c.commit()
 return c

def cipher(root):
 file=Path(root)/'ssh-vault.key'
 try:
  fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 except FileExistsError:pass
 else:
  with os.fdopen(fd,'wb') as stream:stream.write(Fernet.generate_key())
 return Fernet(file.read_bytes())

def validate(data):
 ip=ipaddress.ip_address(data.get('ip',''));port=int(data.get('sshPort',22));user=data.get('username') or 'root'
 if ip.version!=4 or not ip.is_global:raise ValueError('SSH 地址必须是公网 IPv4')
 if not 1<=port<=65535 or not re.fullmatch('[a-zA-Z_][a-zA-Z0-9_-]{0,63}',user):raise ValueError('SSH 端口或用户名无效')
 password=data.get('password') or '';key=data.get('privateKey') or ''
 if not isinstance(password,str) or not isinstance(key,str) or len(password)>512 or len(key)>24000:raise ValueError('SSH 凭据格式无效')

 return str(ip),port,user,{'password':password,'privateKey':key}

def save(root,data):
 ip,port,user,secret=validate(data);identity=hashlib.sha256((ip+':'+str(port)+':'+user).encode()).hexdigest()[:32]
 remark=data.get('remark')
 if remark is not None and (not isinstance(remark,str) or len(remark)>120):raise ValueError('服务器备注最多 120 字')
 with connection(root) as c:
  old=c.execute('SELECT secret,remark FROM servers WHERE id=?',(identity,)).fetchone()
  encrypted=cipher(root).encrypt(json.dumps(secret).encode()) if secret['password'] or secret['privateKey'] else old['secret'] if old else None
  note=remark.strip() if remark is not None else old['remark'] if old else ''
  c.execute('INSERT OR REPLACE INTO servers(id,ip,port,username,secret,updated,remark) VALUES(?,?,?,?,?,?,?)',(identity,ip,port,user,encrypted,time.time(),note))
 return identity

def list_servers(root):
 with connection(root) as c:return [dict(r) for r in c.execute('SELECT id,ip,port AS sshPort,username,updated,remark,(secret IS NOT NULL) AS hasCredentials FROM servers ORDER BY updated DESC')]

def load(root,identity):
 with connection(root) as c:row=c.execute('SELECT * FROM servers WHERE id=?',(identity,)).fetchone()
 if not row or not row['secret']:raise ValueError('保存的 SSH 信息不存在，请重新填写')
 secret=json.loads(cipher(root).decrypt(row['secret']));return {'ip':row['ip'],'sshPort':row['port'],'username':row['username'],**secret}

def delete(root,identity):
 with connection(root) as c:c.execute('DELETE FROM servers WHERE id=?',(identity,))

def resolve(root,data,target=None):
 data=dict(data);target=target or data;identity=data.get('serverId')
 if not identity and not data.get('password') and not data.get('privateKey'):
  matched=next((r for r in list_servers(root) if r['hasCredentials'] and r['ip']==target.get('ip') and r['sshPort']==int(target.get('sshPort',22)) and r['username']==(data.get('username') or 'root')),None)
  if matched:identity=matched['id']
 if identity and not (data.get('password') or data.get('privateKey')):
  saved=load(root,identity)
  if saved['ip']!=target.get('ip') or saved['sshPort']!=int(target.get('sshPort',22)):raise ValueError('保存的 SSH 信息与目标服务器不匹配')
  data.update(saved)
 return data
