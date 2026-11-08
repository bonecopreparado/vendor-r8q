"""Recovery installer fixtures use regular temporary files, never real devices."""
from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,tempfile,unittest,zipfile
ROOT=Path(__file__).resolve().parents[2]
SHA=lambda b:hashlib.sha256(b).hexdigest()
SHELL=os.environ.get('MKSH_BINARY',shutil.which('mksh') or '/bin/bash')
LEGACY_SHA='8debe752a74eb73382de872638462e6869f50041d75bba9f66aa89e2e2530f12'
VENDOR_SHA='9971fef6dfa6951ec593bd82351203deb71e6185a4eea5354fe2fef3912114ea'
MOCK=r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
r=Path(os.environ['FIXTURE_ROOT']);name=Path(sys.argv[0]).name;args=sys.argv[1:]
flags=json.loads((r/'flags.json').read_text())
with (r/'events').open('a') as f:f.write(name+' '+json.dumps(args)+'\n')
if name=='getprop':print('wrong' if flags.get('wrong_device') else 'r8q')
elif name=='id':print('0')
elif name=='ls':print('u:object_r:vendor_file:s0 '+args[-1])
elif name in ('chown','chcon'):
 if flags.get(name):sys.exit(1)
elif name=='mount':
 if flags.get('remount'):sys.exit(1)
 p=r/'proc/mounts';s=p.read_text()
 p.write_text(s.replace(' ro,',' rw,') if 'remount,rw' in args else s.replace(' rw,',' ro,'))
elif name=='mv':
 if flags.get('activate'):sys.exit(1)
 os.execv('/usr/bin/mv',['mv']+args)
'''
class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t=tempfile.TemporaryDirectory();cls.out=Path(cls.t.name)
        subprocess.run(['python3',str(ROOT/'tools/package_ueventd_compat.py'),'--output',str(cls.out)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.t.cleanup()
    def fixture(self,flags=None,system=True,imports=True,vendor_fs='ext4',system_fs='erofs',vendor_dm='vendor',system_dm='system'):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);r=Path(t.name)
        for p in ['vendor/etc/init/hw','system_root/system/etc','proc','bin','tmp','dev/block','sys/class/block/dm-vendor/dm','sys/class/block/dm-system/dm']:(r/p).mkdir(parents=True,exist_ok=True)
        for name,dm in [('vendor',vendor_dm),('system',system_dm)]:
            (r/f'dev/block/dm-{name}').touch();(r/f'sys/class/block/dm-{name}/dm/name').write_text(dm+'\n')
        (r/'vendor/ueventd.rc').write_text('/dev/qseecom 0660 system drmrpc\n/dev/ion 0664 system system\n/dev/spcom 0660 system system\n')
        (r/'vendor/etc/init/hw/init.qcom.rc').write_text('# reviewed vendor fixture\n')
        (r/'system_root/system/etc/ueventd.rc').write_text(f'import {r}/vendor/etc/ueventd.rc\n' if imports else '# canonical import missing\n')
        mounts=f'{r}/dev/block/dm-vendor {r}/vendor {vendor_fs} ro,relatime 0 0\n'
        if system:mounts+=f'{r}/dev/block/dm-system {r}/system_root {system_fs} ro,relatime 0 0\n'
        (r/'proc/mounts').write_text(mounts);(r/'flags.json').write_text(json.dumps(flags or {}))
        for name in ['getprop','id','ls','chown','chcon','mount','mv']:
            p=r/'bin'/name;p.write_text(MOCK);p.chmod(0o755)
        return r
    def execute(self,r,mode='ENABLE',corrupt=False):
        archive=self.out/('R8Q-UEVENTD-COMPAT-'+mode+'.zip')
        with zipfile.ZipFile(archive) as z:script=z.read('META-INF/com/google/android/update-binary').decode()
        script=script.replace(LEGACY_SHA,SHA(b'/dev/qseecom 0660 system drmrpc\n/dev/ion 0664 system system\n/dev/spcom 0660 system system\n'))
        script=script.replace(VENDOR_SHA,SHA(b'# reviewed vendor fixture\n'))
        paths=['/sys/class/block','/proc/mounts','/vendor','/system_root','/system','/tmp/r8q-ueventd']
        script=re.sub(r'(?<![A-Za-z0-9_./$])(?:'+'|'.join(re.escape(p) for p in sorted(paths,key=len,reverse=True))+')',lambda m:str(r)+m.group(),script)
        if corrupt:
            archive=r/'corrupt.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('payload/ueventd.rc','damaged')
        (r/'run.sh').write_text(script)
        return subprocess.run([SHELL,str(r/'run.sh'),'3','1',str(archive)],env=dict(os.environ,PATH=str(r/'bin')+':'+os.environ['PATH'],FIXTURE_ROOT=str(r)),capture_output=True,text=True,timeout=20)
    def test_enable_idempotence_remove_and_original_vendor_mount_mode(self):
        r=self.fixture();old=(r/'vendor/ueventd.rc').read_bytes();target=r/'vendor/etc/ueventd.rc'
        for _ in range(2):
            p=self.execute(r);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertEqual(target.read_bytes(),(ROOT/'tools/ueventd_compat/ueventd.rc').read_bytes())
            self.assertEqual(target.stat().st_mode&0o777,0o644);self.assertIn(' ro,',(r/'proc/mounts').read_text())
        self.assertEqual(self.execute(r,'REMOVE').returncode,0);self.assertFalse(target.exists())
        self.assertEqual((r/'vendor/ueventd.rc').read_bytes(),old)
        self.assertEqual(self.execute(r,'REMOVE').returncode,0)
    def test_wrong_device_mount_fs_logical_name_or_donor_import_aborts_before_remount(self):
        cases=[dict(flags={'wrong_device':True}),dict(system=False),dict(imports=False),dict(vendor_fs='erofs'),dict(system_fs='ext4'),dict(vendor_dm='system'),dict(system_dm='vendor')]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                r=self.fixture(**kwargs);p=self.execute(r);self.assertNotEqual(p.returncode,0)
                self.assertFalse((r/'vendor/etc/ueventd.rc').exists());self.assertNotIn('mount ',(r/'events').read_text())
    def test_original_rule_or_vendor_reference_drift_aborts_before_remount(self):
        for name in ['vendor/ueventd.rc','vendor/etc/init/hw/init.qcom.rc']:
            r=self.fixture();(r/name).write_text('modified');self.assertNotEqual(self.execute(r).returncode,0)
            self.assertNotIn('mount ',(r/'events').read_text())
    def test_unknown_or_symlinked_canonical_file_is_never_replaced_or_removed(self):
        for link in [False,True]:
            for mode in ['ENABLE','REMOVE']:
                r=self.fixture();p=r/'vendor/etc/ueventd.rc'
                if link:p.symlink_to('../ueventd.rc')
                else:p.write_text('foreign configuration')
                result=self.execute(r,mode);self.assertNotEqual(result.returncode,0)
                self.assertTrue(p.is_symlink() if link else p.read_text()=='foreign configuration')
                self.assertNotIn('mount ',(r/'events').read_text())
    def test_system_config_cannot_escape_its_mount_and_ambiguity_aborts(self):
        r=self.fixture();p=r/'system_root/system/etc/ueventd.rc';outside=r/'other.rc';outside.write_bytes(p.read_bytes());p.unlink();p.symlink_to(outside)
        self.assertNotEqual(self.execute(r).returncode,0)
        r=self.fixture();(r/'system_root/etc').mkdir();(r/'system_root/etc/ueventd.rc').write_text(f'import {r}/vendor/etc/ueventd.rc\n')
        self.assertNotEqual(self.execute(r).returncode,0);self.assertNotIn('mount ',(r/'events').read_text())
    def test_payload_corruption_aborts_before_writable_remount(self):
        r=self.fixture();self.assertNotEqual(self.execute(r,corrupt=True).returncode,0)
        self.assertNotIn('mount ',(r/'events').read_text())
    def test_remount_label_and_activation_failures_leave_no_new_bridge(self):
        for flag in ['remount','chcon','activate']:
            r=self.fixture(flags={flag:True});p=self.execute(r);self.assertNotEqual(p.returncode,0)
            self.assertFalse((r/'vendor/etc/ueventd.rc').exists());self.assertEqual(list((r/'vendor/etc').glob('.r8q-ueventd.*')),[])
            self.assertIn(' ro,',(r/'proc/mounts').read_text())
    def test_remove_needs_only_vendor_and_preserves_diagnostics_and_keys(self):
        r=self.fixture();self.assertEqual(self.execute(r).returncode,0)
        marker=r/'vendor/etc/init/diagnostic.rc';marker.write_text('keep')
        (r/'proc/mounts').write_text((r/'proc/mounts').read_text().splitlines()[0]+'\n')
        p=self.execute(r,'REMOVE');self.assertEqual(p.returncode,0,p.stderr+p.stdout);self.assertEqual(marker.read_text(),'keep')
    def test_packages_crc_digest_and_one_import_only(self):
        self.assertEqual((ROOT/'tools/ueventd_compat/ueventd.rc').read_text().splitlines()[-1],'import /vendor/ueventd.rc')
        for mode in ['ENABLE','REMOVE']:
            p=self.out/('R8Q-UEVENTD-COMPAT-'+mode+'.zip')
            self.assertEqual(p.with_name(p.name+'.sha256').read_text().split()[0],SHA(p.read_bytes()))
            with zipfile.ZipFile(p) as z:self.assertIsNone(z.testzip());self.assertEqual(len(z.namelist()),5)
    def test_real_baseline_pin_and_effective_node_permissions_under_legacy_and_modern_loading(self):
        # Bounded import-resolution model, not the OEM ueventd executable.
        archive=ROOT/'ci-r8q/vendor_audit/data/baseline-vendor.zip'
        if not archive.exists():self.skipTest('Tracked binary baseline is absent from this partial local workspace; required in full CI checkout')
        with zipfile.ZipFile(archive) as z:original=z.read('configs/ueventd.rc')
        self.assertEqual(SHA(original),LEGACY_SHA)
        expected={'/dev/qseecom':['0660','system','drmrpc'],'/dev/spcom':['0660','system','system'],'/dev/ion':['0664','system','system']}
        def effective(include_legacy):
            sources=[original] if include_legacy else []
            sources.append(original)  # canonical bridge resolves to the same original bytes
            result={}
            for text in sources:
                for line in text.decode().splitlines():
                    fields=line.split()
                    if len(fields)>=4 and fields[0] in expected:result[fields[0]]=fields[1:4]
            return result
        self.assertEqual(effective(True),expected);self.assertEqual(effective(False),expected)
if __name__=='__main__':unittest.main()
