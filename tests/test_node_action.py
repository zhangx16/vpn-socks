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

 def switch_view(self):return {'exits':[{'slot':1,'host':'original','exit_ip':'8.8.8.8','region':'KR','status':'up','inbounds':[{'tag':'in-20001-ws'}]},{'slot':2,'host':'backup','exit_ip':'8.8.4.4','region':'KR','status':'up','inbounds':[]}]}
 def test_manual_switch_changes_only_selected_tag_after_validation(self):
  view=self.switch_view();calls=[]
  def api(path,params=None,post=False):calls.append((path,params));return view if path=='/api/exits' else {'ok':True}
  request={**self.request,'operation':'switch','region':'KR','targetHost':'backup','targetIP':'8.8.4.4'}
  with patch.object(action,'actual_exit',return_value={'ip':'8.8.4.4','loc':'KR'}):result=action.switch_exit(api,view,{'inbounds':[self.first,self.other]},request)
  self.assertEqual(result['exit_ip'],'8.8.4.4');self.assertEqual([p for path,p in calls if path=='/api/xui/bind'],[{'tag':'in-20001-ws','host':'backup'}])
 def test_failed_full_chain_verification_rolls_back_binding(self):
  view=self.switch_view();calls=[]
  def api(path,params=None,post=False):calls.append((path,params));return view if path=='/api/exits' else {}
  request={**self.request,'operation':'switch','region':'KR','targetHost':'backup','targetIP':'8.8.4.4'}
  with patch.object(action,'actual_exit',return_value={'ip':'1.1.1.1','loc':'US'}),self.assertRaises(ValueError):action.switch_exit(api,view,{'inbounds':[self.first]},request)
  self.assertEqual([p for path,p in calls if path=='/api/xui/bind'][-1],{'tag':'in-20001-ws','host':'original'})
 def test_exit_owned_by_another_node_cannot_be_selected(self):
  view=self.switch_view();view['exits'][1]['inbounds']=[{'tag':'in-20002-ws'}]
  options=action.exit_options(view,{**self.request,'region':'KR'});self.assertFalse(next(r for r in options if r['host']=='backup')['available'])
