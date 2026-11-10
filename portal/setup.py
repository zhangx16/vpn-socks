#!/usr/bin/env python3
"""Create/reset local administrator settings using hidden prompts."""
import getpass,hashlib,json,os,secrets,sqlite3
from pathlib import Path
os.umask(0o077);target=Path('/etc/vpn-control.json');cfg=json.loads(target.read_text()) if target.exists() else {}
cfg['hostname']=input('Console hostname: ').strip().lower();cfg['username']=input('Administrator username [admin]: ').strip() or 'admin'
password=getpass.getpass('Administrator password (14+ characters): ')
if len(password)<14 or password!=getpass.getpass('Confirm password: '):raise SystemExit('Password is too short or confirmation does not match')
cfg['password_salt']=secrets.token_hex(24);cfg['password_hash']=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(cfg['password_salt']),600000).hex();cfg['runner_token']=cfg.get('runner_token') or secrets.token_urlsafe(48)
cf=getpass.getpass('Cloudflare API token (leave blank to keep existing): ')
if cf:cfg['cf_token']=cf
cfg.setdefault('nodes',[]);cfg.setdefault('protected_hosts',[]);target.write_text(json.dumps(cfg));target.chmod(0o600)
runner=Path('/etc/vpn-runner.json');runner.write_text(json.dumps({'auth_sha256':hashlib.sha256(cfg['runner_token'].encode()).hexdigest(),'hostname':cfg['hostname'],'reserved_hosts':cfg['protected_hosts']}));runner.chmod(0o600)
auth=Path('/var/lib/vpn-control/auth.sqlite')
if auth.exists():
 with sqlite3.connect(auth) as c:c.execute('DELETE FROM sessions')
print('Configuration saved. Old sessions revoked. Restart vpn-control and vpn-runner.')
