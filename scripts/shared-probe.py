#!/usr/bin/env python3
"""One shared Xray process for all node health probes on a server."""
import copy,json,signal,subprocess,time
from pathlib import Path
ROOT=Path('/var/lib/fanout-nodes')
def aggregate(root=ROOT):
 result={'log':{'loglevel':'error','access':'none'},'inbounds':[],'outbounds':[],'routing':{'rules':[]}}
 for node in sorted(root.glob('*')):
  if not node.is_dir() or not (node/'enabled').exists() or (node/'disabled').exists():continue
  source=copy.deepcopy(json.loads((node/'ha/probe.json').read_text()));prefix='n'+node.name+'_'
  for field in ('inbounds','outbounds'):
   for entry in source[field]:entry['tag']=prefix+entry['tag'];result[field].append(entry)
  for rule in source['routing']['rules']:
   rule['inboundTag']=[prefix+tag for tag in rule['inboundTag']];rule['outboundTag']=prefix+rule['outboundTag'];result['routing']['rules'].append(rule)
 return result
if __name__=='__main__':
 child=None;previous=None
 def stopped(*args):raise KeyboardInterrupt
 signal.signal(signal.SIGTERM,stopped);signal.signal(signal.SIGINT,stopped)
 try:
  while True:
   try:
    config=aggregate();encoded=json.dumps(config,sort_keys=True)
    if encoded!=previous or child and child.poll() is not None:
     if child:
      child.terminate()
      try:child.wait(timeout=10)
      except subprocess.TimeoutExpired:child.kill();child.wait()
      child=None
     if config['inbounds']:
      file=ROOT/'shared-probe.json';temporary=file.with_suffix('.tmp');temporary.write_text(encoded);temporary.chmod(0o600);temporary.replace(file)
      child=subprocess.Popen(['/var/lib/fanout/bin/xray','run','-config',str(file)])
     previous=encoded
   except Exception as error:print('Shared health probe update failed: '+str(error),flush=True)
   time.sleep(3)
 except KeyboardInterrupt:pass
 finally:
  if child:
   child.terminate()
   try:child.wait(timeout=10)
   except subprocess.TimeoutExpired:child.kill();child.wait()
