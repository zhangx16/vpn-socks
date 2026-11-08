function headers(extra={}){return {'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',...extra};}
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:headers({'Content-Type':'application/json; charset=utf-8'})});
async function runner(env,path,actor,method='GET',body){
 if(!env.RUNNER_URL||!env.RUNNER_TOKEN)throw Error('SSH 执行器尚未配置');
 const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(actor));
 const actorKey=[...new Uint8Array(digest)].map(n=>n.toString(16).padStart(2,'0')).join('');
 const response=await fetch(env.RUNNER_URL+path,{method,headers:{Authorization:'Bearer '+env.RUNNER_TOKEN,'X-Actor':actorKey,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(35000)});
 let data;try{data=await response.json()}catch{throw Error('执行器响应异常，请稍后重试')}
 if(!response.ok)throw Error(data.error||'执行器暂时不可用');return data;
}
export default {async fetch(request,env,ctx){
 const url=new URL(request.url);
 if(url.pathname.startsWith('/api/')){
  if(!request.headers.get('oai-authenticated-user-id'))return json({error:'请使用本人账号登录此私有控制页'},401);
  if(request.method==='POST'&&request.headers.get('Origin')!==url.origin)return json({error:'请求来源不匹配'},403);
  const actor=request.headers.get('oai-authenticated-user-id');
  if(url.pathname==='/api/config'&&request.method==='GET'){let nodes=[];try{nodes=JSON.parse(env.NODE_PRESETS||'[]')}catch{}return json({nodes,hasToken:!!env.CF_API_TOKEN,runnerReady:!!env.RUNNER_URL&&!!env.RUNNER_TOKEN});}
  if(request.method==='GET'&&['/api/regions','/api/jobs'].includes(url.pathname)){
   try{
    const id=url.searchParams.get('id');if(id&&!/^[a-f0-9]{32}$/.test(id))return json({error:'任务 ID 无效'},400);
    return json(await runner(env,url.pathname==='/api/regions'?'/regions':id?'/jobs/'+id:'/jobs',actor));
   }catch(error){return json({error:error.message},503)}
  }
  if(request.method!=='POST')return json({error:'Method not allowed'},405);
  if(Number(request.headers.get('Content-Length')||0)>65536)return json({error:'请求过大'},413);
  let input;try{const raw=await request.text();if(raw.length>65536)return json({error:'请求过大'},413);input=JSON.parse(raw);validateConfig(input);}catch(error){return json({error:error.message},400);}
  let protectedHosts=[url.hostname];try{protectedHosts.push(...JSON.parse(env.CONTROL_HOSTS||'[]'))}catch{}
  if(env.RUNNER_URL)protectedHosts.push(new URL(env.RUNNER_URL).hostname);
  if((url.pathname==='/api/deploy'||url.pathname==='/api/task'&&!input.dryRun)&&protectedHosts.includes(validateConfig(input).domain))return json({error:'不能覆盖控制台或执行器域名'},400);
  if(url.pathname==='/api/deploy'){
   try{
    const config=validateConfig(input);
    if(config.domain===url.hostname||config.domain===new URL(env.RUNNER_URL).hostname)return json({error:'不能覆盖控制台或执行器域名'},400);
    if(!/^[A-Z]{2}$/.test(input.region||''))return json({error:'请选择出口库中的国家'},400);
    const token=input.token||env.CF_API_TOKEN||'';if(!token)return json({error:'缺少 CF Token'},400);
    await zoneFor(client(token),config.domain);
    const result=await runner(env,'/jobs',actor,'POST',{...config,region:input.region,sshPort:input.sshPort,username:input.username||'root',password:input.password||'',privateKey:input.privateKey||'',cfToken:token});
    return json(result,202);
   }catch(error){return json({error:error.message},400)}
   finally{input.password='';input.privateKey='';input.token=''}
  }
  if(url.pathname==='/api/verify')return json(await verify(validateConfig(input)));
  if(url.pathname==='/api/task'){
   input.token=input.token||env.CF_API_TOKEN||'';const secret=input.token,encoder=new TextEncoder();
   const stream=new ReadableStream({start(controller){const emit=e=>{try{let value=JSON.stringify(e);if(secret)value=value.split(secret).join('[redacted]');controller.enqueue(encoder.encode(value+'\n'));}catch{}};
    const task=configure(input,emit).catch(error=>emit({step:'error',state:'error',message:error.message})).finally(()=>{input.token='';try{controller.close()}catch{}});ctx.waitUntil(task);
   }});return new Response(stream,{headers:headers({'Content-Type':'application/x-ndjson; charset=utf-8'})});
  }
  return json({error:'Not found'},404);
 }
 if(url.pathname!=='/')return new Response('Not found',{status:404});
 const nonce=crypto.randomUUID().replaceAll('-','');
 return new Response(page.replace('__NONCE__',nonce),{headers:headers({'Content-Type':'text/html; charset=utf-8','Content-Security-Policy':"default-src 'self'; script-src 'nonce-"+nonce+"'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'"})});
}};
