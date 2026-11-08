import test from 'node:test';
import assert from 'node:assert/strict';
import {configure,validateConfig,desiredRule,verify} from '../worker/core.mjs';
const config={domain:'node.example.com',ip:'8.8.4.4',port:35001,path:'/ws',ssl:'full',token:'not-a-real-token'};
function fake({failTLS=false}={}){
 const calls=[];
 const fetcher=async(url,options={})=>{
  const method=options.method||'GET',body=options.body?JSON.parse(options.body):undefined;
  calls.push({url,method,body});
  if(!url.includes('api.cloudflare.com'))return {status:101,webSocket:{accept(){},close(){}}};
  const path=url.replace('https://api.cloudflare.com/client/v4','');let result;
  if(path==='/user/tokens/verify')result={status:'active'};
  else if(path==='/zones?name=node.example.com')result=[];
  else if(path==='/zones?name=example.com')result=[{id:'zone',name:'example.com'}];
  else if(path.includes('/dns_records?'))result=[{id:'dns',type:'A',name:config.domain,content:'1.1.1.1',ttl:1,proxied:true}];
  else if(path.includes('/phases/http_request_origin/'))result={id:'origin',rules:[{id:'manual',ref:'manual-ref',action:'route',expression:'(http.host eq "node.example.com")',enabled:true,action_parameters:{origin:{port:1000},host_header:'keep.example.com'}}]};
  else if(path.includes('/phases/http_config_settings/'))return Response.json({success:false},{status:404});
  else if(path==='/zones/zone/rulesets'&&method==='POST'){
   if(failTLS)return Response.json({success:false,errors:[{code:10000,message:'not authorized'}]},{status:403});
   result={id:'settings',rules:[{id:'tls-rule',...body.rules[0]}]};
  }else if(path.includes('/dns_records/'))result={id:'dns',...body};
  else if(path.includes('/rules/manual'))result={id:'origin',rules:[{id:'manual',...body}]};
  else throw Error('unexpected mocked request '+method+' '+path);
  return Response.json({success:true,result});
 };
 return {fetcher,calls};
}
test('reject invalid ports, private origin IP and unsafe WS paths',()=>{
 assert.throws(()=>validateConfig({...config,port:0}));assert.throws(()=>validateConfig({...config,ip:'10.0.0.1'}));assert.throws(()=>validateConfig({...config,path:'//evil.example?x=1'}));
 assert.equal(validateConfig({...config,domain:'Node.Example.com.'}).domain,'node.example.com');
});
test('rules scope TLS and origin port to exactly one hostname',()=>{
 const rule=desiredRule(config,'origin');assert.equal(rule.expression,'http.host eq "node.example.com"');assert.equal(rule.action_parameters.origin.port,35001);
 assert.deepEqual(desiredRule(config,'tls').action_parameters,{ssl:'full'});
});
test('dry run performs no mutations and exposes no token',async()=>{
 const {fetcher,calls}=fake(),events=[];await configure({...config,dryRun:true},e=>events.push(e),fetcher);
 assert.ok(calls.every(c=>c.method==='GET'));assert.equal(events.at(-1).step,'complete');assert.ok(!JSON.stringify(events).includes(config.token));
});
test('adopts existing exact-host rule and preserves unrelated parameters',async()=>{
 const {fetcher,calls}=fake(),events=[];await configure(config,e=>events.push(e),fetcher);
 const update=calls.find(c=>c.method==='PATCH');assert.equal(update.body.action_parameters.host_header,'keep.example.com');assert.equal(update.body.action_parameters.origin.port,35001);
 assert.equal(update.body.ref,undefined);
 assert.equal(events.at(-1).detail.verified,true);
});
test('write failure restores the rule already changed and does not touch DNS',async()=>{
 const {fetcher,calls}=fake({failTLS:true}),events=[];await assert.rejects(configure(config,e=>events.push(e),fetcher),/403/);
 const patches=calls.filter(c=>c.method==='PATCH');assert.equal(patches.length,2);assert.equal(patches[1].body.action_parameters.origin.port,1000);
 assert.ok(!calls.some(c=>c.method==='PUT'));assert.ok(events.some(e=>e.step==='rollback'&&e.state==='done'));
});
test('HTTP 521 is reported as pending rather than a successful deployment',async()=>{
 const result=await verify(config,async()=>({status:521}));assert.equal(result.ok,false);assert.equal(result.status,521);
});
