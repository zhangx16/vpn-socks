#!/usr/bin/env python3
"""Generate private health-client config using credentials already on this host."""
import argparse
import json
import os
import http.cookiejar
import urllib.parse
import urllib.request
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--domain',required=True)
parser.add_argument('--port',type=int,default=33003)
parser.add_argument('--region',default='JP')
parser.add_argument('--allow-single',action='store_true')
args=parser.parse_args()
if len(args.region)!=2 or not args.region.isalpha() or not args.region.isupper(): parser.error("region must be a two-letter country code")
if not args.domain or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in args.domain):
    parser.error('domain must be a DNS hostname')
os.umask(0o077)
store=json.loads(Path('/var/lib/fanout/native.json').read_text())
inbound=next((r for r in store['inbounds'] if r['port']==args.port and r['protocol']=='vless' and r['network']=='ws' and r['security']=='tls'),None)
if not inbound: raise SystemExit('Create a native VLESS WS TLS inbound on the selected port in fanout first')
client=next((r for r in inbound['clients'] if r['enable']),None)
if not client: raise SystemExit('No enabled client found on inbound 33003')
outbounds=[]
for tag,host,port in [('cf',args.domain,443),('origin','127.0.0.1',args.port)]:
    tls={'serverName':args.domain}
    if tag=='origin': tls['certificates']=[{'certificateFile':inbound['tls']['cert_file'],'usage':'verify'}]
    outbounds.append({'tag':tag,'protocol':'vless','settings':{'vnext':[{'address':host,'port':port,'users':[{'id':client['id'],'encryption':'none'}]}]},
        'streamSettings':{'network':'ws','security':'tls','tlsSettings':tls,'wsSettings':{'path':inbound['path'],'host':args.domain}}})
config={'log':{'loglevel':'error','access':'none'},'inbounds':[
    {'tag':tag+'-check','listen':'127.0.0.1','port':port,'protocol':'socks','settings':{'auth':'noauth','udp':False}}
    for tag,port in [('cf',int(os.environ.get('FANOUT_CF_PORT','10809'))),('origin',int(os.environ.get('FANOUT_ORIGIN_PORT','10810')))]],
    'outbounds':outbounds,'routing':{'rules':[{'type':'field','inboundTag':[tag+'-check'],'outboundTag':tag} for tag in ['origin','cf']]}}
directory=Path(os.environ.get('FANOUT_HA_DIR','/var/lib/fanout-ha'))
directory.mkdir(mode=0o700,exist_ok=True)
output=directory/'probe.json'
output.write_text(json.dumps(config,indent=2)+'\n')
os.chmod(output,0o600)
print('Private probe configuration generated; client credentials were not printed.')
tags=['in-'+str(args.port)+'-ws']
if not os.environ.get('FANOUT_NODE_MODE') and args.port==33003 and any(r['port']==33002 and r['network']=='ws' for r in store['inbounds']): tags.append('in-33002-ws')
Path(os.environ.get('FANOUT_HA_CONFIG','/etc/fanout-ha.json')).write_text(json.dumps({'region':args.region,'primary_inbound_tag':tags[0],'inbound_tags':tags},indent=2)+'\n')
managed=Path(os.environ.get('FANOUT_SPEED_DIR','/var/lib/fanout-speed'))/'managed-slots.json'
if not managed.exists() or os.environ.get('FANOUT_NODE_MODE'):
    settings=json.loads(Path('/var/lib/fanout/settings.json').read_text())
    base='http://127.0.0.1:'+str(settings['port'])+'/'+Path('/var/lib/fanout/basepath').read_text().strip()
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    password=Path('/var/lib/fanout/password').read_text().strip()
    with opener.open(base+'/login',urllib.parse.urlencode({'password':password}).encode(),timeout=10) as response:
        json.load(response)
    with opener.open(urllib.request.Request(base+'/api/settings',data=b'{"residential_only":false}',headers={'Content-Type':'application/json'},method='POST'),timeout=10) as response:json.load(response)
    with opener.open(base+'/api/exits',timeout=10) as response: exits=json.load(response)['exits']
    active=next((row for row in exits if any(i['tag']==tags[0] for i in row.get('inbounds') or [])),None)
    if not active or active['region']!=args.region: raise SystemExit('Bind the selected TLS inbound to a '+args.region+' exit in fanout first')
    reserved=set()
    legacy=Path('/etc/fanout-ha.json');legacy_slots=Path('/var/lib/fanout-speed/managed-slots.json')
    if os.environ.get('FANOUT_NODE_MODE') and legacy.exists() and legacy_slots.exists() and json.loads(legacy.read_text()).get('primary_inbound_tag')!=tags[0]:reserved.update(json.loads(legacy_slots.read_text()))
    for file in Path('/var/lib/fanout-nodes').glob('*/speed/managed-slots.json'):
        if (file.parent.parent/'disabled').exists():continue
        if file!=managed:reserved.update(json.loads(file.read_text()))
    standby=next((row for row in exits if row['slot'] not in reserved and row['slot']!=active['slot'] and row['region']==args.region and not row.get('inbounds')),None)
    if not standby and not args.allow_single: raise SystemExit('Create a second unbound '+args.region+' exit in fanout first')
    managed.parent.mkdir(mode=0o700,exist_ok=True)
    managed.write_text(json.dumps([active['slot']]+([standby['slot']] if standby else []))+'\n')
    os.chmod(managed,0o600)
    print('Adopted the current regional exit'+(' and a standby.' if standby else '; no independent standby is available.'))
