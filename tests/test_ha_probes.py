import os,subprocess,unittest
from pathlib import Path
source=(Path(__file__).resolve().parents[1]/'bin/fanout-ha').read_text();function='probe() {'+source.split('probe() {',1)[1].split('\n}',1)[0]+'\n}\n'
class CountryProbeTests(unittest.TestCase):
 def run_probe(self,region,trace,code=0):
  script=function+'\ncurl() { printf "%s" "$MOCK_TRACE"; return "$MOCK_CODE"; }\nprobe socks5h://127.0.0.1:18000\n'
  return subprocess.run(['bash'],input=script,capture_output=True,text=True,env={**os.environ,'REGION':region,'MOCK_TRACE':trace,'MOCK_CODE':str(code)})
 def test_wrong_country_is_never_accepted_as_healthy(self):self.assertNotEqual(self.run_probe('JP','ip=8.8.4.4\nloc=KR\n').returncode,0)
 def test_matching_country_returns_actual_exit_ip(self):
  result=self.run_probe('JP','ip=8.8.4.4\nloc=JP\n');self.assertEqual(result.returncode,0);self.assertEqual(result.stdout.strip(),'8.8.4.4')
 def test_failed_network_request_is_not_healthy(self):self.assertNotEqual(self.run_probe('JP','',7).returncode,0)
