#!/usr/bin/env python3
"""Share mapped TLS ports by hostname and exact WS path, preserving native listeners."""
import json,os,re,shutil,socket,subprocess,sys
from pathlib import Path
ROOT=Path('/var/lib/fanout-ingress')
def key(domain,path):return domain+'|'+path
def registry():
 file=ROOT/'nodes.json';old=json.loads(file.read_text()) if file.exists() else {}
 return {key(name.split('|')[0],item['path']):item for name,item in old.items()}
def native():return json.loads(Path('/var/lib/fanout/native.json').read_text())['inbounds']
def directory():return Path('/etc/nginx/http.d') if Path('/etc/alpine-release').exists() else Path('/etc/nginx/conf.d')
def reload_nginx():
 subprocess.run(['nginx','-t'],check=True)
 if shutil.which('rc-service'):
  if subprocess.run(['rc-service','nginx','reload'],stdout=subprocess.DEVNULL).returncode:subprocess.run(['rc-service','nginx','start'],check=True)
  subprocess.run(['rc-update','add','nginx','default'],check=True)
 else:subprocess.run(['systemctl','enable','--now','nginx'],check=True);subprocess.run(['systemctl','reload','nginx'],check=True)
def render(nodes,ports,domain):
 entries=[(k.split('|')[1],item) for k,item in nodes.items() if k.split('|')[0]==domain];target=directory()/('vpn-node-'+domain+'.conf')
 runner=Path('/etc/nginx/http.d/vpn-runner.conf')
 if runner.exists() and 'server_name '+domain+';' in runner.read_text():
  # Keep the runner-owned server block and add exact paths inside its existing location.
  text=runner.read_text();marker='# vpn-node-paths '+domain
  block_re=r'\n # vpn-node-paths '+re.escape(domain)+r'\n.*?\n # end-vpn-node-paths '+re.escape(domain)+r'\n'
  text=re.sub(block_re,'\n',text,flags=re.S)
  locations=''.join(location(path,item['port'],domain) for path,item in entries)
  if locations:text=text.replace('server_name '+domain+';', 'server_name '+domain+';\n '+marker+'\n'+locations+'\n # end-vpn-node-paths '+domain+'\n',1)
  runner.write_text(text);return
 if not entries:target.unlink(missing_ok=True);return
 public={item['public_port'] for _,item in entries}
 if len(public)!=1:raise ValueError('同一域名的多个路径必须共用一个公网端口')
 edge=ports[str(next(iter(public)))]['edge'];inbounds=native();first=next((i for i in inbounds if i['port']==entries[0][1]['port']),None)
 if not first:raise ValueError('Ingress target does not exist')
 cert,keyfile=first['tls']['cert_file'],first['tls']['key_file']
 if not re.fullmatch('[a-z0-9.-]+',domain) or not all(re.fullmatch('/[a-zA-Z0-9/_.-]+',s) for s in (cert,keyfile)):raise ValueError('Unsafe ingress config')
 content='server {\n listen '+str(edge)+' ssl;\n server_name '+domain+';\n ssl_certificate '+cert+';\n ssl_certificate_key '+keyfile+';\n'
 content+=''.join(location(path,item['port'],domain) for path,item in entries)
 content+=' location / { return 404; }\n}\n';target.write_text(content)
def location(path,port,domain):
 if not re.fullmatch('/[a-zA-Z0-9/_~.%-]*',path):raise ValueError('Unsafe path')
 return ''' location = PATH {
  proxy_pass https://127.0.0.1:INTERNAL;
  proxy_ssl_verify off;
  proxy_ssl_server_name on;
  proxy_ssl_name DOMAIN;
  proxy_http_version 1.1;
  proxy_set_header Host $host;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
  proxy_read_timeout 3600s;
 }
'''.replace('PATH',path).replace('INTERNAL',str(port)).replace('DOMAIN',domain)
def save(nodes,ports):
 temporary=ROOT/'nodes.tmp';temporary.write_text(json.dumps(nodes));temporary.replace(ROOT/'nodes.json');(ROOT/'ports.json').write_text(json.dumps(ports))
def install(request):
 os.umask(0o077);public=int(request.get('public_port',request['port']));internal=int(request['port']);ROOT.mkdir(parents=True,exist_ok=True);nodes=registry();name=request['domain'];identity=key(name,request['path'])
 if any(k.split('|')[0]==name and item['public_port']!=public for k,item in nodes.items()):raise ValueError('同一域名的多个节点须填写相同公网端口')
 if identity in nodes and nodes[identity]['port']!=internal:raise ValueError('域名与路径已被其他入站使用')
 nodes[identity]={'port':internal,'public_port':public,'path':request['path']}
 old=next((i for i in native() if i['port']==public and i.get('security')=='tls'),None)
 if old:nodes.setdefault(key(old['tls']['server_name'],old['path']),{'port':public,'public_port':public,'path':old['path']})
 mapping=ROOT/'ports.json';ports=json.loads(mapping.read_text()) if mapping.exists() else {}
 if str(public) not in ports:
  existing=subprocess.run(['iptables','-t','nat','-S','PREROUTING'],capture_output=True,text=True,check=True).stdout
  match=re.search(r'--dport '+str(public)+r' .*--comment vpn-runner-proxy .*--to-ports (\d+)',existing)
  if match:edge=int(match[1]);owned=False
  else:
   for edge in range(42000,43000):
    if edge in [int(x['edge']) for x in ports.values()]:continue
    s=socket.socket()
    try:s.bind(('0.0.0.0',edge));s.close();break
    except OSError:s.close()
   else:raise ValueError('No free ingress port')
   owned=True
  ports[str(public)]={'edge':edge,'owned':owned}
 directory().mkdir(parents=True,exist_ok=True)
 for domain in {k.split('|')[0] for k,item in nodes.items() if item['public_port']==public}:render(nodes,ports,domain)
 reload_nginx();save(nodes,ports)
 script=Path('/usr/local/libexec/fanout/ingress-rules');script.parent.mkdir(parents=True,exist_ok=True)
 if Path(__file__).resolve()!=script.parent/'ingress.py':shutil.copy2(__file__,script.parent/'ingress.py')
 rules=['#!/bin/sh','set -eu']
 for source,value in ports.items():
  if not value['owned']:continue
  args='-p tcp --dport '+source+' -m comment --comment vpn-node-ingress -j REDIRECT --to-ports '+str(value['edge'])
  rules.append('iptables -t nat -C PREROUTING '+args+' 2>/dev/null || iptables -t nat -I PREROUTING 1 '+args)
 script.write_text('\n'.join(rules)+'\n');script.chmod(0o700)
 if shutil.which('rc-service'):
  init=Path('/etc/init.d/fanout-ingress');init.write_text('#!/sbin/openrc-run\ndepend() { need net nginx; }\nstart() { /usr/local/libexec/fanout/ingress-rules; }\n');init.chmod(0o755);subprocess.run(['rc-update','add','fanout-ingress','default'],check=True)
 else:
  Path('/etc/systemd/system/fanout-ingress.service').write_text('[Unit]\nAfter=network-online.target nginx.service\nWants=nginx.service\n[Service]\nType=oneshot\nRemainAfterExit=true\nExecStart=/usr/local/libexec/fanout/ingress-rules\n[Install]\nWantedBy=multi-user.target\n');subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','enable','fanout-ingress'],check=True)
 subprocess.run([str(script)],check=True)
def remove(request):
 nodes=registry();identity=key(request['domain'],request['path']);current=nodes.get(identity)
 if current and current['port']!=request['port']:raise ValueError('Ingress target changed; refusing removal')
 nodes.pop(identity,None);ports=json.loads((ROOT/'ports.json').read_text());render(nodes,ports,request['domain']);reload_nginx();save(nodes,ports)
if __name__=='__main__':
 value=json.loads(sys.argv[1]);remove(value) if value.get('operation')=='remove' else install(value)
