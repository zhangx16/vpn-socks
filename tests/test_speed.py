import importlib.machinery
import importlib.util
import json
import tempfile
import ast
import ipaddress
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

loader=importlib.machinery.SourceFileLoader('fanout_speed',str(Path(__file__).resolve().parents[1]/'bin'/'fanout-speed'))
spec=importlib.util.spec_from_loader(loader.name,loader)
speed=importlib.util.module_from_spec(spec)
loader.exec_module(speed)

class TriggerTests(unittest.TestCase):
    def test_korean_region_and_custom_inbound_tag(self):
        ha={'region':'KR','primary_inbound_tag':'in-35001-ws'}
        def read(path,default): return ha if path==speed.HA_CONFIG else default
        with patch.object(speed,'read_json',side_effect=read):
            self.assertEqual(speed.configuration()['region'],'KR')
            view={'exits':[{'slot':1,'inbounds':[{'tag':'in-33003-ws'}]},
                           {'slot':2,'inbounds':[{'tag':'in-35001-ws'}]}]}
            self.assertEqual(speed.API.active(view)['slot'],2)

    def test_exact_20_mbps_is_not_low(self):
        self.assertEqual(speed.low_streak({'sample_host':'a','low_count':2},'a',2500000,speed.DEFAULTS),0)

    def test_host_change_and_unavailable_sample_reset_streak(self):
        old={'sample_host':'a','low_count':2}
        self.assertEqual(speed.low_streak(old,'b',1000000,speed.DEFAULTS),1)
        self.assertEqual(speed.low_streak(old,'a',None,speed.DEFAULTS),0)

    def run_ticks(self, samples, last_scan=0):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            speed.write_json(root/'state.json',{'last_scan_started':last_scan})
            api=Mock()
            api.view.return_value={'exits':[]}
            api.active.return_value={'host':'a','exit_ip':'1.2.3.4','status':'up'}
            speed.write_json(root/'status.json',{'state':'healthy'})
            with patch.object(speed,'ROOT',root),patch.object(speed,'HA',root),patch.object(speed,'API',return_value=api),patch.object(speed,'configuration',return_value=speed.DEFAULTS),patch.object(speed,'throughput',side_effect=samples),patch.object(speed,'scan_and_replace') as scan:
                for _ in samples: speed.tick()
                return scan.call_count,speed.read_json(root/'state.json',{})

    def test_three_consecutive_low_samples_trigger(self):
        calls,state=self.run_ticks([1000000]*3)
        self.assertEqual(calls,1)
        self.assertEqual(state['low_count'],3)

    def test_healthy_sample_breaks_streak(self):
        calls,state=self.run_ticks([1000000,3000000,1000000,1000000])
        self.assertEqual(calls,0)
        self.assertEqual(state['low_count'],2)

    def test_cooldown_prevents_repeat_scan(self):
        calls,_=self.run_ticks([1000000]*3,last_scan=speed.time.time())
        self.assertEqual(calls,0)

    def test_partial_http_200_timeout_counts_as_low_speed(self):
        result=Mock(stdout='200 100000 8333',returncode=28)
        with patch.object(speed.subprocess,'run',return_value=result):
            self.assertEqual(speed.throughput(speed.DEFAULTS),8333)

    def test_http_error_is_not_a_slow_exit(self):
        with patch.object(speed.subprocess,'run',return_value=Mock(stdout='403 1 4',returncode=0)):
            self.assertIsNone(speed.throughput(speed.DEFAULTS))

class CleanupTests(unittest.TestCase):
    def test_private_dns_routes_exclude_public_and_loopback_resolvers(self):
        path=Path(__file__).resolve().parents[1]/'libexec'/'scan-jp'
        tree=ast.parse(path.read_text())
        definition=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='private_resolvers')
        scope={'ipaddress':ipaddress}
        exec(compile(ast.Module(body=[definition],type_ignores=[]),str(path),'exec'),scope)
        text='nameserver 10.10.0.1\nnameserver 172.31.0.53\nnameserver 192.168.1.1\nnameserver 1.1.1.1\nnameserver 127.0.0.1\nnameserver ::1\nnameserver invalid\n'
        self.assertEqual(scope['private_resolvers'](text),['10.10.0.1','172.31.0.53','192.168.1.1'])

    def test_cleanup_never_stops_active_or_protected_exit(self):
        api=object.__new__(speed.API)
        api.view=Mock(return_value={'exits':[{'slot':1,'inbounds':[{'tag':'in-33003-ws'}]},{'slot':2,'inbounds':None},{'slot':3,'inbounds':None}]})
        api.call=Mock()
        self.assertFalse(api.stop_unused(1,set()))
        self.assertFalse(api.stop_unused(2,{2}))
        api.call.assert_not_called()
        self.assertTrue(api.stop_unused(3,{2}))
        api.call.assert_called_once()

if __name__=='__main__': unittest.main()
