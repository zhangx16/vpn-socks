import base64,importlib.util,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch,Mock
spec=importlib.util.spec_from_file_location('pool',Path(__file__).resolve().parents[1]/'libexec/catalog_pool.py')
pool=importlib.util.module_from_spec(spec);spec.loader.exec_module(pool)
def row(host='vpn1',ip='8.8.8.8',code='JP'):
 r={f:'0' for f in pool.FIELDS};r.update(HostName=host,IP=ip,CountryShort=code,CountryLong='Japan',Speed='100',OpenVPN_ConfigData_Base64=base64.b64encode(('client\ndev tun\nproto tcp\nremote '+ip+' 443\n').encode()).decode());return r
class PoolTests(unittest.TestCase):
 def test_deduplicates_same_ip_across_sources_and_aliases(self):
  items=pool.merge({},[('main',[row()]),('mirror',[row(),row('alias')])],100)
  self.assertEqual(len(items),1)
 def test_new_address_supersedes_old_hostname_configuration(self):
  old=pool.merge({},[('main',[row()])],100)
  merged=pool.merge(old,[('main',[row(ip='1.1.1.1')])],200)
  self.assertEqual([v['row']['IP'] for v in merged.values()],['1.1.1.1'])
 def test_unseen_nodes_expire_after_24_hours(self):
  old=pool.merge({},[('main',[row()])],100)
  self.assertEqual(len(pool.merge(old,[],100+pool.TTL+1)),0)
 def test_keeps_previous_nodes_when_different_snapshot_arrives(self):
  old=pool.merge({},[('main',[row()])],100)
  self.assertEqual(len(pool.merge(old,[('mirror',[row('vpn2','1.1.1.1')])],200)),2)
 def test_peer_history_does_not_extend_last_seen_or_keep_obsolete_hostname_ip(self):
  old=pool.merge({},[('main',[row()])],100)
  new=pool.merge({},[('main',[row(ip='1.1.1.1')])],200)
  merged=pool.merge(old|new,[],300)
  self.assertEqual(len(merged),1);self.assertEqual(next(iter(merged.values()))['last_seen'],200)
 def test_peer_uses_pinned_host_key_and_preserves_original_age(self):
  state={'items':pool.merge({},[('main',[row()])],100)}
  peer={'key_file':'/private/readonly-key','known_hosts_file':'/private/pinned-host','port':2222,'user':'root','host':'8.8.4.4'}
  with patch.object(pool.subprocess,'run',return_value=Mock(returncode=0,stdout=json.dumps(state).encode())) as ssh:
   found=pool.peer_snapshot(peer,200)
  self.assertEqual(next(iter(found.values()))['last_seen'],100)
  self.assertIn('StrictHostKeyChecking=yes',ssh.call_args.args[0])
  with patch.object(pool.subprocess,'run',return_value=Mock(returncode=0,stdout=json.dumps(state).encode())):
   self.assertEqual(pool.peer_snapshot(peer,100+pool.TTL+1),{})
 def test_csv_round_trip_preserves_configs_and_all_types(self):
  items=pool.merge({},[('main',[row('public-vpn-1','219.100.37.1')])],100)
  self.assertEqual(pool.parse(pool.render(items))[0]['HostName'],'public-vpn-1')
 def test_mirror_discovery_uses_public_literal_ips_and_is_bounded(self):
  s=''.join('<a href="'+u+'">mirror</a>' for u in ['http://127.0.0.1:80/en/','http://8.8.8.8:81/en/','http://1.1.1.1:82/en/'])
  self.assertEqual(pool.mirror_sources(s,1),['http://8.8.8.8:81/api/iphone/'])
 def test_rejects_executable_openvpn_directives(self):
  r=row();r['OpenVPN_ConfigData_Base64']=base64.b64encode(b'remote 8.8.8.8 443\nup /tmp/executable\n').decode()
  with self.assertRaises(ValueError):pool.parse(pool.render(pool.merge({},[('main',[r])],100)))
 def test_force_fetch_failure_preserves_saved_pool(self):
  with tempfile.TemporaryDirectory() as d:
   with patch.object(pool,'download',side_effect=lambda u: '<html></html>' if u==pool.MIRRORS else pool.render(pool.merge({},[('main',[row()])],100))):
    state=pool.collect(d,True)
   original=(Path(d)/'pool.json').read_text()
   with patch.object(pool,'download',side_effect=ValueError('offline')):
    with self.assertRaises(ValueError):pool.collect(d,True)
   self.assertEqual((Path(d)/'pool.json').read_text(),original)
if __name__=='__main__':unittest.main()
