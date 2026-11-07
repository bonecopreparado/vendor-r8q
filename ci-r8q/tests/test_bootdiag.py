"""Execute the temporary addon against bounded mock mounts, never devices."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,tempfile,unittest,zipfile
ROOT=Path(__file__).resolve().parents[2]
SHA=lambda b:hashlib.sha256(b).hexdigest()
SHELL=os.environ.get('MKSH_BINARY',shutil.which('mksh') or '/bin/bash')
WRAPPER=r"""#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
root=Path(os.environ['FIXTURE_ROOT']);name=Path(sys.argv[0]).name;args=sys.argv[1:]
flags=json.loads((root/'flags.json').read_text())
with (root/'events').open('a') as f:f.write(name+' '+json.dumps(args)+'\n')
if name=='getprop':print('wrong' if flags.get('device') else 'r8q')
elif name=='id':print('0')
elif name=='chown':pass
elif name=='ls':print('u:object_r:vendor_configs_file:s0 '+args[-1] if args[-1].endswith('.rc') else 'u:object_r:vendor_file:s0 '+args[-1])
elif name=='chcon':
 if flags.get('chcon'):sys.exit(1)
elif name=='mount':
 if flags.get('remount'):sys.exit(1)
 p=root/'proc/mounts';s=p.read_text()
 p.write_text(s.replace(' ro,',' rw,') if 'remount,rw' in args else s.replace(' rw,',' ro,'))
elif name=='mv':
 if flags.get('activate_rc') and args[-1].endswith('r8q-bootdiag.rc'):sys.exit(1)
 os.execv('/usr/bin/mv',['mv']+args)
else:sys.exit(2)
"""
class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t=tempfile.TemporaryDirectory();cls.out=Path(cls.t.name)
        subprocess.run(['python3',str(ROOT/'tools/package_bootdiag.py'),'--output',str(cls.out)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.t.cleanup()
    def fixture(self,flags=None,fs='ext4',mounted=True,dm='vendor',existing=None):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);root=Path(t.name)
        for d in ['vendor/etc/init/hw','vendor/bin','proc','sys/class/block/dm-vendor/dm','dev/block','tmp','bin']:
            (root/d).mkdir(parents=True,exist_ok=True)
        source=root/'dev/block/dm-vendor';source.write_text('mock logical device')
        (root/'sys/class/block/dm-vendor/dm/name').write_text(dm+'\n')
        reference=ROOT/'patches/0007-policy-integration/candidate/vendor/etc/init/hw/init.qcom.rc'
        (root/'vendor/etc/init/hw/init.qcom.rc').write_bytes(reference.read_bytes())
        (root/'vendor/bin/init.qti.qcv.sh').write_text('reference script')
        (root/'proc/mounts').write_text(f'{source} {root}/vendor {fs} ro,relatime 0 0\n' if mounted else '')
        (root/'flags.json').write_text(json.dumps(flags or {}))
        for name in ['getprop','id','chown','ls','chcon','mount','mv']:
            p=root/'bin'/name;p.write_text(WRAPPER);p.chmod(0o755)
        return root
    def execute(self,root,mode='ENABLE',corrupt=False):
        archive=self.out/('R8Q-BOOTDIAG-'+mode+'.zip')
        with zipfile.ZipFile(archive) as z:script=z.read('META-INF/com/google/android/update-binary').decode()
        for old in ['/sys/class/block','/proc/mounts','/vendor','/tmp/r8q-bootdiag']:
            script=script.replace(old,'@FIX@'+old)
        script=script.replace('@FIX@',str(root))
        expected=json.loads((ROOT/'tools/bootdiag/reference.json').read_text())['vendor_init_qcom_sha256']
        original=(ROOT/'patches/0007-policy-integration/candidate/vendor/etc/init/hw/init.qcom.rc').read_bytes()
        script=script.replace(expected,SHA(original))
        runner=root/'run.sh';runner.write_text(script)
        if corrupt:
            archive=root/'corrupt.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('payload/init.rc','damaged');z.writestr('payload/bootdiag.sh','damaged')
        p=subprocess.run([SHELL,str(runner),'3','1',str(archive)],capture_output=True,text=True,timeout=20,
            env=dict(os.environ,PATH=str(root/'bin')+':'+os.environ['PATH'],FIXTURE_ROOT=str(root)))
        return p
    def active(self,r):return [p for p in [r/'vendor/bin/r8q-bootdiag.sh',r/'vendor/etc/init/r8q-bootdiag.rc'] if p.exists()]
    def test_enable_remove_preserve_unrelated_files_and_original_mount_mode(self):
        root=self.fixture();reference=root/'vendor/etc/init/hw/init.qcom.rc';before=reference.read_bytes()
        p=self.execute(root);self.assertEqual(p.returncode,0,p.stderr+p.stdout)
        self.assertEqual(len(self.active(root)),2);self.assertEqual(reference.read_bytes(),before)
        self.assertIn(' ro,',(root/'proc/mounts').read_text())
        self.assertEqual((root/'vendor/bin/r8q-bootdiag.sh').stat().st_mode&0o777,0o755)
        events=(root/'events').read_text().splitlines()
        moves=[e for e in events if e.startswith('mv ')]
        self.assertTrue(moves[0].endswith('/r8q-bootdiag.sh"]'));self.assertTrue(moves[1].endswith('/r8q-bootdiag.rc"]'))
        p=self.execute(root,'REMOVE');self.assertEqual(p.returncode,0,p.stderr+p.stdout)
        self.assertEqual(self.active(root),[]);self.assertEqual(reference.read_bytes(),before)
        self.assertIn(' ro,',(root/'proc/mounts').read_text())
    def test_wrong_device_vendor_type_unmounted_or_wrong_logical_device_aborts(self):
        for kwargs in [dict(flags={'device':True}),dict(fs='erofs'),dict(mounted=False),dict(dm='system')]:
            with self.subTest(kwargs=kwargs):
                r=self.fixture(**kwargs);p=self.execute(r)
                self.assertNotEqual(p.returncode,0);self.assertEqual(self.active(r),[])
                events=(r/'events').read_text();self.assertNotIn('mount ',events)
    def test_vendor_reference_drift_aborts_before_writes(self):
        r=self.fixture();(r/'vendor/etc/init/hw/init.qcom.rc').write_text('other vendor')
        p=self.execute(r);self.assertNotEqual(p.returncode,0);self.assertEqual(self.active(r),[])
        self.assertNotIn('mount ',(r/'events').read_text())
    def test_corrupt_payload_aborts_before_remount(self):
        r=self.fixture();p=self.execute(r,corrupt=True)
        self.assertNotEqual(p.returncode,0);self.assertEqual(self.active(r),[])
        self.assertNotIn('mount ',(r/'events').read_text())
    def test_remount_or_label_failure_leaves_no_active_files(self):
        for flags in [{'remount':True},{'chcon':True}]:
            r=self.fixture(flags=flags);p=self.execute(r)
            self.assertNotEqual(p.returncode,0);self.assertEqual(self.active(r),[])
            self.assertIn(' ro,',(r/'proc/mounts').read_text())
    def test_failed_rc_activation_rolls_back_new_script(self):
        r=self.fixture(flags={'activate_rc':True});p=self.execute(r)
        self.assertNotEqual(p.returncode,0);self.assertEqual(self.active(r),[])
        self.assertIn(' ro,',(r/'proc/mounts').read_text())
    def test_unexpected_existing_file_and_symlink_are_not_overwritten(self):
        for symlink in [False,True]:
            r=self.fixture();p=r/'vendor/bin/r8q-bootdiag.sh'
            if symlink:p.symlink_to('missing')
            else:p.write_text('existing user file')
            result=self.execute(r);self.assertNotEqual(result.returncode,0)
            self.assertTrue(p.is_symlink() if symlink else p.read_text()=='existing user file')
            self.assertNotIn('mount ',(r/'events').read_text())
    def test_idempotent_enable_and_remove_refuses_altered_file(self):
        r=self.fixture();self.assertEqual(self.execute(r).returncode,0)
        before={p:p.read_bytes() for p in self.active(r)}
        self.assertEqual(self.execute(r).returncode,0)
        self.assertEqual(before,{p:p.read_bytes() for p in self.active(r)})
        altered=r/'vendor/etc/init/r8q-bootdiag.rc';altered.write_text('user changes')
        p=self.execute(r,'REMOVE');self.assertNotEqual(p.returncode,0)
        self.assertEqual(altered.read_text(),'user changes');self.assertEqual(len(self.active(r)),2)
    def test_packages_have_valid_crc_hash_and_no_partition_images(self):
        for mode in ['ENABLE','REMOVE']:
            p=self.out/('R8Q-BOOTDIAG-'+mode+'.zip')
            self.assertEqual(p.with_name(p.name+'.sha256').read_text().split()[0],SHA(p.read_bytes()))
            with zipfile.ZipFile(p) as z:
                self.assertIsNone(z.testzip());self.assertEqual(len(z.namelist()),6)
                self.assertFalse(any(n.endswith('.img') for n in z.namelist()))
    def test_logger_mirrors_filtered_userspace_without_kernel_feedback(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Path(temp);(r/'logdr').touch();(r/'kmsg').touch();(r/'bin').mkdir()
            logger=ROOT/'tools/bootdiag/bootdiag.sh'
            script=logger.read_text().replace('KMSG=/dev/kmsg','KMSG='+str(r/'kmsg')).replace('[ -c "$KMSG" ]','[ -f "$KMSG" ]')
            script=script.replace('/dev/socket/logdr',str(r/'logdr')).replace('[ ! -S ','[ ! -f ').replace('> "$KMSG"','>> "$KMSG"')
            fake=r/'bin/logcat';fake.write_text("#!/bin/sh\nprintf '%s\\n' 'I vold: waiting for key service' '[R8QBOOT] feedback must be skipped' 'E keystore2: test failure'\nprintf '%s\\n' \"$*\" > '"+str(r/'args')+"'\n");fake.chmod(0o755)
            timer=r/'bin/timeout';timer.write_text('#!/bin/sh\nshift\nexec \"$@\"\n');timer.chmod(0o755)
            script=script.replace('/system/bin/logcat',str(fake));p=r/'logger.sh';p.write_text(script)
            proc=subprocess.run([SHELL,str(p)],env=dict(os.environ,PATH=str(r/'bin')+':'+os.environ['PATH']),capture_output=True,text=True,timeout=10)
            self.assertEqual(proc.returncode,0,proc.stderr)
            data=(r/'kmsg').read_text();self.assertIn('I vold: waiting for key service',data);self.assertIn('E keystore2: test failure',data)
            self.assertNotIn('feedback must be skipped',data);self.assertIn('lines=2',data)
            args=(r/'args').read_text();self.assertNotIn('-b kernel',args);self.assertIn('-b main -b system -b crash',args)
if __name__=='__main__':unittest.main()
