import hashlib,importlib.util,json,sqlite3,tempfile,threading,unittest,urllib.request,urllib.error,subprocess,os
from pathlib import Path
from unittest.mock import Mock,MagicMock,patch

spec=importlib.util.spec_from_file_location('vpn_runner',Path(__file__).resolve().parents[1]/'runner'/'service.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

class RunnerTests(unittest.TestCase):
 def setUp(self):
  def fetch_pool(directory,force=False):
   response=runner.subprocess.run(['mock-official-fetch'])
   if response.returncode:raise ValueError('offline')
   import csv,io
   text=response.stdout.decode();items={}
   for index,r in enumerate(csv.DictReader(io.StringIO(text[text.index('#HostName,')+1:]))):
    if r.get('CountryShort'):items[str(index)]={'row':r}
   return {'updated_at':runner.time.time(),'items':items,'sources':[]}
  self.collect_patch=patch.object(runner,'collect_pool',side_effect=fetch_pool);self.collect_patch.start()
  self.temporary=tempfile.TemporaryDirectory();runner.ROOT=Path(self.temporary.name);runner.CONFIG=runner.ROOT/'config.json';runner.CATALOG={}
  runner.CONFIG.write_text(json.dumps({'auth_sha256':hashlib.sha256(b'test-runner-secret').hexdigest(),'hostname':'runner.example.com'}));runner.init()
  self.server=runner.http.server.ThreadingHTTPServer(('127.0.0.1',0),runner.Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.url='http://127.0.0.1:'+str(self.server.server_port)
  self.payload={'ip':'8.8.4.4','domain':'node.example.com','port':35001,'path':'/ws','region':'RO','sshPort':22,'username':'root','password':'not-a-real-ssh-password','cfToken':'not-a-real-cf-token'}
 def tearDown(self):self.collect_patch.stop();self.server.shutdown();self.server.server_close();self.temporary.cleanup()
 def request(self,path,body=None,token='test-runner-secret',actor='owner'):
  req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+token,'X-Actor':actor,'Content-Type':'application/json'})
  try:
   with urllib.request.urlopen(req,timeout=5) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def test_authentication_is_required(self):self.assertEqual(self.request('/health',token='wrong')[0],401)
 def test_deployment_error_returns_the_actual_cause_and_redacts_credentials(self):
  output='{"step":"install","state":"error","message":"安装失败"}\nERROR: openvpn: failed to rename\npassword=secret-password token=secret-token\n'
  message=runner.deployment_failure(output,{'password':'secret-password','cfToken':'secret-token'})
  self.assertIn('failed to rename',message);self.assertNotIn('secret-password',message);self.assertNotIn('secret-token',message)
 def test_preflight_rejects_an_operator_prohibition_before_package_install(self):
  directory=Path(self.temporary.name)/'bin';directory.mkdir()
  wrapper=directory/'openvpn';wrapper.write_text('#!/bin/sh\necho "当前节点严禁运行 OpenVPN"\nexit 1\n');wrapper.chmod(0o755)
  script=Path(__file__).resolve().parents[1]/'scripts'/'preflight.sh'
  result=subprocess.run(['sh',str(script)],env={**os.environ,'PATH':str(directory)+':'+os.environ['PATH']},capture_output=True,text=True)
  self.assertEqual(result.returncode,42);self.assertIn('服务器预置策略明确禁止 OpenVPN',result.stderr)
 def test_error_does_not_report_success_for_missing_node_result(self):
  message=runner.deployment_failure('{"step":"install","state":"error","message":"依赖安装失败，退出码 1"}',{})
  self.assertIn('依赖安装失败',message)
 def test_catalog_includes_self_hosted_and_datacenter_candidates(self):
  sample=b'*vpn_servers\n#HostName,IP,CountryShort,CountryLong\nvpn1,8.8.4.4,RO,Romania\npublic-vpn-1,8.8.8.8,JP,Japan\nvpn-owned,219.100.37.1,JP,Japan\n*\n'
  with patch.object(runner.subprocess,'run',return_value=Mock(returncode=0,stdout=sample)):
   catalog=runner.regions()
  self.assertEqual(catalog['regions'],[{'code':'JP','name':'Japan','count':2},{'code':'RO','name':'Romania','count':1}]);self.assertEqual(catalog['scope'],'all')
 def test_force_refresh_bypasses_a_fresh_cache(self):
  original={'scope':'all','mode':'official-merged','updated_at':runner.time.time(),'stale':False,'regions':[{'code':'JP','count':1}]};runner.CATALOG=original
  sample=b'*vpn_servers\n#HostName,IP,CountryShort,CountryLong\nvpn2,8.8.4.4,CA,Canada\n*\n'
  with patch.object(runner.subprocess,'run',return_value=Mock(returncode=0,stdout=sample)) as fetch:
   self.assertEqual(runner.regions()['regions'][0]['code'],'JP');fetch.assert_not_called()
   updated=runner.regions(force=True);self.assertEqual(updated['regions'][0]['code'],'CA');fetch.assert_called_once()
 def test_previous_residential_cache_is_not_reused(self):
  runner.CATALOG={'updated_at':runner.time.time(),'regions':[{'code':'RO','count':1}]}
  sample=b'*vpn_servers\n#HostName,IP,CountryShort,CountryLong\npublic-vpn-1,219.100.37.1,JP,Japan\n*\n'
  with patch.object(runner.subprocess,'run',return_value=Mock(returncode=0,stdout=sample)) as fetch:
   catalog=runner.regions()
  fetch.assert_called_once();self.assertEqual(catalog['scope'],'all');self.assertEqual(catalog['regions'][0]['code'],'JP')
 def test_failed_manual_refresh_preserves_the_previous_catalog(self):
  original={'scope':'all','updated_at':runner.time.time(),'stale':False,'regions':[{'code':'JP','count':1}]};runner.CATALOG=original
  with patch.object(runner.subprocess,'run',return_value=Mock(returncode=28,stdout=b'')):
   with self.assertRaises(ValueError):runner.regions(force=True)
  self.assertEqual(runner.CATALOG,original)
 def test_manual_refresh_endpoint_requires_authentication(self):
  self.assertEqual(self.request('/regions/refresh',{},token='wrong')[0],401)
  with patch.object(runner,'regions',return_value={'updated_at':123,'regions':[{'code':'RO','count':1}]}) as fetch:
   status,catalog=self.request('/regions/refresh',{});self.assertEqual(status,200);fetch.assert_called_once_with(force=True)
 def test_private_and_control_hosts_are_rejected(self):
  self.assertEqual(self.request('/jobs',{**self.payload,'ip':'127.0.0.1'})[0],400)
  self.assertEqual(self.request('/jobs',{**self.payload,'domain':'runner.example.com'})[0],400)
 def test_single_candidate_country_is_accepted_and_secrets_are_not_persisted(self):
  with patch.object(runner,'regions',return_value={'regions':[{'code':'RO','count':1}]}),patch.object(runner.EXECUTOR,'submit'):
   status,data=self.request('/jobs',self.payload);self.assertEqual(status,202)
  status,job=self.request('/jobs/'+data['id']);self.assertEqual(status,200)
  self.assertNotIn('password',job['config']);self.assertNotIn('cfToken',job['config'])
  self.assertNotIn(self.payload['password'],(runner.ROOT/'jobs.sqlite').read_bytes().decode('latin1'))
 def test_jobs_are_scoped_to_the_submitting_actor(self):
  with patch.object(runner,'regions',return_value={'regions':[{'code':'RO','count':1}]}),patch.object(runner.EXECUTOR,'submit'):
   _,data=self.request('/jobs',self.payload)
  self.assertEqual(self.request('/jobs/'+data['id'],actor='other-owner')[0],404)
 def test_country_missing_from_live_catalog_is_rejected(self):
  with patch.object(runner,'regions',return_value={'regions':[{'code':'JP','count':1}]}):self.assertEqual(self.request('/jobs',self.payload)[0],400)
 def test_restart_marks_inflight_jobs_interrupted(self):
  with patch.object(runner,'regions',return_value={'regions':[{'code':'RO','count':1}]}),patch.object(runner.EXECUTOR,'submit'):
   _,data=self.request('/jobs',self.payload)
  runner.init();_,job=self.request('/jobs/'+data['id']);self.assertEqual(job['status'],'interrupted')

 def test_delete_requires_owned_record_and_exact_confirmation(self):
  data={**self.payload,'_actor':'owner'};node={'link':'vless://uuid-one@node.example.com:443','exit_ip':'1.2.3.4'}
  identity=runner.register_node(data,node,'owner')
  body={'nodeId':identity,'confirmDomain':'wrong.example.com','password':'secret','cfToken':'secret'}
  self.assertEqual(self.request('/delete',body)[0],400)
  self.assertEqual(self.request('/delete',{**body,'confirmDomain':self.payload['domain']},actor='stranger')[0],400)
  with patch.object(runner.EXECUTOR,'submit') as submit:
   code,result=self.request('/delete',{**body,'confirmDomain':self.payload['domain']})
   self.assertEqual(code,202);passed=submit.call_args.args[2];self.assertEqual(passed['ip'],self.payload['ip']);self.assertEqual(passed['uuid'],'uuid-one')
  self.assertNotIn('secret',(runner.ROOT/'jobs.sqlite').read_bytes().decode('latin1'))
 def test_multiple_nodes_same_server_domain_port_keep_separate_identity(self):
  first={**self.payload,'path':'/one'};second={**self.payload,'path':'/two'}
  runner.register_node(first,{'link':'vless://one@node.example.com:443','listen_port':20000},'owner')
  runner.register_node(second,{'link':'vless://two@node.example.com:443','listen_port':20001},'owner')
  code,data=self.request('/nodes');self.assertEqual(code,200);self.assertEqual(len(data['nodes']),2)
  self.assertEqual({n['config']['listenPort'] for n in data['nodes']},{20000,20001});self.assertEqual(len(self.request('/nodes',actor='stranger')[1]['nodes']),0)
 def test_shared_domain_deletion_preserves_cloudflare(self):
  job='a'*32;data={**self.payload,'_actor':'owner','_operation':'delete','nodeId':'b'*32,'uuid':'one'}
  with runner.db() as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',(job,'owner','queued',runner.time.time(),json.dumps({}),None,None))
  client=MagicMock();client.open_sftp.return_value.__enter__.return_value.file.return_value.__enter__.return_value=Mock()
  with patch.object(runner,'connect',return_value=client),patch.object(runner,'ssh_run',side_effect=[(0,''),(0,json.dumps({'node_deleted':True,'remaining_domain_nodes':1}))]),patch.object(runner.subprocess,'run') as cf:
   runner.node_worker(job,data);cf.assert_not_called()
  _,result=self.request('/jobs/'+job);self.assertEqual(result['status'],'succeeded')

if __name__=='__main__':unittest.main()
