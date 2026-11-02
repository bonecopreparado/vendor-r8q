"""Bounded native ZIP64 and package tests; no devices or physical writes."""
from pathlib import Path
import gzip,hashlib,importlib.util,json,os,shutil,struct,subprocess,sys,tempfile,unittest,warnings,zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import package_p1_single as package

@unittest.skipUnless(shutil.which('cc'),'Host C compiler required')
class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='r8q-single-');cls.root=Path(cls.temp.name)
        cls.helper=cls.root/'reader'
        subprocess.run(['cc','-D_FILE_OFFSET_BITS=64','-Os','-Wall','-Wextra','-Werror',str(ROOT/'tools/single_zip_helper.c'),'-o',str(cls.helper)],check=True)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.work=tempfile.TemporaryDirectory(prefix='r8q-zip-case-');self.addCleanup(self.work.cleanup);self.folder=Path(self.work.name)
    def archive(self,prefix=0,method=zipfile.ZIP_STORED):
        path=self.folder/'source.zip'
        if prefix:
            with path.open('wb') as f:f.truncate(prefix)
        data=gzip.compress(b'R8Q fixture bytes'*200,mtime=0)
        with zipfile.ZipFile(path,'a' if prefix else 'w',allowZip64=True,compression=method) as z:
            info=zipfile.ZipInfo('payloads/super-000.gz');info.compress_type=method
            with z.open(info,'w',force_zip64=True) as out:out.write(data)
        return path,data
    def read(self,path,*extra):return subprocess.run([str(self.helper),*extra,str(path),'payloads/super-000.gz'],capture_output=True)
    def test_stored_member_size_and_crc_stream(self):
        p,data=self.archive();r=self.read(p);self.assertEqual((r.returncode,r.stdout),(0,data))
        self.assertEqual(self.read(p,'--size').stdout.strip(),str(len(data)).encode())
    def test_real_zip64_central_and_local_offsets_above_four_gib(self):
        p,data=self.archive(prefix=5*1024**3+4096)
        self.assertLess(p.stat().st_blocks*512,1024**2)
        self.assertEqual(self.read(p).stdout,data);self.assertEqual(self.read(p).returncode,0)
    def test_resolved_zip64_local_offset_exactly_uint32_max_is_valid(self):
        p,data=self.archive(prefix=2**32-1)
        self.assertLess(p.stat().st_blocks*512,1024**2)
        with zipfile.ZipFile(p) as archive:
            self.assertEqual(archive.getinfo('payloads/super-000.gz').header_offset,2**32-1)
        self.assertEqual(self.read(p).stdout,data)
        self.assertEqual(self.read(p).returncode,0)
    def test_payload_corruption_is_a_native_crc_failure(self):
        p,data=self.archive()
        with zipfile.ZipFile(p) as z:offset=z.getinfo('payloads/super-000.gz').header_offset
        with p.open('r+b') as f:
            f.seek(offset);h=f.read(30);start=offset+30+struct.unpack_from('<H',h,26)[0]+struct.unpack_from('<H',h,28)[0]
            f.seek(start+len(data)//2);b=f.read(1);f.seek(start+len(data)//2);f.write(bytes([b[0]^1]))
        r=self.read(p);self.assertNotEqual(r.returncode,0);self.assertIn(b'CRC32 mismatch',r.stderr)
    def test_local_central_crc_mismatch_stops_before_output(self):
        p,_=self.archive()
        with p.open('r+b') as f:f.seek(14);b=f.read(1);f.seek(14);f.write(bytes([b[0]^1]))
        r=self.read(p);self.assertNotEqual(r.returncode,0);self.assertEqual(r.stdout,b'')
    def test_compressed_outer_member_is_rejected(self):
        p,_=self.archive(method=zipfile.ZIP_DEFLATED);self.assertNotEqual(self.read(p).returncode,0)
    def test_duplicate_member_is_rejected(self):
        p,data=self.archive()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(p,'a') as z:z.writestr('payloads/super-000.gz',data)
        self.assertNotEqual(self.read(p).returncode,0)
    def test_missing_and_truncated_archive_rejected(self):
        p,_=self.archive()
        r=subprocess.run([str(self.helper),str(p),'payloads/missing.gz'],capture_output=True);self.assertNotEqual(r.returncode,0)
        with p.open('r+b') as f:f.truncate(20)
        self.assertNotEqual(self.read(p).returncode,0)
    def test_traversal_or_arbitrary_member_not_allowed(self):
        p,_=self.archive()
        for name in ('../outside','tools/helper','payloads/../super.gz','payloads/sub/name.gz'):
            r=subprocess.run([str(self.helper),str(p),name],capture_output=True);self.assertNotEqual(r.returncode,0)
    def test_symlink_zip_source_is_read_as_regular_open_file(self):
        # The shell canonicalizes source/mounts before invocation; helper still
        # fstats the opened file. No extraction uses archive-controlled paths.
        p,data=self.archive();link=self.folder/'alias.zip';link.symlink_to(p)
        self.assertEqual(self.read(link).stdout,data)
    def test_one_zip_package_bootstrap_and_native_end_to_end(self):
        images=[]
        for part,length in [('super',32768),('boot',8192),('dtbo',4096)]:
            data=(part.encode()*length)[:length];path=self.folder/(part+'.img');path.write_bytes(data)
            images.append(dict(partition=part,file=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        output=self.folder/'candidate.zip'
        report=package.build(output,self.helper,images,require_arm64=False,host_helper=self.helper)
        self.assertFalse(report['external_payloads_required']);self.assertTrue(report['native_host_readback']);self.assertEqual(report['payload_chunks'],3)
        self.assertEqual(output.with_suffix('.zip.sha256').read_text().split()[0],hashlib.sha256(output.read_bytes()).hexdigest())
        with zipfile.ZipFile(output) as z:
            script=z.read(package.INSTALLER).decode();manifest=json.loads(z.read('P1-MANIFEST.json'))
            self.assertNotIn('@@',script);self.assertNotIn('PAYLOAD_DIR',script)
            self.assertIn('check_battery before-write',script);self.assertIn('verify_written super',script)
            self.assertEqual(z.getinfo(package.INSTALLER).external_attr>>16,0o100755)
            self.assertEqual(manifest['helper']['data_offset'],4096)
            self.assertFalse(manifest['boot_confirmed'])
        self.assertNotEqual(package.helper_blob(self.helper,False),b'')
        with self.assertRaisesRegex(ValueError,'AArch64'):package.helper_blob(self.helper,True)
    def test_changed_source_hash_does_not_publish_checksum(self):
        path=self.folder/'super.img';path.write_bytes(b'X'*8192)
        images=[dict(partition='super',file=str(path),bytes=8192,sha256='0'*64)]
        output=self.folder/'bad.zip'
        with self.assertRaisesRegex(ValueError,'Source image SHA256'):package.build(output,self.helper,images,require_arm64=False)
        self.assertFalse(output.with_suffix('.zip.sha256').exists());self.assertFalse(output.exists())
    def test_mapping_variant_archive_instructions_and_guards_match_manifest(self):
        images=[]
        for part,length in [('super',32768),('boot',8192),('dtbo',4096)]:
            data=(part.encode()*length)[:length];path=self.folder/(part+'.img');path.write_bytes(data)
            images.append(dict(partition=part,file=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        omitted=[dict(partition=p,path='/etc/selinux/mapping/30.0.cil',old_sha256='a'*64)for p in ('system_ext','product')]
        output=self.folder/'HyperOS4-R8Q-P1r1-SINGLE-EXPERIMENTAL.zip'
        report=package.build(output,self.helper,images,require_arm64=False,host_helper=self.helper,build_label='P1r1',omitted_optional_mappings=omitted)
        self.assertEqual(report['build_label'],'P1r1');self.assertEqual(report['omitted_optional_mappings'],omitted)
        with zipfile.ZipFile(output) as z:
            script=z.read(package.INSTALLER).decode();manifest=json.loads(z.read('P1-MANIFEST.json'));notes=z.read('README-TESTER.txt').decode()
            self.assertEqual(manifest['build_label'],'P1r1');self.assertFalse(manifest['boot_confirmed'])
            self.assertIn(output.name,notes);self.assertIn('System/platform mappings',notes)
            self.assertIn('P1r1 SINGLE ZIP EXPERIMENTAL',script)
            self.assertIn('system_ext/product SELinux mappings omitted',script)
            for guard in ('check_battery before-write','verify_written super','Conferindo o vbmeta'):
                self.assertIn(guard,script)

class VariantMetadataTests(unittest.TestCase):
    def test_variant_rejects_platform_removal_or_missing_partition_evidence(self):
        rows=[dict(partition=p,path='/etc/selinux/mapping/30.0.cil',old_sha256='a'*64)for p in ('system_ext','product')]
        self.assertEqual(package.variant_metadata({'build_label':'P1r1','omitted_optional_mappings':rows})[0],'P1r1')
        for invalid in ([],rows[:1],[dict(rows[0],partition='system'),rows[1]],[dict(rows[0],path='/etc/selinux/mapping/..'),rows[1]]):
            with self.assertRaises(ValueError):package.variant_metadata({'build_label':'P1r1','omitted_optional_mappings':invalid})

if __name__=='__main__':unittest.main()
