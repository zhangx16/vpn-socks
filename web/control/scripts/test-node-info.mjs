import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm';
const page=fs.readFileSync(new URL('../worker/page.html',import.meta.url),'utf8');
test('node details export explicitly excludes SSH credentials and CF tokens',()=>{
 const source=page.slice(page.indexOf('function nodeDetails('),page.indexOf('function downloadNode('));const details=vm.runInNewContext(source+';nodeDetails');
 const result=details({config:{domain:'node.example.com',ip:'8.8.4.4',port:35001,path:'/node',uuid:'node-uuid',region:'JP',password:'hidden-ssh-password',privateKey:'hidden-private-key',cfToken:'hidden-cf-token'},result:{link:'vless://node-uuid@node.example.com:443',exit_ip:'8.8.8.8'},status:'active',updated:1});
 assert.equal(result.uuid,'node-uuid');assert.ok(!JSON.stringify(result).includes('hidden-'));assert.equal(result.clientPort,443);
});
