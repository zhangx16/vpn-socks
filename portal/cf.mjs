import https from 'node:https';
import {randomBytes} from 'node:crypto';
import {configure,verify,validateConfig} from '../web/control/worker/core.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const input=JSON.parse(raw),events=[];
const fetcher=(url,options={})=>url.startsWith('https://api.cloudflare.com')?fetch(url,options):new Promise((resolve,reject)=>{
 const request=https.request(url,{headers:{Upgrade:'websocket',Connection:'Upgrade','Sec-WebSocket-Version':'13','Sec-WebSocket-Key':randomBytes(16).toString('base64')},timeout:10000});
 request.on('upgrade',(r,s)=>resolve({status:r.statusCode,webSocket:{accept(){},close(){s.destroy()}}}));request.on('response',r=>{r.resume();resolve({status:r.statusCode})});request.on('timeout',()=>request.destroy(Error('timeout')));request.on('error',reject);request.end();
});
try{if(input.operation==='verify')console.log(JSON.stringify(await verify(validateConfig(input),fetcher)));else{await configure(input,e=>events.push(e),fetcher);console.log(JSON.stringify(events))}}catch(e){console.error(String(e.message).split(input.token||'\0').join('[redacted]'));process.exitCode=1}
