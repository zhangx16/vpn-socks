import importlib.util,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('control_health',Path(__file__).resolve().parents[1]/'scripts/control-health.py');health=importlib.util.module_from_spec(spec);spec.loader.exec_module(health)
class ControlHealthTests(unittest.TestCase):
 def setUp(self):self.config={'port':35001,'listenPort':20000,'domain':'node.example.com','path':'/node','uuid':'expected-uuid','region':'JP'};self.inbound={'port':20000,'path':'/node','tls':{'server_name':'node.example.com'},'clients':[{'id':'expected-uuid'}]}
 def test_changed_identity_disables_shared_repairs(self):
  with patch.object(health,'read',return_value={'inbounds':[self.inbound]}),patch.object(health,'service') as service,patch.object(health,'manager_snapshot',return_value=[]):
   result=health.main({'nodes':[{'id':'node','config':{**self.config,'uuid':'changed'}}],'repair':True})
  service.assert_not_called();self.assertEqual(result['nodes'][0]['state'],'identity_changed')
 def test_websocket_transport_is_insufficient_when_country_is_wrong(self):
  with patch.object(health,'read',return_value={'cf_port':18000,'origin_port':18001}),patch.object(health,'trace',return_value={'ip':'8.8.4.4','loc':'US'}),patch.object(health,'service',return_value=True),patch.object(health,'listening',return_value=True):result=health.inspect(self.config)
  self.assertEqual(result['state'],'degraded');self.assertIn('国家',result['reason'])
