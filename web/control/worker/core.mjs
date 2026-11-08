const CF='https://api.cloudflare.com/client/v4';
const cleanRule=r=>Object.fromEntries(['action','action_parameters','expression','description','enabled','ref','logging'].filter(k=>k in r).map(k=>[k,r[k]]));
const recordBody=r=>Object.fromEntries(['type','name','content','ttl','proxied','comment','tags','settings'].filter(k=>k in r).map(k=>[k,r[k]]));
const normalize=s=>String(s).replace(/[\s()]/g,'');

export function validateConfig(input){
 const domain=String(input.domain||'').trim().toLowerCase().replace(/\.$/,'');
 if(domain.length>253||!domain.includes('.')||!domain.split('.').every(s=>/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(s)))throw Error('请输入完整、有效的节点域名');
 const ip=String(input.ip||'').trim(),oct=ip.split('.');
 if(oct.length!==4||!oct.every(s=>/^\d{1,3}$/.test(s)&&+s<=255&&String(+s)===s))throw Error('请输入有效的服务器 IPv4 地址');
 if([0,10,127].includes(+oct[0])||(+oct[0]===169&&+oct[1]===254)||(+oct[0]===100&&+oct[1]>=64&&+oct[1]<=127)||(+oct[0]===172&&+oct[1]>=16&&+oct[1]<=31)||(+oct[0]===192&&+oct[1]===168)||+oct[0]>=224)throw Error('服务器必须使用公网 IPv4 地址');
 const port=Number(input.port);if(!Number.isInteger(port)||port<1||port>65535)throw Error('回源端口范围为 1–65535');
 const path=String(input.path||'/').trim();if(!/^\/[A-Za-z0-9/_~.%-]*$/.test(path)||path.length>200)throw Error('WebSocket 路径必须以 / 开头，不包含查询参数');
 return {domain,ip,port,path,ssl:input.ssl==='strict'?'strict':'full'};
}

export function client(token,fetcher=fetch){
 return async function api(path,method='GET',body,optional=false){
  const response=await fetcher(CF+path,{method,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(12000)});
  let value;try{value=await response.json();}catch{throw Error('Cloudflare 响应无法解析（HTTP '+response.status+'）');}
  if(optional&&response.status===404)return null;
  if(!response.ok||value.success===false){const message=(value.errors||[]).map(e=>(e.code||'')+': '+e.message).join('；');throw Error('CF API '+response.status+' '+(message||'请求未成功'));}
  return value.result;
 };
}

async function zoneFor(api,domain){
 const labels=domain.split('.');
 for(let i=0;i<labels.length-1;i++){const name=labels.slice(i).join('.'),zones=await api('/zones?name='+encodeURIComponent(name));const found=zones.find(z=>z.name===name);if(found)return found;}
 throw Error('Token 无法找到域名所属的 Zone，请检查 Zone Read 权限和资源范围');
}

export function desiredRule(config,kind){
 const origin=kind==='origin';
 return {ref:'vpn_socks_'+kind+'_'+config.domain.replace(/[^a-z0-9]/g,'_'),description:'vpn-socks · '+config.domain+' · '+kind,
  expression:'http.host eq "'+config.domain+'"',enabled:true,action:origin?'route':'set_config',
  action_parameters:origin?{origin:{port:config.port}}:{ssl:config.ssl}};
}

async function ruleUpsert(api,zone,phase,existing,rule,undo){
 const base='/zones/'+zone+'/rulesets';
 if(!existing){const made=await api(base,'POST',{name:'vpn-socks '+phase,kind:'zone',phase,rules:[rule]});const item=made.rules?.find(r=>r.ref===rule.ref);if(item)undo.push(()=>api(base+'/'+made.id+'/rules/'+item.id,'DELETE'));return;}
 const rules=existing.rules||[],matched=rules.find(r=>r.ref===rule.ref)||rules.find(r=>r.action===rule.action&&normalize(r.expression)===normalize(rule.expression));
 const last=rules.at(-1);
 if(matched){
  const old=cleanRule(matched),params={...(matched.action_parameters||{}),...rule.action_parameters};
  if(rule.action==='route')params.origin={...(matched.action_parameters?.origin||{}),...rule.action_parameters.origin};
  const body={...rule,action_parameters:params};delete body.ref;if(last&&last.id!==matched.id)body.position={after:last.id};
  await api(base+'/'+existing.id+'/rules/'+matched.id,'PATCH',body);
  const index=rules.findIndex(r=>r.id===matched.id),restore={...old,position:index?{after:rules[index-1].id}:{index:1}};delete restore.ref;
  undo.push(()=>api(base+'/'+existing.id+'/rules/'+matched.id,'PATCH',restore));
 }else{
  const made=await api(base+'/'+existing.id+'/rules','POST',rule),item=made.rules?.find(r=>r.ref===rule.ref);
  if(item)undo.push(()=>api(base+'/'+existing.id+'/rules/'+item.id,'DELETE'));
 }
}

async function dnsUpsert(api,zone,records,config,undo){
 const base='/zones/'+zone+'/dns_records',addresses=records.filter(r=>['A','AAAA','CNAME'].includes(r.type));
 const first=addresses.find(r=>r.type==='A')||addresses.find(r=>r.type==='CNAME');
 const body={type:'A',name:config.domain,content:config.ip,ttl:1,proxied:true,comment:'vpn-socks managed origin'};
 if(first){await api(base+'/'+first.id,'PUT',body);undo.push(()=>api(base+'/'+first.id,'PUT',recordBody(first)));}
 else{const made=await api(base,'POST',body);undo.push(()=>api(base+'/'+made.id,'DELETE'));}
 for(const other of addresses.filter(r=>r.id!==first?.id)){await api(base+'/'+other.id,'DELETE');undo.push(()=>api(base,'POST',recordBody(other)));}
}

export async function verify(config,fetcher=fetch){
 try{
  const response=await fetcher('https://'+config.domain+config.path,{headers:{Upgrade:'websocket'},redirect:'manual',signal:AbortSignal.timeout(10000)});
  const status=response.status;
  if(response.webSocket){response.webSocket.accept();response.webSocket.close(1000,'check complete');}
  return {ok:status===101,status,message:status===101?'Cloudflare → 源站 WebSocket 握手正常':'收到 HTTP '+status+'，请检查源站或等待规则生效'};
 }catch{return {ok:false,status:0,message:'暂时无法握手；DNS、证书或规则可能仍在生效'};}
}

export async function configure(input,emit,fetcher=fetch){
 const config=validateConfig(input),token=String(input.token||'').trim();
 if(!token)throw Error('后台尚未配置 Token，请在凭据选项中填写');
 const api=client(token,fetcher),undo=[];
 const event=(step,state,message,detail)=>emit({step,state,message,...(detail?{detail}:{})});
 event('permission','running','检查 Token 与 Zone 访问权限');
 const verified=await api('/user/tokens/verify');if(verified.status!=='active')throw Error('Token 尚未启用');
 const zone=await zoneFor(api,config.domain),base='/zones/'+zone.id;
 const [dns,origin,settings]=await Promise.all([api(base+'/dns_records?name='+encodeURIComponent(config.domain)+'&per_page=100'),api(base+'/rulesets/phases/http_request_origin/entrypoint','GET',undefined,true),api(base+'/rulesets/phases/http_config_settings/entrypoint','GET',undefined,true)]);
 event('permission','done','Token 与配置读取接口可访问',zone.name);
 const plan={domain:config.domain,ip:config.ip,port:config.port,ssl:config.ssl,path:config.path,zone:zone.name};
 if(input.dryRun){
  event('dns','done','计划：橙云 A 记录 → '+config.ip);event('origin','done','计划：回源端口 → '+config.port);event('tls','done','计划：仅该主机名使用 '+config.ssl);
  const check=await verify(config,fetcher);event('verify',check.ok?'done':'pending',check.message);event('complete','done','配置检查结束；未修改 Cloudflare',plan);return;
 }
 try{
  event('origin','running','写入域名回源端口规则');await ruleUpsert(api,zone.id,'http_request_origin',origin,desiredRule(config,'origin'),undo);event('origin','done','回源端口已设置为 '+config.port);
  event('tls','running','设置域名级 TLS 模式');await ruleUpsert(api,zone.id,'http_config_settings',settings,desiredRule(config,'tls'),undo);event('tls','done','TLS '+config.ssl+'，仅作用于该主机名');
  event('dns','running','同步橙云 A 记录');await dnsUpsert(api,zone.id,dns,config,undo);event('dns','done',config.domain+' → '+config.ip+' · 橙云开启');
 }catch(error){
  event('rollback','running','配置写入未完成，恢复本次已修改的记录');let failures=0;for(const restore of undo.reverse()){try{await restore();}catch{failures++;}}
  event('rollback',failures?'error':'done',failures?'部分恢复未完成，请查看 Cloudflare 配置':'本次已完成的修改已恢复');throw error;
 }
 event('verify','running','通过域名执行 WebSocket 验收');let check=await verify(config,fetcher);
 if(!check.ok){await new Promise(resolve=>setTimeout(resolve,1500));check=await verify(config,fetcher);}
 event('verify',check.ok?'done':'pending',check.message);event('complete',check.ok?'done':'pending',check.ok?'自动配置完成，WebSocket 验收通过':'配置已保存，链路验收待生效',{...plan,verified:check.ok});
}
