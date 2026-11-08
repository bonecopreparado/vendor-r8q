"""Execute the one-file upgrade in a regular-file fixture, never a phone."""
from pathlib import Path
import hashlib,os,subprocess,tempfile,unittest,zipfile
import test_bootdiag as legacy
from test_bootdiag import WRAPPER
ROOT=Path(__file__).resolve().parents[2]
SHELL=os.environ.get('MKSH_BINARY','/bin/bash')
SHA=lambda b:hashlib.sha256(b).hexdigest()
VENDOR_SHA='9971fef6dfa6951ec593bd82351203deb71e6185a4eea5354fe2fef3912114ea'
class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t=tempfile.TemporaryDirectory();cls.out=Path(cls.t.name)
        subprocess.run(['python3',str(ROOT/'tools/package_bootdiag_v4.py'),'--output',str(cls.out)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.t.cleanup()
    def fixture(self,**kwargs):
        r=legacy.Tests.fixture(self,**kwargs)
        for relative,source in [('vendor/etc/init/r8q-bootdiag.rc','tools/bootdiag/init.rc'),('vendor/bin/r8q-bootdiag.sh','tools/bootdiag/bootdiag.sh')]:
            (r/relative).write_bytes((ROOT/source).read_bytes())
        (r/'vendor/bin/r8q-bootdiag.sh').chmod(0o755)
        mock=WRAPPER.replace("flags.get('activate_rc') and args[-1].endswith('r8q-bootdiag.rc')","flags.get('activate_script') and args[-1].endswith('r8q-bootdiag.sh')")
        (r/'bin/mv').write_text(mock);(r/'bin/mv').chmod(0o755)
        return r
    def execute(self,r,restore=False,corrupt=False):
        mode='RESTORE-V3' if restore else 'ENABLE';archive=self.out/('R8Q-BOOTDIAG-V4-'+mode+'.zip')
        with zipfile.ZipFile(archive) as z:script=z.read('META-INF/com/google/android/update-binary').decode()
        original=(ROOT/'patches/0007-policy-integration/candidate/vendor/etc/init/hw/init.qcom.rc').read_bytes();script=script.replace(VENDOR_SHA,SHA(original))
        for old in ['/sys/class/block','/proc/mounts','/vendor','/tmp/r8q-bootdiag-v4']:script=script.replace(old,'@FIX@'+old)
        script=script.replace('@FIX@',str(r));p=r/'run.sh';p.write_text(script)
        if corrupt:
            archive=r/'bad.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('payload/runtime-v4.sh','damaged')
        return subprocess.run([SHELL,str(p),'3','1',str(archive)],env=dict(os.environ,PATH=str(r/'bin')+':'+os.environ['PATH'],FIXTURE_ROOT=str(r)),capture_output=True,text=True,timeout=20)
    def test_upgrade_idempotence_and_exact_v3_restoration_preserve_rc_and_vendor_mode(self):
        r=self.fixture();rc=r/'vendor/etc/init/r8q-bootdiag.rc';before=rc.read_bytes();ref=r/'vendor/etc/init/hw/init.qcom.rc';ref_before=ref.read_bytes()
        for _ in range(2):
            p=self.execute(r);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertEqual((r/'vendor/bin/r8q-bootdiag.sh').read_bytes(),(ROOT/'tools/bootdiag_v4/runtime.sh').read_bytes())
            self.assertEqual(rc.read_bytes(),before);self.assertEqual(ref.read_bytes(),ref_before);self.assertIn(' ro,',(r/'proc/mounts').read_text())
        self.assertEqual((r/'vendor/bin/r8q-bootdiag.sh').stat().st_mode&0o777,0o755)
        for _ in range(2):
            p=self.execute(r,restore=True);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertEqual((r/'vendor/bin/r8q-bootdiag.sh').read_bytes(),(ROOT/'tools/bootdiag/bootdiag.sh').read_bytes());self.assertEqual(rc.read_bytes(),before)
    def test_wrong_device_unmounted_wrong_type_or_logical_vendor_aborts_before_remount(self):
        for kwargs in [dict(flags={'device':True}),dict(mounted=False),dict(fs='erofs'),dict(dm='system')]:
            r=self.fixture(**kwargs);before=(r/'vendor/bin/r8q-bootdiag.sh').read_bytes();p=self.execute(r)
            self.assertNotEqual(p.returncode,0);self.assertEqual((r/'vendor/bin/r8q-bootdiag.sh').read_bytes(),before);self.assertNotIn('mount ',(r/'events').read_text())
    def test_unknown_script_or_rc_or_reference_is_preserved(self):
        for name in ['vendor/bin/r8q-bootdiag.sh','vendor/etc/init/r8q-bootdiag.rc','vendor/etc/init/hw/init.qcom.rc']:
            for restore in [False,True]:
                r=self.fixture();(r/name).write_text('user-file');p=self.execute(r,restore=restore)
                self.assertNotEqual(p.returncode,0);self.assertEqual((r/name).read_text(),'user-file');self.assertNotIn('mount ',(r/'events').read_text())
    def test_symlinked_script_is_not_followed(self):
        r=self.fixture();target=r/'vendor/bin/r8q-bootdiag.sh';outside=r/'original.sh';target.rename(outside);target.symlink_to(outside)
        p=self.execute(r);self.assertNotEqual(p.returncode,0);self.assertTrue(target.is_symlink());self.assertEqual(outside.read_bytes(),(ROOT/'tools/bootdiag/bootdiag.sh').read_bytes())
    def test_corrupt_archive_aborts_before_remount(self):
        r=self.fixture();p=self.execute(r,corrupt=True);self.assertNotEqual(p.returncode,0);self.assertNotIn('mount ',(r/'events').read_text())
    def test_remount_label_or_activation_failure_preserves_existing_script(self):
        for flags in [{'remount':True},{'chcon':True},{'activate_script':True}]:
            r=self.fixture(flags=flags);before=(r/'vendor/bin/r8q-bootdiag.sh').read_bytes();p=self.execute(r)
            self.assertNotEqual(p.returncode,0);self.assertEqual((r/'vendor/bin/r8q-bootdiag.sh').read_bytes(),before);self.assertEqual(list((r/'vendor/bin').glob('.r8q-bootdiag-v4.*')),[]);self.assertIn(' ro,',(r/'proc/mounts').read_text())
    def test_archive_crc_hash_and_no_partition_images(self):
        for mode in ['ENABLE','RESTORE-V3']:
            p=self.out/('R8Q-BOOTDIAG-V4-'+mode+'.zip');self.assertEqual(p.with_name(p.name+'.sha256').read_text().split()[0],SHA(p.read_bytes()))
            with zipfile.ZipFile(p) as z:self.assertIsNone(z.testzip());self.assertEqual(len(z.namelist()),6);self.assertFalse(any(n.endswith('.img') for n in z.namelist()))
if __name__=='__main__':unittest.main()
