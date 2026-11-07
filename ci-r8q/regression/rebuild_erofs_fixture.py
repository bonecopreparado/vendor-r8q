"""Real erofs-utils bounded fixtures; no mounts or real device files."""
from pathlib import Path
import hashlib, importlib.util, io, json, os, subprocess, sys, tarfile, tempfile, unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('rebuild',ROOT/'tools/rebuild_erofs_candidate.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@unittest.skipUnless((ROOT/'tools/image-tools/root/usr/bin/mkfs.erofs').exists(),'Pinned local erofs-utils required')
class Tests(unittest.TestCase):
    def fixture(self):
        tmp=tempfile.TemporaryDirectory(prefix='r8q-rebuild-fixture-');self.addCleanup(tmp.cleanup)
        root=Path(tmp.name);(root/'tools/image-tools/root/usr').mkdir(parents=True)
        (root/'tools/image-tools/root/usr/bin').symlink_to(ROOT/'tools/image-tools/root/usr/bin')
        tar=root/'base.tar';old=b'OLD-CONTENT\n'*1500
        with tarfile.open(tar,'w',format=tarfile.PAX_FORMAT) as archive:
            for name,kind,data in [('.',tarfile.DIRTYPE,b''),('etc',tarfile.DIRTYPE,b''),
                                   ('etc/policy.cil',tarfile.REGTYPE,old),('keep',tarfile.REGTYPE,b'UNCHANGED\n'*1000),
                                   ('link',tarfile.SYMTYPE,b''),('hardlink',tarfile.LNKTYPE,b'')]:
                entry=tarfile.TarInfo(name);entry.type=kind;entry.mode=0o755 if kind==tarfile.DIRTYPE else 0o644
                entry.uid=0;entry.gid=2000;entry.mtime=1230768000
                entry.pax_headers['SCHILY.xattr.security.selinux']='u:object_r:system_file:s0'
                entry.pax_headers['SCHILY.xattr.user.fixture']='preserve-me'
                if name=='keep':
                    entry.uid=65536
                    entry.pax_headers['SCHILY.xattr.security.capability']=b'\x01\x00\x00\x02\x80\xff\x00\x00\x00\x00'.decode('utf-8','surrogateescape')
                if kind==tarfile.SYMTYPE:entry.linkname='etc/policy.cil'
                if kind==tarfile.LNKTYPE:entry.linkname='keep'
                entry.size=len(data);archive.addfile(entry,io.BytesIO(data))
        source=root/'base.img'
        m.run([ROOT/'tools/image-tools/root/usr/bin/mkfs.erofs','--tar=f','-z','lz4hc','-T','1230768000','--mkfs-time',source,tar])
        (root/'replacement.cil').write_bytes(b'NEW-CONTENT\n'*1700)
        plan=dict(source_image='base.img',source_sha256=m.file_sha(source),output_image='new.img',
                  patches=[dict(path='/etc/policy.cil',old_sha256=m.sha(old),replacement_file='replacement.cil',sha256=m.sha((root/'replacement.cil').read_bytes()))])
        return root,plan
    def test_full_patch_preserves_metadata_links_xattrs_and_original(self):
        root,plan=self.fixture();report=m.build(root,plan)
        self.assertTrue(report['original_unchanged']);self.assertTrue(report['metadata_preserved'])
        self.assertEqual(report['entries_verified'],6)
        image=m.Image(root/'new.img',ROOT/'tools/image-tools/root/usr/bin')
        self.assertEqual(image.read('/etc/policy.cil'),(root/'replacement.cil').read_bytes())
        self.assertEqual(image.entry('/keep')['nid'],image.entry('/hardlink')['nid'])
        self.assertEqual(image.entry('/etc/policy.cil')['xattrs']['security.selinux'],m.base64.b64encode(b'u:object_r:system_file:s0').decode())
        self.assertEqual(image.read('/link'),b'etc/policy.cil')
        self.assertEqual(image.entry('/keep')['uid'],65536)
        self.assertEqual(m.base64.b64decode(image.entry('/keep')['xattrs']['security.capability']),b'\x01\x00\x00\x02\x80\xff\x00\x00\x00\x00')
    @unittest.skipUnless((ROOT/'tools/erofs-legacy/bin/mkfs.erofs').exists(),'Compatibility writer required')
    def test_legacy_writer_keeps_symlink_metadata_target_and_hardlinks(self):
        root,plan=self.fixture()
        (root/'tools/erofs-legacy').mkdir()
        (root/'tools/erofs-legacy/bin').symlink_to(ROOT/'tools/erofs-legacy/bin')
        before=m.Image(root/'base.img',ROOT/'tools/image-tools/root/usr/bin').entry('/link')
        report=m.build(root,plan,legacy_kernel_symlinks=True)
        image=m.Image(root/'new.img',ROOT/'tools/image-tools/root/usr/bin')
        after=image.entry('/link')
        self.assertEqual(after['layout'],0)
        self.assertEqual(image.read('/link'),b'etc/policy.cil')
        for key in ('mode','uid','gid','mtime','mtime_ns','nlink','xattrs'):
            self.assertEqual(before[key],after[key],key)
        self.assertEqual(image.entry('/keep')['nid'],image.entry('/hardlink')['nid'])
        self.assertEqual(report['legacy_symlink_issues'],[])

    def test_old_kernel_boundary_guard_distinguishes_inline_and_plain(self):
        row=dict(nid=127,mode=0o120777,layout=2,inode_offset=4064,inode_isize=32,xattr_isize=0,size=12)
        self.assertEqual(m.legacy_symlink_issues({'/link':row},4096)[0]['nid'],127)
        row['layout']=0
        self.assertEqual(m.legacy_symlink_issues({'/link':row},4096),[])
        row.update(layout=2,inode_offset=4032)
        self.assertEqual(m.legacy_symlink_issues({'/link':row},4096),[])
        row['xattr_isize']=24;row['size']=9
        self.assertEqual(len(m.legacy_symlink_issues({'/link':row},4096)),1)

    def test_generic_add_delete_plan_preserves_unmodified_files(self):
        root,old=self.fixture();replacement=root/'replacement.cil'
        plan=dict(schema_version=1,source_image='base.img',source_image_sha256=old['source_sha256'],output_image='new.img',operations=[
            dict(op='delete',path='/etc/policy.cil',old_sha256=old['patches'][0]['old_sha256']),
            dict(op='add',path='/etc/new.xml',source='replacement.cil',sha256=m.file_sha(replacement),metadata_from='/etc/policy.cil')])
        report=m.build(root,plan,root)
        self.assertEqual(report['deleted'],['/etc/policy.cil'])
        after=m.Image(root/'new.img',ROOT/'tools/image-tools/root/usr/bin').inventory()
        self.assertNotIn('/etc/policy.cil',after);self.assertIn('/etc/new.xml',after)
    def test_source_hash_mismatch_stops_before_output(self):
        root,plan=self.fixture();plan['source_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'Source image SHA'):m.build(root,plan)
        self.assertFalse((root/'new.img').exists())
    def test_changed_replacement_stops_before_output(self):
        root,plan=self.fixture();(root/'replacement.cil').write_bytes(b'CORRUPT')
        with self.assertRaisesRegex(ValueError,'Patch identity'):m.build(root,plan)
        self.assertFalse((root/'new.img').exists())
    def test_existing_output_preserved(self):
        root,plan=self.fixture();(root/'new.img').write_bytes(b'PRESERVE')
        with self.assertRaisesRegex(ValueError,'new regular'):m.build(root,plan)
        self.assertEqual((root/'new.img').read_bytes(),b'PRESERVE')
    def test_report_cannot_overwrite_source_image(self):
        root,plan=self.fixture();manifest=root/'plan.json';manifest.write_text(json.dumps(plan))
        result=subprocess.run([sys.executable,str(ROOT/'tools/rebuild_erofs_candidate.py'),
                               '--plan',str(manifest),'--project-root',str(root),'--report',str(root/'base.img')],capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(m.file_sha(root/'base.img'),plan['source_sha256'])
        self.assertFalse((root/'new.img').exists())

if __name__=='__main__':unittest.main(verbosity=2)
