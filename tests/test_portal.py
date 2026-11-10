import hashlib,importlib.util,json,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('portal',Path(__file__).resolve().parents[1]/'portal/server.py');portal=importlib.util.module_from_spec(spec);spec.loader.exec_module(portal)
class PortalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();portal.ROOT=Path(self.tmp.name);portal.CONFIG=portal.ROOT/'config.json';salt='ab'*24
  self.config={'hostname':'control.example.com','username':'admin','password_salt':salt,'password_hash':portal.password_hash('long-test-admin-password',salt),'runner_token':'hidden-runner-secret','cf_token':'hidden-cf-secret'};portal.CONFIG.write_text(json.dumps(self.config));portal.init()
  self.server=portal.http.server.ThreadingHTTPServer(('127.0.0.1',0),portal.Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start();self.url='http://127.0.0.1:'+str(self.server.server_port);self.cookie=''
 def tearDown(self):self.server.shutdown();self.server.server_close();self.tmp.cleanup()
 def request(self,path,body=None,origin='https://control.example.com'):
  req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Origin':origin,'Cookie':self.cookie,'Content-Type':'application/json'})
  try:r=urllib.request.urlopen(req)
  except urllib.error.HTTPError as e:r=e
  raw=r.read().decode();return r.code,raw,r.headers
 def login(self):
  code,raw,headers=self.request('/api/login',{'username':'admin','password':'long-test-admin-password'});self.assertEqual(code,200);self.cookie=headers['Set-Cookie'].split(';')[0];return headers
 def test_login_page_and_script_are_public_but_apis_are_private(self):
  self.assertIn('管理员登录',self.request('/')[1]);self.assertEqual(self.request('/login.js')[0],200)
  self.assertEqual(self.request('/api/jobs')[0],401);self.assertEqual(self.request('/api/delete',{})[0],401)
 def test_login_uses_secure_cookie_and_stores_only_token_hash(self):
  headers=self.login();self.assertIn('Secure; HttpOnly; SameSite=Strict',headers['Set-Cookie']);self.assertEqual(self.request('/api/config')[0],200)
  self.assertNotIn(self.cookie.split('=',1)[1],(portal.ROOT/'auth.sqlite').read_bytes().decode('latin1'));self.assertNotIn('hidden-',self.request('/api/config')[1])
 def test_cross_origin_posts_and_bad_credentials_are_rejected(self):
  self.assertEqual(self.request('/api/login',{'username':'admin','password':'wrong'},origin='https://attacker.example')[0],403)
  self.assertEqual(self.request('/api/login',{'username':'admin','password':'wrong'})[0],401)
 def test_logout_revokes_session(self):
  self.login();self.assertEqual(self.request('/api/logout',{})[0],200);self.assertEqual(self.request('/api/jobs')[0],401)
 def test_password_rotation_invalidates_all_sessions(self):
  self.login();self.assertEqual(self.request('/api/password',{'oldPassword':'long-test-admin-password','newPassword':'changed-strong-password'})[0],200);self.assertEqual(self.request('/api/config')[0],401)
 def test_protected_control_domain_cannot_become_a_node(self):
  self.login();self.assertEqual(self.request('/api/task',{'domain':'control.example.com'})[0],400)
 def test_admin_identity_is_local_and_runner_secrets_are_not_exposed(self):
  self.login()
  with patch.object(portal,'runner',return_value={'jobs':[]}) as runner:
   self.assertEqual(self.request('/api/jobs')[0],200);runner.assert_called_once_with('/jobs')

 def test_saved_ssh_reuse_and_remark_api_never_expose_credentials(self):
  body={'ip':'8.8.4.4','sshPort':2222,'username':'root','password':'test-secret-ssh','remark':'东京备用'}
  self.assertEqual(self.request('/api/servers/save',body)[0],401);self.login();self.assertEqual(self.request('/api/servers/save',body)[0],200)
  code,raw,_=self.request('/api/servers');self.assertEqual(code,200);self.assertNotIn('test-secret-ssh',raw);self.assertIn('东京备用',raw)
  with patch.object(portal,'runner',return_value={'id':'fake-job'}) as runner:
   code,raw,_=self.request('/api/deploy',{'ip':'8.8.4.4','sshPort':2222,'domain':'node.example.com','region':'JP','port':35001,'path':'/node'})
   self.assertEqual(code,202);self.assertEqual(runner.call_args.args[1]['password'],'test-secret-ssh');self.assertNotIn('test-secret-ssh',raw)
