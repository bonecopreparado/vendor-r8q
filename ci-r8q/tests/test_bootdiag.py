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
        archive=self.out/('R8Q-BOOTDIAG-V3-'+mode+'.zip')
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
            p=self.out/('R8Q-BOOTDIAG-V3-'+mode+'.zip')
            self.assertEqual(p.with_name(p.name+'.sha256').read_text().split()[0],SHA(p.read_bytes()))
            with zipfile.ZipFile(p) as z:
                self.assertIsNone(z.testzip());self.assertEqual(len(z.namelist()),6)
                self.assertFalse(any(n.endswith('.img') for n in z.namelist()))
    def logger_fixture(self,fs='ext4',options='rw,relatime',mounted=True,correct_device=True,free=20000,owner=0,lines=None):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);r=Path(t.name)
        for name in ['metadata','proc','dev','bin']:(r/name).mkdir()
        (r/'dev/metadata').touch();(r/'dev/wrong').touch();(r/'logdr').touch()
        source=r/('dev/metadata' if correct_device else 'dev/wrong')
        (r/'proc/mounts').write_text(f'{source} {r}/metadata {fs} {options} 0 0\n' if mounted else '')
        for pid,args in [('819',b'/system/bin/vdc\0cryptfs\0init_user0\0SECRET-ARGUMENT\0'),('820',b'/system/bin/vdc\0cryptfs\0checkpw\0PRIVATE-PASSWORD\0')]:
            d=r/'proc'/pid;d.mkdir()
            (d/'comm').write_text('vdc\n');(d/'cmdline').write_bytes(args)
            (d/'wchan').write_text('binder_thread_read\n');(d/'stack').write_text('[<0>] binder_thread_read\n')
        content=lines or ['I vold: waiting for key service','[R8QBOOT] feedback must be skipped','E keystore2: test failure']
        (r/'logcat-input').write_text('\n'.join(content)+'\n')
        mocks={
            'logcat':f'printf "%s\\n" "$*" > {r}/args\ncat {r}/logcat-input\n',
            'timeout':'shift\nexec "$@"\n','sleep':'exit 0\n',
            'df':f'printf "%s\\n" "Filesystem 1024-blocks Used Available Capacity Mounted" "fixture 24000 100 {free} 1% {r}/metadata"\n',
            'stat':f'printf "{owner}:%s\\n" "$(/usr/bin/stat -c %a "$3")"\n',
        }
        for name,body in mocks.items():
            p=r/'bin'/name;p.write_text('#!/bin/sh\n'+body);p.chmod(0o755)
        script=(ROOT/'tools/bootdiag/bootdiag.sh').read_text()
        # Bounded filesystem fixture: regular files stand in for block nodes.
        script=script.replace('[ -b "$actual" ]','[ -f "$actual" ]')
        # Replace absolute path tokens together, preserving replacements.
        import re
        paths={'/dev/block/platform/soc/1d84000.ufshc/by-name/metadata':str(r/'dev/metadata'),'/metadata':str(r/'metadata'),'/proc/':str(r/'proc')+'/', '/dev/socket/logdr':str(r/'logdr'),'/system/bin/logcat':str(r/'bin/logcat')}
        script=re.sub('|'.join(re.escape(p) for p in sorted(paths,key=len,reverse=True)),lambda m:paths[m.group()],script)
        script=script.replace('[ ! -S ','[ ! -f ')
        p=r/'logger.sh';p.write_text(script)
        return r
    def run_logger(self,r):
        return subprocess.run([SHELL,str(r/'logger.sh')],env=dict(os.environ,PATH=str(r/'bin')+':'+os.environ['PATH']),capture_output=True,text=True,timeout=30)
    def test_logger_persists_filtered_messages_and_redacted_snapshots_without_kmsg(self):
        r=self.logger_fixture();p=self.run_logger(r);self.assertEqual(p.returncode,0,p.stderr)
        logs=list((r/'metadata/r8q-bootdiag-v3').glob('capture.*/boot.log'));self.assertEqual(len(logs),1)
        data=logs[0].read_text();self.assertIn('I vold: waiting for key service',data);self.assertIn('E keystore2: test failure',data)
        self.assertNotIn('feedback must be skipped',data);self.assertIn('lines=2',data)
        self.assertIn('cmd=/system/bin/vdc cryptfs init_user0',data);self.assertIn('wchan=binder_thread_read',data)
        self.assertEqual(data.count('PROC snapshot begin'),2)
        self.assertNotIn('SECRET-ARGUMENT',data);self.assertNotIn('PRIVATE-PASSWORD',data)
        self.assertEqual(logs[0].stat().st_mode&0o777,0o600);self.assertEqual(logs[0].parent.stat().st_mode&0o777,0o700)
        args=(r/'args').read_text();self.assertNotIn('-b kernel',args);self.assertIn('-b main -b system -b crash',args)
    def test_runtime_rejects_unmounted_wrong_type_readonly_wrong_device_and_low_space(self):
        for opts in [dict(mounted=False),dict(fs='f2fs'),dict(options='ro,relatime'),dict(correct_device=False),dict(free=12287)]:
            with self.subTest(opts=opts):
                r=self.logger_fixture(**opts);key=r/'metadata/unchanged-key-fixture';key.write_text('untouched')
                p=self.run_logger(r);self.assertNotEqual(p.returncode,0)
                self.assertFalse((r/'metadata/r8q-bootdiag-v3').exists());self.assertEqual(key.read_text(),'untouched')
    def test_runtime_refuses_symlinked_or_insecure_base_and_capture_limit(self):
        for kind in ['symlink','mode','owner','unknown-entry','limit']:
            with self.subTest(kind=kind):
                r=self.logger_fixture(owner=1000 if kind=='owner' else 0);base=r/'metadata/r8q-bootdiag-v3'
                if kind=='symlink':base.symlink_to(r/'proc',target_is_directory=True)
                else:
                    base.mkdir(mode=0o700)
                    if kind=='mode':base.chmod(0o755)
                    if kind=='unknown-entry':(base/'unexpected').touch()
                    if kind=='limit':
                        for i in range(4):(base/f'capture.{i:06}').mkdir(mode=0o700)
                before=sorted(str(p) for p in r.rglob('*'));p=self.run_logger(r)
                self.assertNotEqual(p.returncode,0);self.assertEqual(before,sorted(str(p) for p in r.rglob('*')))
    def test_runtime_keeps_previous_capture_and_bounds_long_logcat_input(self):
        r=self.logger_fixture(lines=['E test: '+'x'*1200]*1502)
        self.assertEqual(self.run_logger(r).returncode,0)
        base=r/'metadata/r8q-bootdiag-v3';old=next(base.glob('capture.*/boot.log'));before=old.read_bytes()
        self.assertIn(b'lines=1500',before);self.assertLess(len(before),2*1024*1024)
        self.assertTrue(all(len(line)<=912 for line in before.splitlines()))
        self.assertEqual(self.run_logger(r).returncode,0);self.assertEqual(old.read_bytes(),before)
        self.assertEqual(len(list(base.glob('capture.*/boot.log'))),2)
    def test_previous_version_requires_removal_and_v3_remove_handles_it(self):
        r=self.fixture();old=ROOT/'tools/bootdiag/legacy-v1'
        rc=r/'vendor/etc/init/r8q-bootdiag.rc';sh=r/'vendor/bin/r8q-bootdiag.sh'
        rc.write_bytes((old/'init.rc').read_bytes());sh.write_bytes((old/'bootdiag.sh').read_bytes())
        previous={p:p.read_bytes() for p in [rc,sh]}
        p=self.execute(r);self.assertNotEqual(p.returncode,0)
        self.assertIn('Install V3 REMOVE',p.stdout);self.assertEqual(previous,{p:p.read_bytes() for p in [rc,sh]})
        self.assertEqual(self.execute(r,'REMOVE').returncode,0)
        self.assertEqual(self.active(r),[])
        self.assertEqual(self.execute(r).returncode,0)
        self.assertIn('on init\n',rc.read_text());self.assertNotIn('on property:',rc.read_text())

    def test_partial_v1_can_be_removed_without_touching_other_files(self):
        r=self.fixture();sh=r/'vendor/bin/r8q-bootdiag.sh'
        sh.write_bytes((ROOT/'tools/bootdiag/legacy-v1/bootdiag.sh').read_bytes())
        self.assertEqual(self.execute(r,'REMOVE').returncode,0);self.assertEqual(self.active(r),[])
        self.assertTrue((r/'vendor/bin/init.qti.qcv.sh').exists())

    def test_v2_upgrade_requires_remove_and_preserves_legacy_hash_guards(self):
        for partial in [False,True]:
            with self.subTest(partial=partial):
                r=self.fixture();old=ROOT/'tools/bootdiag/legacy-v2'
                sh=r/'vendor/bin/r8q-bootdiag.sh';sh.write_bytes((old/'bootdiag.sh').read_bytes())
                if not partial:(r/'vendor/etc/init/r8q-bootdiag.rc').write_bytes((old/'init.rc').read_bytes())
                self.assertNotEqual(self.execute(r).returncode,0)
                self.assertEqual(sh.read_bytes(),(old/'bootdiag.sh').read_bytes())
                self.assertEqual(self.execute(r,'REMOVE').returncode,0);self.assertEqual(self.active(r),[])
                self.assertEqual(self.execute(r).returncode,0)

    def test_documented_init_event_order_starts_capture_before_userdata_wait(self):
        # Bounded ordering model from AOSP init README; does not execute OEM init.
        def before_wait(text):
            trigger=None;actions={}
            for line in text.splitlines():
                if line.startswith('on '):trigger=line[3:];actions.setdefault(trigger,[])
                elif line.startswith('service '):trigger=None
                elif trigger and line.strip().startswith('start '):actions[trigger].append(line.strip())
            started=[]
            for event in ['early-init','init','late-init','userdata-wait','boot','property:init.svc.logd=running']:
                if event=='userdata-wait':break
                started.extend(actions.get(event,[]))
            return started
        old=(ROOT/'tools/bootdiag/legacy-v1/init.rc').read_text()
        new=(ROOT/'tools/bootdiag/init.rc').read_text()
        self.assertEqual(before_wait(old),[])
        self.assertEqual(before_wait(new),['start vendor.r8q_bootdiag'])

if __name__=='__main__':unittest.main()
