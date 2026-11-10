import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
spec=importlib.util.spec_from_file_location('node_action',Path(__file__).resolve().parents[1]/'scripts/node-action.py');action=importlib.util.module_from_spec(spec);spec.loader.exec_module(action)
class NodeActionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.native=self.root/'var/lib/fanout/native.json';self.native.parent.mkdir(parents=True)
  self.first={'id':11,'port':20001,'protocol':'vless','network':'ws','security':'tls','path':'/one','tls':{'server_name':'one.example.com'},'clients':[{'id':'uuid-one','enable':True}]}
  self.other={**self.first,'id':12,'port':20002,'path':'/two','tls':{'server_name':'two.example.com'},'clients':[{'id':'uuid-two','enable':True}]}
  self.native.write_text(json.dumps({'inbounds':[self.first,self.other]}));self.request={'operation':'delete','port':20001,'domain':'one.example.com','path':'/one','uuid':'uuid-one'}
  def path(value):return self.root/str(value).lstrip('/')
  self.path=patch.object(action,'Path',side_effect=path);self.path.start()
 def tearDown(self):self.path.stop();self.tmp.cleanup()
 def api(self,path,params=None,post=False):
  if path=='/api/exits':return {'exits':[]}
  if path=='/api/xui/delete':
   self.assertEqual(params,{'ids':11});self.native.write_text(json.dumps({'inbounds':[self.other]}));return {'ok':True}
  raise AssertionError(path)
 def test_deletion_removes_only_the_exact_inbound_without_stopping_tunnels(self):
  with patch.object(action,'call_api',return_value=self.api),patch.object(action.subprocess,'run') as run:
   result=action.main(self.request)
  self.assertTrue(result['node_deleted']);self.assertEqual(json.loads(self.native.read_text())['inbounds'],[self.other]);run.assert_not_called()
 def test_changed_uuid_or_domain_is_rejected_before_mutation(self):
  for change in ({'uuid':'new-uuid'},{'domain':'new.example.com'},{'path':'/changed'}):
   with patch.object(action,'call_api',return_value=self.api),self.assertRaises(ValueError):action.main({**self.request,**change})
  self.assertEqual(len(json.loads(self.native.read_text())['inbounds']),2)
 def test_absent_node_deletion_is_idempotent(self):
  with patch.object(action,'call_api',return_value=self.api):result=action.main({**self.request,'port':20555})
  self.assertTrue(result['already_absent'])
