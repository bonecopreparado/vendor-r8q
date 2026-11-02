"""Bounded offline ext4 patch fixtures; no physical partitions or firmware."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('ext4_candidate',ROOT/'tools/patch_ext4_candidate.py')
patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
LOCAL_MKFS=ROOT/'tools/image-tools/root/usr/sbin/mke2fs'
MKFS=str(LOCAL_MKFS) if LOCAL_MKFS.is_file() else shutil.which('mke2fs')
AVAILABLE=bool(MKFS and Path(patch.tool('debugfs')).is_file() and Path(patch.tool('e2fsck')).is_file())


@unittest.skipUnless(AVAILABLE,'Host e2fsprogs tools are required for bounded ext4 fixtures')
class Ext4CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='r8q-ext4-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.image=self.root/'original.img'
        with self.image.open('wb') as stream:stream.truncate(32*1024**2)
        env=os.environ.copy()
        if LOCAL_MKFS.is_file():env['LD_LIBRARY_PATH']=str(ROOT/'tools/image-tools/root/usr/lib/x86_64-linux-gnu')
        subprocess.run([MKFS,'-q','-t','ext4','-F',str(self.image)],env=env,check=True,capture_output=True)
        self.fs=patch.Ext4(self.image,self.root)
        self.fs.command('mkdir /etc',writable=True)
        self.old=self.root/'old';self.old.write_bytes(b'original init config\n')
        self.fs.command('write '+str(self.old)+' /etc/service.rc',writable=True)
        for key,value in [('uid',123),('gid',456),('mode','0100640'),('projid',7),('generation',12),('atime','0x12345678')]:
            self.fs.command('set_inode_field /etc/service.rc '+key+' '+str(value),writable=True)
        self.fs.command('ea_set /etc/service.rc security.selinux u:object_r:vendor_configs_file:s0',writable=True)
        self.binary_attr=self.root/'binary';self.binary_attr.write_bytes(b'\x00arbitrary\xff\x00')
        self.fs.command('ea_set -f '+str(self.binary_attr)+' /etc/service.rc user.fixture',writable=True)
        self.new=self.root/'new';self.new.write_bytes(b'corrected init config longer than the original\n')
        self.output=self.root/'candidate.img'

    def plan(self,operations):
        p=self.root/'plan.json'
        p.write_text(json.dumps(dict(schema_version=1,source_image_sha256=patch.sha_file(self.image),operations=operations)))
        return p

    def replace(self,**extra):
        return dict(op='replace',path='/etc/service.rc',old_sha256=hashlib.sha256(self.old.read_bytes()).hexdigest(),
                    source='new',sha256=hashlib.sha256(self.new.read_bytes()).hexdigest())|extra

    def run_patch(self,operations):return patch.patch_image(self.image,self.plan(operations),self.output)

    def test_replace_preserves_file_and_parent_metadata_and_original(self):
        original_sha=patch.sha_file(self.image)
        before=self.fs.stat('/etc/service.rc');parent=self.fs.stat('/etc')
        result=self.run_patch([self.replace()])
        newfs=patch.Ext4(self.output,self.root)
        self.assertEqual(newfs.content('/etc/service.rc'),self.new.read_bytes())
        self.assertTrue(patch.metadata_equal(before,newfs.stat('/etc/service.rc')))
        self.assertTrue(patch.metadata_equal(parent,newfs.stat('/etc')))
        self.assertEqual(patch.sha_file(self.image),original_sha)
        self.assertEqual(result['candidate_e2fsck']['exit'],0)
        self.assertFalse(result['boot_confirmed'])

    def test_delete_and_add_preserve_label_from_explicit_template(self):
        row=self.replace()
        before=self.fs.stat('/etc/service.rc')
        added=dict(op='add',path='/etc/new.rc',metadata_from='/etc/service.rc',source='new',sha256=row['sha256'])
        deleted=dict(op='delete',path='/etc/service.rc',old_sha256=row['old_sha256'])
        self.run_patch([added,deleted])
        newfs=patch.Ext4(self.output,self.root)
        self.assertIsNone(newfs.stat('/etc/service.rc',missing_ok=True))
        self.assertEqual(newfs.content('/etc/new.rc'),self.new.read_bytes())
        self.assertTrue(patch.metadata_equal(before,newfs.stat('/etc/new.rc')))

    def test_bad_image_identity_stops_without_output(self):
        p=self.plan([self.replace()]);data=json.loads(p.read_text());data['source_image_sha256']='0'*64;p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'Source image SHA256'):patch.patch_image(self.image,p,self.output)
        self.assertFalse(self.output.exists())

    def test_bad_old_or_new_hash_stops_without_output(self):
        for key in ('old_sha256','sha256'):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError,'SHA256'):self.run_patch([self.replace(**{key:'0'*64})])
                self.assertFalse(self.output.exists())

    def test_symlink_target_or_parent_rejected(self):
        self.fs.command('symlink /etc/link service.rc',writable=True)
        self.fs.command('symlink /alias /etc',writable=True)
        for path in ('/etc/link','/alias/service.rc'):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):self.run_patch([self.replace(path=path)])
                self.assertFalse(self.output.exists())

    def test_hardlinked_regular_file_is_rejected(self):
        self.fs.command('link /etc/service.rc /etc/hardlink.rc',writable=True)
        self.fs.command('set_inode_field /etc/service.rc links_count 2',writable=True)
        with self.assertRaisesRegex(ValueError,'single-link'):self.run_patch([self.replace()])
        self.assertFalse(self.output.exists())

    def test_existing_output_and_in_place_changes_are_rejected(self):
        self.output.write_bytes(b'keep existing result')
        with self.assertRaises(ValueError):self.run_patch([self.replace()])
        self.assertEqual(self.output.read_bytes(),b'keep existing result')
        with self.assertRaises(ValueError):patch.patch_image(self.image,self.plan([self.replace()]),self.image)

    def test_path_injection_and_traversal_are_rejected(self):
        for path in ('/etc/x;rm','/etc/../service.rc','/etc//service.rc','/etc/with space'):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):self.run_patch([self.replace(path=path)])
                self.assertFalse(self.output.exists())

    def test_cli_report_cannot_overwrite_source_image(self):
        original_sha=patch.sha_file(self.image)
        p=subprocess.run(['python3',str(ROOT/'tools/patch_ext4_candidate.py'),
                          '--source',str(self.image),'--plan',str(self.plan([self.replace()])),
                          '--output',str(self.output),'--report',str(self.image)],capture_output=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn(b'Report must be a fresh path',p.stderr)
        self.assertEqual(patch.sha_file(self.image),original_sha)
        self.assertFalse(self.output.exists())

    def test_clean_candidate_does_not_reindex_untouched_large_directory(self):
        self.fs.command('mkdir /many',writable=True)
        commands=self.root/'many-files.commands'
        commands.write_text('\n'.join('write '+str(self.old)+' /many/'+str(n)+'-'+'a'*180 for n in range(120))+'\n')
        p=subprocess.run([patch.tool('debugfs'),'-w','-f',str(commands),str(self.image)],capture_output=True)
        self.assertEqual(p.returncode,0)
        old=self.fs.stat('/many')
        self.assertGreater(old['size'],2048)
        self.assertEqual(old['flags']&0x1000,0)
        self.fs.command('write '+str(self.old)+' /etc/plain.rc',writable=True)
        result=self.run_patch([self.replace(path='/etc/plain.rc')])
        self.assertTrue(result['staging_e2fsck_preen']['skipped'])
        new=patch.Ext4(self.output,self.root).stat('/many')
        self.assertEqual(old['flags'],new['flags'])
        self.assertEqual(old['size'],new['size'])


if __name__=='__main__':unittest.main()
