import importlib.util,json,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('ssh_vault',Path(__file__).resolve().parents[1]/'portal/vault.py');vault=importlib.util.module_from_spec(spec);spec.loader.exec_module(vault)
class VaultTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.data={'ip':'8.8.4.4','sshPort':2222,'username':'root','password':'example-ssh-password','privateKey':'','remark':'东京备用'}
 def tearDown(self):self.tmp.cleanup()
 def test_credentials_encrypted_and_metadata_contains_no_secret(self):
  identity=vault.save(self.root,self.data);rows=vault.list_servers(self.root);self.assertEqual(rows[0]['remark'],'东京备用');self.assertTrue(rows[0]['hasCredentials']);self.assertNotIn('password',json.dumps(rows));self.assertNotIn(b'example-ssh-password',(self.root/'ssh-vault.sqlite').read_bytes());self.assertEqual(vault.load(self.root,identity)['password'],self.data['password']);self.assertEqual((self.root/'ssh-vault.key').stat().st_mode&0o777,0o600)
 def test_reuse_is_scoped_to_exact_server_and_port(self):
  identity=vault.save(self.root,self.data);result=vault.resolve(self.root,{'ip':'8.8.4.4','sshPort':2222});self.assertEqual(result['password'],self.data['password'])
  with self.assertRaises(ValueError):vault.resolve(self.root,{'serverId':identity,'ip':'8.8.8.8','sshPort':2222})
 def test_update_remark_keeps_secret_and_delete_revokes_saved_credential(self):
  identity=vault.save(self.root,self.data);vault.save(self.root,{**self.data,'password':'','remark':'新的备注'});self.assertEqual(vault.load(self.root,identity)['password'],self.data['password']);self.assertEqual(vault.list_servers(self.root)[0]['remark'],'新的备注');vault.delete(self.root,identity)
  with self.assertRaises(ValueError):vault.load(self.root,identity)
 def test_note_can_exist_without_saved_credentials(self):
  vault.save(self.root,{**self.data,'password':''});self.assertFalse(vault.list_servers(self.root)[0]['hasCredentials']);self.assertNotIn('password',vault.resolve(self.root,{'ip':self.data['ip'],'sshPort':2222}))
