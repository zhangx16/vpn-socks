#!/usr/bin/env python3
"""Bounded official-source collection and expiring, deduplicated OpenVPN pool."""
import base64,concurrent.futures,csv,fcntl,html,io,ipaddress,json,os,re,subprocess,time
from pathlib import Path
FIELDS='HostName,IP,Score,Ping,Speed,CountryLong,CountryShort,NumVpnSessions,Uptime,TotalUsers,TotalTraffic,LogType,Operator,Message,OpenVPN_ConfigData_Base64'.split(',')
PRIMARY='https://www.vpngate.net/api/iphone/'
MIRRORS='https://www.vpngate.net/en/sites.aspx'
TTL=86400
def download(url):
    result=subprocess.run(['curl','-4','-fsSL','--connect-timeout','4','--max-time','9','--max-filesize','5000000',url],capture_output=True,timeout=12)
    if result.returncode:raise ValueError('source unavailable')
    return result.stdout.decode('utf-8-sig')

def parse(text):
    start=text.find('#HostName,')
    if start<0:raise ValueError('CSV header missing')
    rows=[]
    for raw in csv.DictReader(io.StringIO(text[start+1:])):
        host=raw.get('HostName') or '';code=raw.get('CountryShort') or ''
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}',host) or not re.fullmatch('[A-Z]{2}',code):continue
        try:
            address=ipaddress.ip_address(raw.get('IP',''))
            if address.version!=4 or not address.is_global:continue
            encoded=raw.get('OpenVPN_ConfigData_Base64') or ''
            if len(encoded)>150000:continue
            config=base64.b64decode(encoded,validate=True).decode('utf-8')
            if not re.search(r'(?m)^\s*remote\s+',config):continue
            # Public mirror data must not introduce executable client directives.
            forbidden=r'(?im)^\s*(?:--)?(?:up|down|route-up|route-pre-down|ipchange|plugin|management(?:-[a-z-]+)?|config|script-security|tls-verify|tls-crypt-v2-verify|auth-user-pass-verify|client-connect|client-disconnect|learn-address|iproute|log|log-append|status|writepid|cd|chroot|daemon|engine|pkcs11-providers)\s'
            if re.search(forbidden,config):continue
            row={k:str(raw.get(k) or '') for k in FIELDS}
            for k in ('Score','Ping','Speed','NumVpnSessions','Uptime','TotalUsers','TotalTraffic'):
                if not re.fullmatch(r'\d{1,25}',row[k]):row[k]='0'
            row['IP']=str(address);rows.append(row)
        except (ValueError,UnicodeError):continue
    if not rows:raise ValueError('No eligible OpenVPN records')
    return rows

def mirror_sources(text,limit=4):
    urls=[]
    for match in re.findall(r'href=[\x27\"](http://[0-9.]+:[0-9]+/en/)',html.unescape(text),re.I):
        from urllib.parse import urlsplit
        parsed=urlsplit(match)
        try:
            if not ipaddress.ip_address(parsed.hostname).is_global:continue
            if not 1<=parsed.port<=65535:continue
        except ValueError:continue
        url=match.rsplit('/en/',1)[0]+'/api/iphone/'
        if url not in urls:urls.append(url)
    return urls[:limit]

def merge(previous,batches,now):
    result={k:v for k,v in previous.items() if now-v.get('last_seen',0)<=TTL}
    fresh=[]
    for source,rows in batches:
        for row in rows:fresh.append((source,row))
    # A changed address for a hostname supersedes its obsolete configuration.
    latest={row['HostName']:row['IP'] for _,row in fresh}
    result={k:v for k,v in result.items() if v['row']['HostName'] not in latest or v['row']['IP']==latest[v['row']['HostName']]}
    for source,row in fresh:
        key=row['HostName']+'|'+row['IP']
        result[key]={'row':row,'last_seen':now,'sources':sorted(set(result.get(key,{}).get('sources',[])+[source]))}
    # One public IP represents one candidate exit, rather than inflating aliases.
    by_host={};by_ip={}
    for item in sorted(result.values(),key=lambda x:(x['last_seen'],int(x['row'].get('Speed') or 0))):by_host[item['row']['HostName']]=item
    for item in sorted(by_host.values(),key=lambda x:(x['last_seen'],int(x['row'].get('Speed') or 0))):by_ip[item['row']['IP']]=item
    return {v['row']['HostName']+'|'+ip:v for ip,v in by_ip.items()}

def render(items):
    output=io.StringIO();output.write('*vpn_servers\n#');writer=csv.DictWriter(output,fieldnames=FIELDS,lineterminator='\n');writer.writeheader()
    for item in sorted(items.values(),key=lambda x:int(x['row']['Speed']),reverse=True):writer.writerow(item['row'])
    output.write('*\n');return output.getvalue()

def peer_snapshot(peer,now):
    # Operator-configured peers use a forced read-only SSH key and pinned host key.
    command=['ssh','-T','-i',peer['key_file'],'-p',str(int(peer['port'])),'-o','BatchMode=yes','-o','ConnectTimeout=4','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+peer['known_hosts_file'],peer['user']+'@'+peer['host']]
    response=subprocess.run(command,capture_output=True,timeout=9)
    if response.returncode or len(response.stdout)>40_000_000:raise ValueError('peer unavailable')
    state=json.loads(response.stdout);items=state.get('items',{})
    validated={r['HostName']+'|'+r['IP']:r for r in parse(render(items))}
    result={}
    for key,item in items.items():
        seen=item.get('last_seen',0)
        if key not in validated or not now-TTL<=seen<=now+60:continue
        result[key]={'row':validated[key],'last_seen':min(seen,now),'sources':['managed-peer']}
    return result

def collect(directory,force=False):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (directory/'pool.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        state={}
        try:state=json.loads((directory/'pool.json').read_text())
        except (OSError,ValueError):pass
        now=time.time()
        if not force and state.get('updated_at',0)>now-600 and state.get('schema')==1:return state
        sources=[PRIMARY]
        try:
            mirrors=mirror_sources(download(MIRRORS),12)
            if mirrors:
                offset=int(now//600)%len(mirrors)
                sources+=(mirrors[offset:]+mirrors[:offset])[:4]
        except Exception:pass
        batches=[];report=[];peer_items={}
        try:peers=json.loads((directory/'peers.json').read_text())
        except (OSError,ValueError):peers=[]
        def fetch(source):return source,parse(download(source))
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures={executor.submit(fetch,s):s for s in sources}
            peer_futures={executor.submit(peer_snapshot,p,now):p.get('name','managed-peer') for p in peers[:2]}
            for future in concurrent.futures.as_completed(futures):
                source=futures[future]
                try:
                    _,rows=future.result();batches.append((source,rows));report.append({'source':source,'records':len(rows),'ok':True})
                except Exception:report.append({'source':source,'records':0,'ok':False})
            for future,name in peer_futures.items():
                try:
                    found=future.result()
                    for key,item in found.items():
                        if item['last_seen']>peer_items.get(key,{}).get('last_seen',0):peer_items[key]=item
                    report.append({'source':name,'records':len(found),'ok':True})
                except Exception:report.append({'source':name,'records':0,'ok':False})
        if not batches and not peer_items:
            if force:raise ValueError('所有官方来源暂时不可用，保留原候选池')
            items=merge(state.get('items',{}),[],now)
            if not items:raise ValueError('候选池已过期且所有来源不可用')
            return {**state,'items':items,'stale':True}
        previous=state.get('items',{}).copy()
        for key,item in peer_items.items():
            if item['last_seen']>previous.get(key,{}).get('last_seen',0):previous[key]=item
        items=merge(previous,batches,now)
        state={'schema':1,'updated_at':now,'scope':'all','stale':False,'items':items,'sources':report,'ttl_seconds':TTL,'fresh_unique_ips':len({row['IP'] for _,rows in batches for row in rows})}
        for name,content in [('pool.json',json.dumps(state)),('pool.csv',render(items))]:
            temporary=directory/(name+'.tmp');temporary.write_text(content);temporary.chmod(0o600);temporary.replace(directory/name)
        return state

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--directory',default='/var/lib/fanout-pool');p.add_argument('--output');p.add_argument('--force',action='store_true');args=p.parse_args()
    state=collect(args.directory,args.force)
    if args.output:Path(args.output).write_text(render(state['items']))
    print(json.dumps({k:v for k,v in state.items() if k!='items'}|{'total':len(state['items'])}))
