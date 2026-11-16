"""Real ext4 fixtures for the targeted Vendor metadata repair."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('vendor_labels', ROOT/'tools/vendor_security/image_labels.py')
labels = importlib.util.module_from_spec(spec)
spec.loader.exec_module(labels)
ext4 = labels.ext4
MKFS = shutil.which('mke2fs')
AVAILABLE = bool(MKFS and Path(ext4.tool('debugfs')).is_file() and Path(ext4.tool('e2fsck')).is_file())


@unittest.skipUnless(AVAILABLE, 'Real ext4 fixtures require e2fsprogs; CI installs it')
class Tests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(prefix='r8q-vendor-label-test-')
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.source = self.root/'source.img'
        with self.source.open('wb') as f: f.truncate(32*1024**2)
        subprocess.run([MKFS, '-q', '-t', 'ext4', '-F', str(self.source)], check=True, capture_output=True)
        fs = ext4.Ext4(self.source, self.root)
        for path in ['/etc','/etc/selinux']: fs.command('mkdir '+path, writable=True)
        self.targets = copy.deepcopy(labels.package.profile()['labels'])
        for row in self.targets:
            path = '/' if row['path'] == '.' else '/'+row['path']
            if path != '/':
                b=('fixture:'+path).encode();row['sha256']=hashlib.sha256(b).hexdigest()
                data=self.root/'data';data.write_bytes(b);fs.command('write '+str(data)+' '+path,writable=True)
            old='u:object_r:vendor_apex_file:s0' if path=='/' else 'u:object_r:vendor_configs_file:s0'
            fs.command('ea_set '+path+' security.selinux '+old,writable=True)
        b=self.root/'keep';b.write_bytes(b'UNRELATED FILE\n');fs.command('write '+str(b)+' /keep',writable=True)
        fs.command('ea_set /keep user.test unrelated',writable=True)
        self.output = self.root/'fixed.img'

    def test_repairs_root_and_context_labels_without_changing_bytes_or_other_metadata(self):
        fs=ext4.Ext4(self.source,self.root);before=fs.stat('/keep');digest=ext4.sha_file(self.source)
        result=labels.repair(self.source,self.output,digest,self.targets)
        self.assertEqual(ext4.sha_file(self.source),digest)
        fixed=ext4.Ext4(self.output,self.root)
        self.assertEqual(fixed.content('/keep'),b'UNRELATED FILE\n')
        self.assertTrue(ext4.metadata_equal(before,fixed.stat('/keep')))
        self.assertEqual(result['candidate_e2fsck']['exit'],0)
        self.assertTrue(all(r['correct'] for r in labels.inspect(self.output,self.root,self.targets)))
        self.assertFalse(result['hardware_boot_confirmed'])

    def test_wrong_source_or_content_pin_and_inplace_or_existing_output_are_rejected(self):
        digest=ext4.sha_file(self.source)
        with self.assertRaises(ValueError):labels.repair(self.source,self.output,'0'*64,self.targets)
        bad=copy.deepcopy(self.targets);bad[1]['sha256']='0'*64
        with self.assertRaises(ValueError):labels.repair(self.source,self.output,digest,bad)
        self.assertFalse(self.output.exists())
        with self.assertRaises(ValueError):labels.repair(self.source,self.source,digest,self.targets)
        self.output.write_bytes(b'KEEP')
        with self.assertRaises(ValueError):labels.repair(self.source,self.output,digest,self.targets)
        self.assertEqual(self.output.read_bytes(),b'KEEP')

    def test_symlink_metadata_target_is_refused(self):
        fs=ext4.Ext4(self.source,self.root);path='/'+self.targets[1]['path']
        fs.command('rm '+path,writable=True);fs.command('symlink '+path+' /keep',writable=True)
        with self.assertRaises(ValueError):labels.repair(self.source,self.output,ext4.sha_file(self.source),self.targets)
        self.assertFalse(self.output.exists())

    def test_full_builder_consumes_checked_metadata_image_and_records_proof_chain(self):
        build_spec=importlib.util.spec_from_file_location('security_ci_builder',ROOT/'tools/rebuild_p1_ci.py')
        build=importlib.util.module_from_spec(build_spec);build_spec.loader.exec_module(build)
        report=self.root/'vendor-build.json';report.write_text(json.dumps({'output_sha256':ext4.sha_file(self.source)}))
        with patch.object(labels.package,'profile',return_value={'labels':self.targets}):
            result=build.repair_rebuilt_vendor_labels(self.source,self.root)
        self.assertEqual(ext4.sha_file(self.source),result['candidate_sha256'])
        self.assertEqual(result['prelabel_build_report_sha256'],ext4.sha_file(report))
        self.assertTrue((self.root/'vendor-label-repair.json').is_file())
        self.assertTrue(all(r['correct']for r in labels.inspect(self.source,self.root,self.targets)))


if __name__=='__main__':unittest.main()
