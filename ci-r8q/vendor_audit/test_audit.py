"""Bounded full-OTA fixtures; no network, mounts or physical devices."""
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
import zipfile
from unittest.mock import patch
import brotli

import audit_vendor as audit


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/'vendor.new.dat.br'
        self.destination=self.root/'vendor.img'
        self.transfer=b'4\n4\n0\n0\nnew 2,2,3\nzero 2,1,2\nnew 4,0,1,3,4\n'
        self.newdata=b'B'*4096+b'A'*4096+b'C'*4096
        self.source.write_bytes(brotli.compress(self.newdata))

    def test_full_ota_order_and_zeros(self):
        result=audit.reconstruct(self.source,self.transfer,self.destination,expected_bytes=16384)
        expected=b'A'*4096+b'\0'*4096+b'B'*4096+b'C'*4096
        self.assertEqual(self.destination.read_bytes(),expected)
        self.assertEqual(result['sha256'],hashlib.sha256(expected).hexdigest())
        self.assertEqual(result['new_bytes'],12288)

    def test_incremental_and_wrong_version_rejected(self):
        for data in (self.transfer.replace(b'new 2,2,3',b'move 2,2,3'),self.transfer.replace(b'4\n4',b'3\n4')):
            with self.assertRaises(ValueError):audit.parse_transfer(data,expected_bytes=16384)

    def test_overlapping_ranges_rejected(self):
        with self.assertRaises(ValueError):audit.parse_transfer(self.transfer.replace(b'zero 2,1,2',b'zero 2,0,2'),expected_bytes=16384)

    def test_unaccounted_gap_rejected(self):
        with self.assertRaises(ValueError):audit.parse_transfer(self.transfer.replace(b'zero 2,1,2\n',b''),expected_bytes=16384)

    def test_truncated_brotli_not_published(self):
        self.source.write_bytes(self.source.read_bytes()[:-1])
        with self.assertRaises((ValueError,brotli.error)):
            audit.reconstruct(self.source,self.transfer,self.destination,expected_bytes=16384)
        self.assertFalse(self.destination.exists())

    def test_extra_brotli_output_rejected(self):
        self.source.write_bytes(brotli.compress(self.newdata+b'EXTRA'))
        with self.assertRaises(ValueError):audit.reconstruct(self.source,self.transfer,self.destination,expected_bytes=16384)
        self.assertFalse(self.destination.exists())

    def test_existing_output_preserved(self):
        self.destination.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):audit.reconstruct(self.source,self.transfer,self.destination,expected_bytes=16384)
        self.assertEqual(self.destination.read_bytes(),b'keep')

    def test_collect_handles_real_tuple_api(self):
        class FakeExt4:
            block_size=4096;block_count=100;incompat=0;ro_compat=0
            def __init__(self,path):pass
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def list_dir(self,path):return [('build.prop',False),('alias',False)]
            def stat(self,path,follow_symlinks=False):
                return dict(mode=0o100644 if path=='/build.prop' else 0o120777,uid=0,gid=0,size=3)
            def read_file(self,path,max_bytes):return b'x=1'
            def readlink(self,path):return 'build.prop'
        with patch.object(audit,'Ext4',FakeExt4):result=audit.collect('unused',self.root)
        self.assertEqual(len(result['files']),2)
        self.assertEqual(result['files'][0]['target'],'build.prop')
        self.assertEqual((self.root/'configs/build.prop').read_bytes(),b'x=1')

    def test_contexts_without_extension_and_hardware_conf_exported(self):
        self.assertTrue(audit.selected_config('/etc/selinux/vendor_file_contexts'))
        self.assertTrue(audit.selected_config('/etc/selinux/vendor_property_contexts'))
        self.assertTrue(audit.selected_config('/etc/libnfc-nxp.conf'))
        self.assertTrue(audit.selected_config('/bin/enforcing.sh'))
        self.assertTrue(audit.selected_config('/bin/brightness_sync.sh'))
        self.assertFalse(audit.selected_config('/lib64/libhardware.so'))

    def test_actual_baseline_archive_loads(self):
        source=Path(__file__).parent/'data/baseline-vendor.zip'
        baseline,configs=audit.load_baseline(source)
        self.assertEqual(baseline['image']['sha256'],audit.BASELINE_SHA)
        self.assertIn('/etc/fstab.qcom',configs)
        self.assertGreater(len(baseline['files']),2000)

    def test_unknown_baseline_identity_rejected(self):
        path=self.root/'baseline.zip'
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('baseline.json',json.dumps(dict(schema_version=1,image=dict(bytes=1,sha256='0'*64))))
        with self.assertRaises(ValueError):audit.load_baseline(path)

    def test_diff_separates_metadata_and_content(self):
        a=dict(path='/etc/build.prop',mode=0o100644,uid=0,gid=0,type='regular',sha256='a')
        b=dict(a,uid=1000,sha256='b')
        result=audit.compare(dict(files=[a]),dict(files=[b]),{'/etc/build.prop':b'version=old'},{'/etc/build.prop':b'version=new'})
        self.assertEqual(result['changed_sha256'],['/etc/build.prop'])
        self.assertEqual(result['metadata_changed'],['/etc/build.prop'])
        self.assertEqual(result['property_files']['/etc/build.prop']['changed']['version'],dict(old='old',new='new'))

    def test_real_transfer_pinned(self):
        data=(Path(__file__).parent/'data/vendor.transfer.list').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),audit.TRANSFER_SHA)
        self.assertEqual(len(audit.parse_transfer(data)),799)


if __name__=='__main__':unittest.main()
