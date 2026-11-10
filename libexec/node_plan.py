"""Pure inbound planning shared by provisioning and isolation tests."""
def plan(request,inbounds,registry,available):
 result=dict(request);public=request['port'];result['public_port']=public
 same_domain=[value for key,value in registry.items() if key.split('|')[0]==request['domain']]
 if any(row['public_port']!=public for row in same_domain):raise ValueError('同一域名的节点必须共用同一公网端口')
 recorded=registry.get(request['domain']+'|'+request['path'])
 legacy=registry.get(request['domain'])
 if not recorded and legacy and legacy['path']==request['path']:recorded=legacy
 matches=[row for row in inbounds if row.get('tls',{}).get('server_name')==request['domain'] and row.get('path')==request['path']]
 if len(matches)>1:raise ValueError('域名和路径对应多个入站，请人工核对')
 if recorded:
  inbound=next((row for row in inbounds if row['port']==recorded['port']),None)
  if inbound and inbound not in matches:raise ValueError('已记录的入站身份发生变化，拒绝覆盖')
  result['port']=recorded['port'];return result,inbound
 if matches:result['port']=matches[0]['port'];return result,matches[0]
 occupied=next((row for row in inbounds if row['port']==public),None)
 if not occupied:return result,None
 for port in range(20000,22000):
  if any(row['port']==port for row in inbounds) or not available(port):continue
  result['port']=port;return result,None
 raise ValueError('没有可用的内部节点端口')
