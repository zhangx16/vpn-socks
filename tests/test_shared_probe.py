import importlib.util,json,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('shared_probe',Path(__file__).resolve().parents[1]/'scripts/shared-probe.py');probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
class SharedProbeTests(unittest.TestCase):
 def test_two_nodes_share_config_without_tag_or_port_collisions(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for i in (1,2):
    node=root/str(20000+i);(node/'ha').mkdir(parents=True);(node/'enabled').touch();(node/'ha/probe.json').write_text(json.dumps({'inbounds':[{'tag':'cf-check','port':18000+i}],'outbounds':[{'tag':'cf'}],'routing':{'rules':[{'inboundTag':['cf-check'],'outboundTag':'cf'}]}}))
   result=probe.aggregate(root);self.assertEqual(len(result['inbounds']),2);self.assertEqual(len({r['tag'] for r in result['inbounds']}),2);self.assertEqual(result['routing']['rules'][0]['outboundTag'],'n20001_cf')
   (root/'20001/disabled').touch();self.assertEqual(len(probe.aggregate(root)['inbounds']),1)
