from pathlib import Path
import hashlib
import io
import json
import sys
import unittest
from unittest.mock import patch
import zipfile
import test_single_zip as old

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import p1r3_materials
import package_p1_single as package


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):old.NativeTests.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):old.NativeTests.tearDownClass.__func__(cls)
    setUp=old.NativeTests.setUp

    def test_complete_revision_zip_has_matching_label_collector_and_write_guards(self):
        images=[]
        for part,length in (('super',32768),('boot',8192),('dtbo',4096)):
            data=(part.encode()*length)[:length];path=self.folder/(part+'.img');path.write_bytes(data)
            images.append(dict(partition=part,file=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        omitted=[dict(partition=p,path='/etc/selinux/mapping/30.0.cil',old_sha256='a'*64)for p in ('system_ext','product')]
        collector=p1r3_materials.collector_bytes(ROOT)
        extras={'extras/R8Q-BOOTDIAG-V6-COLLECT-ONLY.zip':collector}
        evidence=dict(susfs_enabled=True,hardware_boot_confirmed=False)
        expected=next(r['sha256']for r in images if r['partition']=='boot')
        output=self.folder/'HyperOS4-R8Q-P1r4-SINGLE-EXPERIMENTAL.zip'
        with patch.object(p1r3_materials,'collect',return_value=(expected,extras,evidence)):
            result=package.build(output,self.helper,images,require_arm64=False,host_helper=self.helper,
                build_label='P1r4',omitted_optional_mappings=omitted,revision_manifest={'build_label':'P1r4'})
        self.assertEqual(result['build_label'],'P1r4')
        with zipfile.ZipFile(output)as archive:
            self.assertIsNone(archive.testzip())
            script=archive.read(package.INSTALLER).decode()
            self.assertIn('P1r4 SINGLE ZIP EXPERIMENTAL',script)
            self.assertIn('check_battery before-write',script)
            self.assertIn('verify_written super',script)
            self.assertNotIn('@@',script)
            manifest=json.loads(archive.read('P1-MANIFEST.json'))
            self.assertIs(manifest['revision_evidence']['susfs_enabled'],True)
            notes=archive.read('README-TESTER.txt').decode()
            self.assertIn('No separate ENABLE',notes)
            self.assertIn('COLLECT-ONLY.zip',notes)
            self.assertNotIn('manual OrangeFox Format Data',notes)
            with zipfile.ZipFile(io.BytesIO(archive.read('extras/R8Q-BOOTDIAG-V6-COLLECT-ONLY.zip')))as nested:
                self.assertIsNone(nested.testzip())


if __name__=='__main__':unittest.main()
