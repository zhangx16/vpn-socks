import hashlib,importlib.util,json,sqlite3,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import Mock,patch

spec=importlib.util.spec_from_file_location('vpn_runner',Path(__file__).resolve().parents[1]/'runner'/'service.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

class RunnerTests(unittest.TestCase):
 def setUp(self):
  self.temporary=tempfile.TemporaryDirectory();runner.ROOT=Path(self.temporary.name);runner.CONFIG=runner.ROOT/'config.json';runner.CATALOG={}
  runner.CONFIG.write_text(json.dumps({'auth_sha256':hashlib.sha256(b'test-runner-secret').hexdigest(),'hostname':'runner.example.com'}));runner.init()
  self.server=runner.http.server.ThreadingHTTPServer(('127.0.0.1',0),runner.Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.url='http://127.0.0.1:'+str(self.server.server_port)
  self.payload={'ip':'8.8.4.4','domain':'node.example.com','port':35001,'path':'/ws','region':'RO','sshPort':22,'username':'root','password':'not-a-real-ssh-password','cfToken':'not-a-real-cf-token'}
 def tearDown(self):self.server.shutdown();self.server.server_close();self.temporary.cleanup()
 def request(self,path,body=None,token='test-runner-secret',actor='owner'):
  req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+token,'X-Actor':actor,'Content-Type':'application/json'})
  try:
   with urllib.request.urlopen(req,timeout=5) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def test_authentication_is_required(self):self.assertEqual(self.request('/health',token='wrong')[0],401)
 def test_catalog_includes_self_hosted_and_datacenter_candidates(self):
  sample=b'*vpn_servers\n#HostName,IP,CountryShort,CountryLong\nvpn1,8.8.4.4,RO,Romania\npublic-vpn-1,8.8.8.8,JP,Japan\nvpn-owned,219.100.37.1,JP,Japan\n*\n'
  with patch.object(runner.subprocess,'run',return_value=Mock(returncode=0,stdout=sample)):
   catalog=runner.regions()
  self.assertEqual(catalog['regions'],[{'code':'JP','name':'Japan','count':2},{'code':'RO','name':'Romania','count':1}]);self.assertEqual(catalog['scope'],'all')
 def test_force_refresh_bypasses_a_fresh_cache(self):
  original={'scope':'all','updated_at':runner.time.time(),'stale':False,'regions':[{'code':'JP','count':1}]};runner.CATALOG=original
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

if __name__=='__main__':unittest.main()
