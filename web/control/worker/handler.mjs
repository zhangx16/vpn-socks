function headers(extra={}){return {'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',...extra};}
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:headers({'Content-Type':'application/json; charset=utf-8'})});
export default {async fetch(request,env,ctx){
 const url=new URL(request.url);
 if(url.pathname.startsWith('/api/')){
  if(!request.headers.get('oai-authenticated-user-id'))return json({error:'请使用本人账号登录此私有控制页'},401);
  if(request.method==='POST'&&request.headers.get('Origin')!==url.origin)return json({error:'请求来源不匹配'},403);
  if(url.pathname==='/api/config'&&request.method==='GET'){let nodes=[];try{nodes=JSON.parse(env.NODE_PRESETS||'[]')}catch{}return json({nodes,hasToken:!!env.CF_API_TOKEN});}
  if(request.method!=='POST')return json({error:'Method not allowed'},405);
  if(Number(request.headers.get('Content-Length')||0)>16000)return json({error:'请求过大'},413);
  let input;try{const raw=await request.text();if(raw.length>16000)return json({error:'请求过大'},413);input=JSON.parse(raw);validateConfig(input);}catch(error){return json({error:error.message},400);}
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
