import https from 'node:https';
import {randomBytes} from 'node:crypto';
import {configure} from '../web/control/worker/core.mjs';
let text='';for await(const chunk of process.stdin)text+=chunk;
const config=JSON.parse(text);
const fetcher=(url,options={})=>url.startsWith('https://api.cloudflare.com')?fetch(url,options):new Promise((resolve,reject)=>{
 const request=https.request(url,{headers:{Upgrade:'websocket',Connection:'Upgrade','Sec-WebSocket-Version':'13','Sec-WebSocket-Key':randomBytes(16).toString('base64')},timeout:10000});
 request.on('upgrade',(response,socket)=>resolve({status:response.statusCode,webSocket:{accept(){},close(){socket.destroy()}}}));
 request.on('response',response=>{response.resume();resolve({status:response.statusCode})});request.on('timeout',()=>request.destroy(Error('timeout')));request.on('error',reject);request.end();
});
try{await configure(config,()=>{},fetcher);console.log('Cloudflare configuration applied');}
catch(error){console.error(String(error.message).replaceAll(config.token,'[redacted]'));process.exitCode=1;}
