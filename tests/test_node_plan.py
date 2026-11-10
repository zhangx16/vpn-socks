import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'libexec'))
from node_plan import plan
class NodePlanTests(unittest.TestCase):
 def setUp(self):self.request={'domain':'node.example.com','path':'/two','port':35001};self.first={'port':35001,'path':'/one','tls':{'server_name':'node.example.com'}}
 def test_shared_domain_new_path_gets_distinct_internal_port(self):
  result,inbound=plan(self.request,[self.first],{},lambda port:port!=20000)
  self.assertIsNone(inbound);self.assertEqual(result['port'],20001);self.assertEqual(result['public_port'],35001);self.assertEqual(self.first['port'],35001)
 def test_retry_adopts_existing_exact_path_instead_of_duplicating_node(self):
  second={'port':20001,'path':'/two','tls':{'server_name':'node.example.com'}}
  result,inbound=plan(self.request,[self.first,second],{},lambda port:True);self.assertEqual(result['port'],20001);self.assertEqual(inbound,second)
 def test_same_domain_cannot_silently_change_shared_origin_port(self):
  with self.assertRaises(ValueError):plan({**self.request,'port':35002},[self.first],{'node.example.com|/one':{'public_port':35001,'port':35001,'path':'/one'}},lambda p:True)
 def test_changed_recorded_identity_is_rejected(self):
  with self.assertRaises(ValueError):plan(self.request,[self.first],{'node.example.com|/two':{'port':35001,'public_port':35001,'path':'/two'}},lambda p:True)
