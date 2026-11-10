import json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
class NodeInstallerTests(unittest.TestCase):
 def test_fresh_system_without_usr_local_sbin_installs_monitors(self):
  script=Path(__file__).resolve().parents[1]/'scripts/install-node.py'
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'etc/init.d').mkdir(parents=True)
   def mapped(value):
    text=str(value)
    if text.startswith(('/var/lib/','/usr/local/','/etc/')):return root/text.lstrip('/')
    return Path(value)
   source=script.read_text().replace('from pathlib import Path','Path=map_path')
   with patch.object(sys,'argv',[str(script),'node.example.com','JP','33001']),patch.object(shutil,'which',return_value='/sbin/rc-service'),patch.object(subprocess,'run',return_value=Mock(returncode=0)):
    exec(compile(source,str(script),'exec'),{'__file__':str(script),'__name__':'__main__','map_path':mapped})
   self.assertTrue((root/'usr/local/sbin/fanout-ha').exists());self.assertTrue((root/'usr/local/sbin/fanout-speed').exists());self.assertTrue((root/'etc/init.d/fanout-shared-probe').exists());self.assertTrue((root/'var/lib/fanout-nodes/33001/enabled').exists())
