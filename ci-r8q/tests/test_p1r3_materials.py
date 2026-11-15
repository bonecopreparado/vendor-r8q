from pathlib import Path
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import test_susfs22_linked_verifier as linked
import test_nflog_boot_repack as boot_fixture

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'tools/bootdiag_v6'))
import p1r3_materials as materials
import package_bootdiag_v5 as probe
import repack_verified as repack


class Tests(unittest.TestCase):
    def fixture(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        (root/'LICENSE').write_bytes((ROOT/'LICENSE').read_bytes())
        original=boot_fixture.Tests().boot()
        original+=bytes(512*1024-len(original))
        kernel,summary=linked.fixture()
        guards=patch.multiple(repack,BOOT_BYTES=len(original),BOOT_SHA=materials.sha(original))
        guards.start();self.addCleanup(guards.stop)
        _,proof=repack.repack(original,kernel,summary)
        for name,data in (('old.img',original),('Image',kernel),('summary.json',json.dumps(summary).encode())):
            (root/name).write_bytes(data)
        helper=b'validated native-build fixture'
        notices={'licenses/NOTICE.txt':b'preserve this notice exactly'}
        for name,data in notices.items():
            p=root/'patches/0008-boot-fixes/zip-extra'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        native=patch.object(probe,'validate_probe',return_value=(helper,{'fixture':True},notices))
        native.start();self.addCleanup(native.stop)
        manifest=dict(build_label='P1r3',kernel_repack_inputs=dict(source_boot_file='old.img',kernel_file='Image',summary_file='summary.json'),
            kernel_repack=proof,diagnostic_probe_dir='probe',diagnostic_stage=dict(diagnostics=dict(
                namespace='/metadata/r8q-bootdiag-v6',probe_sha256=materials.sha(helper),probe_build={'fixture':True},
                required_zip_licenses={name:materials.sha(data)for name,data in notices.items()})))
        return root,manifest,notices

    def test_regenerated_real_boot_proof_and_license_bytes_bind_zip_extras(self):
        root,manifest,notices=self.fixture()
        boot_sha,extras,evidence=materials.collect(manifest,root)
        self.assertEqual(boot_sha,manifest['kernel_repack']['candidate_boot_sha256'])
        self.assertEqual(extras['licenses/display-probe/NOTICE.txt'],notices['licenses/NOTICE.txt'])
        name='extras/R8Q-BOOTDIAG-V6-COLLECT-ONLY.zip'
        self.assertIn(materials.sha(extras[name]),extras[name+'.sha256'].decode())
        with zipfile.ZipFile(io.BytesIO(extras[name]))as archive:
            self.assertIsNone(archive.testzip())
            script=archive.read('META-INF/com/google/android/update-binary')
            self.assertIn(b'r8q-bootdiag-v6',script)
            self.assertEqual(archive.getinfo('META-INF/com/google/android/update-binary').external_attr>>16,0o100755)
        self.assertIs(evidence['susfs_enabled'],True)
        self.assertIs(evidence['hardware_boot_confirmed'],False)

    def test_forged_boot_marker_or_changed_native_notices_are_refused(self):
        root,manifest,_=self.fixture()
        changed=copy.deepcopy(manifest);changed['kernel_repack']['candidate_boot_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'Regenerated'):
            materials.collect(changed,root)
        (root/'patches/0008-boot-fixes/zip-extra/licenses/NOTICE.txt').write_bytes(b'missing copyright')
        with self.assertRaisesRegex(ValueError,'license differs'):
            materials.collect(manifest,root)

    def test_revision_paths_cannot_escape_checkout(self):
        root,manifest,_=self.fixture()
        for value in ('../Image','/Image','./Image','a//Image'):
            changed=copy.deepcopy(manifest);changed['kernel_repack_inputs']['kernel_file']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                materials.collect(changed,root)


if __name__=='__main__':unittest.main()
