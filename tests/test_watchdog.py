import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
spec=importlib.util.spec_from_file_location('node_watchdog',Path(__file__).resolve().parents[1]/'runner/watchdog.py');watch=importlib.util.module_from_spec(spec);spec.loader.exec_module(watch)
class WatchdogTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=watch.runner.ROOT;watch.runner.ROOT=Path(self.tmp.name);watch.runner.init();watch.init();self.node={'id':'a'*32}
  with watch.runner.db() as c:c.execute('INSERT INTO nodes VALUES(?,?,?,?,?,?)',(self.node['id'],'owner','{}',json.dumps({'link':'vless://example','exit_ip':'old'}),'active',1))
 def tearDown(self):watch.runner.ROOT=self.old;self.tmp.cleanup()
 def test_two_failures_and_cooldown_are_required(self):
  self.assertFalse(watch.should_repair({'failures':0,'repaired':0},1000));self.assertTrue(watch.should_repair({'failures':1,'repaired':0},1000));self.assertFalse(watch.should_repair({'failures':5,'repaired':900},1000))
 def test_maintenance_does_not_increment_failure_counter(self):
  watch.record(self.node,'maintenance',{'reason':'task running'});self.assertEqual(watch.previous(self.node['id'])['failures'],0)
 def test_verified_recovery_updates_live_exit_and_resets_failures(self):
  watch.record(self.node,'unreachable',{'reason':'offline'});watch.record(self.node,'healthy',{'exit_ip':'8.8.4.4','country':'JP','standby_ips':['8.8.8.8']})
  self.assertEqual(watch.previous(self.node['id'])['failures'],0)
  with watch.runner.db() as c:node=json.loads(c.execute('SELECT result FROM nodes').fetchone()['result'])
  self.assertEqual(node['exit_ip'],'8.8.4.4');self.assertEqual(node['standby_ips'],['8.8.8.8'])
 def test_websocket_failure_is_never_healthy_even_if_remote_probe_passes(self):
  config={'ip':'8.8.4.4','sshPort':22,'username':'root','domain':'node.example.com','path':'/node'};node={**self.node,'config':config};client=Mock();client.open_sftp.return_value=__import__('unittest.mock',fromlist=['MagicMock']).MagicMock()
  responses=[(0,''),(0,'wrong-checksum'),(0,json.dumps({'nodes':[{'id':node['id'],'state':'healthy','exit_ip':'8.8.4.4','country':'JP'}],'actions':[]}))]
  with patch.object(watch,'ensure_pin'),patch.object(watch,'websocket',return_value={'ok':False,'status':521}),patch.object(watch,'busy',return_value=False),patch.object(watch.vault,'resolve',return_value={'password':'test-password','username':'root'}),patch.object(watch.runner,'connect',return_value=client),patch.object(watch.runner,'ssh_run',side_effect=responses):watch.check_group([node])
  with watch.runner.db() as c:row=c.execute('SELECT state FROM node_health WHERE id=?',(node['id'],)).fetchone()
  self.assertEqual(row['state'],'cf_unavailable')

 def test_unknown_host_key_prevents_automatic_authentication(self):
  with self.assertRaises(ValueError):watch.ensure_pin({'ip':'8.8.4.4','sshPort':22})
 def test_repair_and_deployment_cannot_hold_same_server_lock(self):
  config={'ip':'8.8.4.4','sshPort':22};lease=watch.runner.server_lock(config)
  try:self.assertIsNone(watch.runner.server_lock(config,blocking=False))
  finally:lease.close()
  other=watch.runner.server_lock(config,blocking=False);self.assertIsNotNone(other);other.close()
