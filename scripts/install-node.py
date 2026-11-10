#!/usr/bin/env python3
"""Install isolated monitors for a single inbound on OpenRC or systemd."""
import json,os,shutil,socket,subprocess,sys
from pathlib import Path
project=Path(__file__).resolve().parents[1];domain,region,port=sys.argv[1],sys.argv[2],int(sys.argv[3]);os.umask(0o077)
node=Path('/var/lib/fanout-nodes')/str(port);node.mkdir(parents=True,exist_ok=True);(node/'ha').mkdir(exist_ok=True);(node/'speed').mkdir(exist_ok=True)
configuration=node/'node.json'
if configuration.exists() and not (node/'disabled').exists():cfg=json.loads(configuration.read_text())
else:
 sockets=[];ports=[]
 for candidate in range(18000,20000):
  s=socket.socket()
  try:s.bind(('127.0.0.1',candidate))
  except OSError:s.close();continue
  sockets.append(s);ports.append(candidate)
  if len(ports)==2:break
 if len(ports)!=2:raise SystemExit('No free loopback probe ports')
 cfg={'cf_port':ports[0],'origin_port':ports[1]}
 for s in sockets:s.close()
cfg.update(domain=domain,region=region,port=port);configuration.write_text(json.dumps(cfg))
if (node/'disabled').exists():
 for file in ('managed-slots.json','state.json','selection.json'):(node/'speed'/file).unlink(missing_ok=True)
 for file in ('switch-request.json','switch-result.json','active-slot','status.json'):(node/'ha'/file).unlink(missing_ok=True)
env={**os.environ,'FANOUT_NODE_MODE':'1','FANOUT_HA_DIR':str(node/'ha'),'FANOUT_SPEED_DIR':str(node/'speed'),'FANOUT_HA_CONFIG':str(node/'ha.json'),'FANOUT_CF_PORT':str(cfg['cf_port']),'FANOUT_ORIGIN_PORT':str(cfg['origin_port'])}
subprocess.run(['python3',str(project/'scripts/configure-probes.py'),'--domain',domain,'--region',region,'--port',str(port),'--allow-single'],env=env,check=True)
subprocess.run(['/var/lib/fanout/bin/xray','run','-test','-config',str(node/'ha/probe.json')],check=True)
Path('/usr/local/libexec/fanout').mkdir(parents=True,exist_ok=True)
for source,target in [(project/'bin/fanout-ha',Path('/usr/local/sbin/fanout-ha')),(project/'bin/fanout-speed',Path('/usr/local/sbin/fanout-speed'))]+[(project/'libexec'/f,Path('/usr/local/libexec/fanout')/f) for f in ('scan-jp','catalog_pool.py','pool_server.py')]+[(project/'scripts/node-supervisor.py',Path('/usr/local/libexec/fanout/node-supervisor.py'))]:
 shutil.copy2(source,target);target.chmod(0o755)
# Migrate an old monitor only when it targets this same inbound.
legacy=Path('/etc/fanout-ha.json');openrc=shutil.which('rc-service');service='fanout-node-'+str(port)
if legacy.exists() and json.loads(legacy.read_text()).get('primary_inbound_tag')=='in-'+str(port)+'-ws':
 for name in ('fanout-speed','fanout-ha','fanout-probe'):
  subprocess.run(['rc-service',name,'stop'] if openrc else ['systemctl','disable','--now',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  if openrc:subprocess.run(['rc-update','del',name,'default'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
(node/'disabled').unlink(missing_ok=True)
if openrc:
 target=Path('/etc/init.d')/service
 target.write_text('#!/sbin/openrc-run\ncommand="/usr/bin/python3"\ncommand_args="/usr/local/libexec/fanout/node-supervisor.py '+str(port)+'"\ncommand_background=true\npidfile="/run/'+service+'.pid"\nsupervisor=supervise-daemon\nrespawn_delay=5\nrespawn_max=0\noutput_log="/var/log/'+service+'.log"\nerror_log="/var/log/'+service+'.log"\ndepend() { need net fanout; }\n');target.chmod(0o755)
 subprocess.run(['rc-update','add',service,'default'],check=True);subprocess.run(['rc-service',service,'restart'],check=True)
else:
 target=Path('/etc/systemd/system')/(service+'.service');target.write_text('[Unit]\nAfter=network-online.target fanout.service\nRequires=fanout.service\n[Service]\nExecStart=/usr/bin/python3 /usr/local/libexec/fanout/node-supervisor.py '+str(port)+'\nRestart=always\nRestartSec=5\nKillMode=control-group\n[Install]\nWantedBy=multi-user.target\n')
 subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','enable',service],check=True);subprocess.run(['systemctl','restart',service],check=True)
print('Independent node monitors installed on loopback ports '+str(cfg['cf_port'])+'/'+str(cfg['origin_port']))
