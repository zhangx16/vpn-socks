#!/usr/bin/env python3
import json,os,signal,subprocess,sys,time
from pathlib import Path
port=int(sys.argv[1]);node=Path('/var/lib/fanout-nodes')/str(port);cfg=json.loads((node/'node.json').read_text());children={}
env={**os.environ,'FANOUT_NODE_MODE':'1','FANOUT_HA_DIR':str(node/'ha'),'FANOUT_SPEED_DIR':str(node/'speed'),'FANOUT_HA_CONFIG':str(node/'ha.json'),'FANOUT_HA_LOCK':str(node/'ha.lock'),'FANOUT_SPEED_LOCK':str(node/'speed.lock'),'FANOUT_CF_PROXY':'socks5h://127.0.0.1:'+str(cfg['cf_port']),'FANOUT_ORIGIN_PROXY':'socks5h://127.0.0.1:'+str(cfg['origin_port'])}
commands={'probe':['/var/lib/fanout/bin/xray','run','-config',str(node/'ha/probe.json')],'ha':['/usr/local/sbin/fanout-ha'],'speed':['/usr/local/sbin/fanout-speed']}
def stopped(*args):raise KeyboardInterrupt
signal.signal(signal.SIGTERM,stopped);signal.signal(signal.SIGINT,stopped)
try:
 while not (node/'disabled').exists():
  for name,command in commands.items():
   if name not in children or children[name].poll() is not None:children[name]=subprocess.Popen(command,env=env,start_new_session=True)
  time.sleep(5)
except KeyboardInterrupt:pass
finally:
 for child in children.values():
  try:os.killpg(child.pid,signal.SIGTERM)
  except ProcessLookupError:pass
 for child in children.values():
  try:child.wait(timeout=25)
  except subprocess.TimeoutExpired:
   try:os.killpg(child.pid,signal.SIGKILL)
   except ProcessLookupError:pass
