import test from 'node:test';
import assert from 'node:assert/strict';
import app from '../dist/server/index.js';
const env={CF_API_TOKEN:'fake-cf-token',RUNNER_URL:'https://runner.example.com',RUNNER_TOKEN:'fake-runner-token',NODE_PRESETS:'[]',CONTROL_HOSTS:'["alias.example"]'};
const config={domain:'node.example.com',ip:'8.8.4.4',port:35001,path:'/ws',region:'RO',sshPort:22,username:'root',password:'fake-password'};
const headers={'oai-authenticated-user-id':'opaque:user|subject',Origin:'https://console.example','Content-Type':'application/json'};
const ctx={waitUntil(){}};
test('SSH and region endpoints reject missing identity',async()=>{
 for(const path of ['/api/regions','/api/jobs']){const r=await app.fetch(new Request('https://console.example'+path),env,ctx);assert.equal(r.status,401)}
});
test('region choices are forwarded from the live catalog',async()=>{
 const original=globalThis.fetch;try{
  globalThis.fetch=async(url,options)=>{assert.equal(url,'https://runner.example.com/regions');assert.match(options.headers['X-Actor'],/^[a-f0-9]{64}$/);return Response.json({regions:[{code:'RO',count:1},{code:'CA',count:2}]})};
  const r=await app.fetch(new Request('https://console.example/api/regions',{headers}),env,ctx);assert.equal((await r.json()).regions.length,2);
 }finally{globalThis.fetch=original}
});
test('deploy queues credentials but returns only a task ID',async()=>{
 const original=globalThis.fetch;try{
  globalThis.fetch=async(url,options)=>{
   if(url.startsWith('https://api.cloudflare.com'))return Response.json({success:true,result:url.includes('name=node.example.com')?[]:[{id:'zone',name:'example.com'}]});
   const body=JSON.parse(options.body);assert.equal(body.password,'fake-password');assert.equal(body.region,'RO');assert.equal(body.cfToken,'fake-cf-token');return Response.json({id:'a'.repeat(32),status:'queued'},{status:202});
  };
  const r=await app.fetch(new Request('https://console.example/api/deploy',{method:'POST',headers,body:JSON.stringify(config)}),env,ctx);
  assert.equal(r.status,202);const text=await r.text();assert.ok(!text.includes('fake-password'));assert.ok(!text.includes('fake-cf-token'));
 }finally{globalThis.fetch=original}
});
test('control and runner domains cannot be overwritten by deployments',async()=>{
 for(const domain of ['console.example','runner.example.com','alias.example']){
  const r=await app.fetch(new Request('https://console.example/api/deploy',{method:'POST',headers,body:JSON.stringify({...config,domain})}),env,ctx);assert.equal(r.status,400);
 }
});
