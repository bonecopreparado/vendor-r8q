"""Exercise v4 against bounded regular-file fixtures, never phone partitions."""
from pathlib import Path
import json,os,re,shutil,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[2]
SHELL=os.environ.get('MKSH_BINARY',shutil.which('mksh') or '/bin/bash')
MOCK=r'''#!/usr/bin/env python3
from pathlib import Path
import json,os,sys
r=Path(os.environ['FIXTURE_ROOT']);flags=json.loads((r/'flags.json').read_text());name=Path(sys.argv[0]).name;args=sys.argv[1:]
with (r/'events').open('a') as f:f.write(name+' '+json.dumps(args)+'\n')
if name=='sleep':sys.exit(0)
if name=='timeout':os.execvp(args[1],args[1:])
if name=='sync':sys.exit(0)
if name=='df':
 print('Filesystem 1024-blocks Used Available Capacity Mounted');print('fixture 24000 100 '+str(flags.get('free',20000))+' 1% '+str(r/'metadata'))
elif name=='stat':
 print(str(flags.get('owner',0))+':'+oct(Path(args[-1]).stat().st_mode&0o777)[2:])
elif name=='lshal':
 if args[0]=='list':
  print('\n'.join(flags.get('services',['android.hardware.graphics.composer@2.1::IComposer/default','android.hardware.graphics.composer@2.4::IComposer/default'])))
  sys.exit(flags.get('list_status',0))
 elif args[0]=='debug':
  print('modeId=0 active=0 width=1080 height=2400 dpiX=400 dpiY=400 vsyncPeriod=16666666 configGroup=0')
  if flags.get('large'):print('x'*200000)
  sys.exit(flags.get('debug_status',0))
 else:sys.exit(4)
elif name=='service':print('Service '+args[-1]+': '+('found' if flags.get('aidl') else 'not found'))
elif name=='dumpsys':print('AIDL composer mode: 1080x2400, period=16666666')
elif name=='getprop':print('1'*512 if flags.get('large') else 'property-value')
elif name=='logcat':
 lines=['I SurfaceFlinger: mode probe','[R8QBOOT] feedback must not repeat','E IptablesRestoreController: NFLOG failure']
 if flags.get('large'):lines=['E SurfaceFlinger: '+'x'*1500]*1002
 for line in lines:print(line)
 sys.exit(flags.get('logcat_status',0))
else:sys.exit(3)
'''
class Tests(unittest.TestCase):
    def fixture(self,flags=None,fs='ext4',options='rw,relatime',mounted=True,correct_device=True,missing=()):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);r=Path(t.name);flags=flags or {}
        for d in ['metadata','proc/net','bin','system_ext/bin','dev','sys/class/graphics/fb0','sys/class/drm/card0-DSI-1']:(r/d).mkdir(parents=True)
        (r/'flags.json').write_text(json.dumps(flags));(r/'logdr').touch();(r/'dev/metadata').touch();(r/'dev/wrong').touch()
        source=r/('dev/metadata' if correct_device else 'dev/wrong')
        (r/'proc/mounts').write_text(f'{source} {r}/metadata {fs} {options} 0 0\n' if mounted else '')
        for name,data in [('config.gz',b'\x1f\x8bTEST-KERNEL-CONFIG'),('modules',b'fixture_module 4096 0 - Live\n'),('net/ip_tables_targets',b'NFLOG\nREJECT\n'),('net/ip6_tables_targets',b'NFLOG\nREJECT\n'),('version',b'Linux version fixture-android-kernel\n'),('uptime',b'20.00 19.00\n')]:
            (r/'proc'/name).write_bytes(data*(14000 if flags.get('large') else 1))
        for name in ['sys/class/graphics/fb0/modes','sys/class/graphics/fb0/mode','sys/class/drm/card0-DSI-1/modes','sys/class/drm/card0-DSI-1/status']:
            (r/name).write_text(('U:1080x2400p-60\n')*(200 if flags.get('large') else 1))
        for pid,comm,exe,cmdline in [('700','binder:700_1','vold',b'/system/bin/vold\0SECRET-VOLD-ARG\0'),('701','vdc','vdc',b'/system/bin/vdc\0cryptfs\0init_user0\0PRIVATE-ARG\0'),('702','vdc','vdc',b'/system/bin/vdc\0cryptfs\0checkpw\0PRIVATE-PASSWORD\0')]:
            d=r/'proc'/pid;d.mkdir();(d/'exe').symlink_to(str(r/'bin'/exe));(d/'comm').write_text(comm+'\n');(d/'cmdline').write_bytes(cmdline);(d/'wchan').write_text('binder_ioctl_write_read\n');(d/'stack').write_text('[<0>] binder_thread_read\n'*10)
        composer='/vendor/bin/hw/vendor.qti.hardware.display.composer-service'
        d=r/'proc/703';d.mkdir();(d/'exe').symlink_to(composer);(d/'comm').write_text('composer-svc\n');(d/'cmdline').write_bytes(composer.encode()+b'\0PRIVATE-COMPOSER-ARG\0');(d/'wchan').write_text('do_epoll_wait\n');(d/'stack').write_text('[<0>] do_epoll_wait\n')
        for name in ['sleep','timeout','sync','df','stat','lshal','service','dumpsys','getprop','logcat']:
            if name in missing:continue
            p=r/'bin'/name;p.write_text(MOCK);p.chmod(0o755)
        old=r/'metadata/r8q-bootdiag-v3/capture.OLD123';old.mkdir(parents=True);(old/'boot.log').write_text('old v3 evidence must stay untouched')
        (r/'metadata/untouched-key-fixture').write_text('not diagnostic input')
        script=(ROOT/'tools/bootdiag_v4/runtime.sh').read_text().replace('SH=/system/bin/sh','SH='+SHELL)
        # Regular files stand in for physical block nodes in this fixture only.
        script=script.replace('[ -b "$actual" ]','[ -f "$actual" ]')
        paths={'/dev/block/platform/soc/1d84000.ufshc/by-name/metadata':str(r/'dev/metadata'),'/metadata':str(r/'metadata'),'/proc/':str(r/'proc')+'/', '/sys/':str(r/'sys')+'/', '/dev/socket/logdr':str(r/'logdr'),'/system/bin/':str(r/'bin')+'/', '/system_ext/bin/':str(r/'system_ext/bin')+'/'}
        script=re.sub('|'.join(re.escape(p) for p in sorted(paths,key=len,reverse=True)),lambda m:paths[m.group()],script)
        script=script.replace('[ ! -S ','[ ! -f ').replace('[ -S ','[ -f ')
        (r/'run.sh').write_text(script)
        return r
    def execute(self,r):
        return subprocess.run([SHELL,str(r/'run.sh')],env=dict(os.environ,PATH=str(r/'bin')+':'+os.environ['PATH'],FIXTURE_ROOT=str(r)),capture_output=True,text=True,timeout=30)
    def capture_dir(self,r):
        files=list((r/'metadata/r8q-bootdiag-v4').glob('capture.*'));self.assertEqual(len(files),1);return files[0]
    def text_outputs(self,c):
        return '\n'.join(p.read_text(errors='replace') for p in c.iterdir() if p.is_file() and p.name!='kernel-config.gz')
    def test_hwc_highest_whitelisted_service_early_rounds_and_selected_properties(self):
        r=self.fixture();p=self.execute(r);self.assertEqual(p.returncode,0,p.stderr);c=self.capture_dir(r)
        for suffix in ['early','later']:
            self.assertEqual((c/f'composer-{suffix}.selected').read_text().strip(),'android.hardware.graphics.composer@2.4::IComposer/default')
            self.assertIn('vsyncPeriod=16666666',(c/f'composer-{suffix}.txt').read_text())
            self.assertIn('producer_status=0',(c/f'composer-{suffix}.txt.status').read_text())
        calls=(r/'events').read_text();self.assertIn('sleep ["8"]',calls);self.assertIn('sleep ["20"]',calls)
        self.assertNotIn('"-E"',calls);self.assertNotIn('setprop',calls)
        self.assertTrue((c/'property-ro.surface_flinger.enable_frame_rate_override.txt').is_file())
        self.assertTrue((c/'COMPLETE.txt').is_file())
    def test_snapshot_finds_renamed_vold_by_executable_and_redacts_arguments(self):
        r=self.fixture();self.assertEqual(self.execute(r).returncode,0);c=self.capture_dir(r)
        for name in ['processes-20.txt','processes-60.txt']:
            text=(c/name).read_text();self.assertIn('name=binder:700_1',text);self.assertIn('vold',text)
            self.assertIn('cryptfs init_user0',text);self.assertIn('binder_ioctl_write_read',text)
            self.assertIn('/vendor/bin/hw/vendor.qti.hardware.display.composer-service',text);self.assertNotIn('PRIVATE-COMPOSER-ARG',text)
            self.assertNotIn('PRIVATE-PASSWORD',text);self.assertNotIn('PRIVATE-ARG',text);self.assertNotIn('SECRET-VOLD-ARG',text)
        calls=(r/'events').read_text();self.assertIn('DEBUG:F',calls);self.assertIn('libc:F',calls);self.assertIn('*:S',calls);self.assertNotIn('*:W',calls);self.assertNotIn('"kernel"',calls)
    def test_kernel_and_fixed_sysfs_inputs_are_bounded_and_old_logs_untouched(self):
        r=self.fixture();old=r/'metadata/r8q-bootdiag-v3/capture.OLD123/boot.log';before=old.read_bytes()
        self.assertEqual(self.execute(r).returncode,0);c=self.capture_dir(r)
        self.assertEqual((c/'kernel-config.gz').read_bytes(),(r/'proc/config.gz').read_bytes())
        self.assertIn('NFLOG',(c/'ip6-tables-targets.txt').read_text());self.assertIn('fixture-android-kernel',(c/'kernel-version.txt').read_text())
        self.assertEqual(old.read_bytes(),before);self.assertEqual((r/'metadata/untouched-key-fixture').read_text(),'not diagnostic input')
        self.assertNotIn('not diagnostic input',self.text_outputs(c))
        self.assertTrue(all(p.stat().st_mode&0o777==0o600 for p in c.iterdir() if p.is_file()));self.assertEqual(c.stat().st_mode&0o777,0o700)
    def test_wrong_metadata_mount_or_low_space_aborts_without_new_namespace(self):
        for opts in [dict(mounted=False),dict(fs='f2fs'),dict(options='ro,relatime'),dict(correct_device=False),dict(flags={'free':12287})]:
            with self.subTest(opts=opts):
                r=self.fixture(**opts);p=self.execute(r);self.assertNotEqual(p.returncode,0);self.assertFalse((r/'metadata/r8q-bootdiag-v4').exists())
    def test_retention_three_new_captures_preserve_v3_and_previous_v4(self):
        r=self.fixture();base=r/'metadata/r8q-bootdiag-v4';previous={}
        for _ in range(3):
            p=self.execute(r);self.assertEqual(p.returncode,0,p.stderr)
            for path,data in previous.items():self.assertEqual(path.read_bytes(),data)
            previous={p:p.read_bytes() for p in base.glob('capture.*/boot.log')}
        p=self.execute(r);self.assertNotEqual(p.returncode,0);self.assertIn('capture limit reached',p.stderr);self.assertEqual(len(list(base.iterdir())),3)
        self.assertTrue((r/'metadata/r8q-bootdiag-v3/capture.OLD123/boot.log').exists())
    def test_symlink_insecure_owner_and_unknown_namespace_entries_are_refused(self):
        for kind in ['symlink','mode','owner','entry']:
            r=self.fixture(flags={'owner':1000} if kind=='owner' else {});base=r/'metadata/r8q-bootdiag-v4'
            if kind=='symlink':base.symlink_to(r/'proc',target_is_directory=True)
            else:
                base.mkdir(mode=0o700)
                if kind=='mode':base.chmod(0o755)
                if kind=='entry':(base/'unknown').touch()
            p=self.execute(r);self.assertNotEqual(p.returncode,0);self.assertEqual(len(list(base.glob('capture.*'))),0)
    def test_producer_failure_is_not_hidden_by_successful_output_reader(self):
        r=self.fixture(flags={'list_status':13,'debug_status':124,'logcat_status':7});p=self.execute(r);self.assertEqual(p.returncode,0,p.stderr);c=self.capture_dir(r)
        self.assertIn('producer_status=13',(c/'lshal-early.txt.status').read_text());self.assertIn('reader_status=0',(c/'lshal-early.txt.status').read_text())
        self.assertIn('producer_status=124',(c/'composer-early.txt.status').read_text());self.assertIn('producer_status=7',(c/'boot.log.status').read_text())
    def test_missing_optional_tools_and_sources_leave_explicit_status(self):
        r=self.fixture(missing=['lshal','service','dumpsys','getprop','logcat']);(r/'proc/config.gz').unlink()
        p=self.execute(r);self.assertEqual(p.returncode,0,p.stderr);c=self.capture_dir(r)
        self.assertIn('unavailable',(c/'lshal-early.txt.status').read_text());self.assertIn('no-whitelisted-service',(c/'composer-early.txt.status').read_text());self.assertIn('unavailable',(c/'properties.status').read_text())
        self.assertIn('missing-or-unreadable',(c/'kernel-config.gz.status').read_text());self.assertIn('independent probes retained',(c/'boot.log.status').read_text())
        self.assertTrue((c/'processes-20.txt').exists())
    def test_missing_logdr_socket_does_not_cancel_composer_and_process_probes(self):
        r=self.fixture();(r/'logdr').unlink();p=self.execute(r);self.assertEqual(p.returncode,0,p.stderr);c=self.capture_dir(r)
        self.assertIn('independent probes retained',(c/'boot.log.status').read_text())
        self.assertIn('vsyncPeriod=16666666',(c/'composer-early.txt').read_text());self.assertTrue((c/'processes-20.txt').is_file())
    def test_untrusted_list_cannot_select_arbitrary_interface_or_shell_command(self):
        services=['android.hardware.graphics.composer@2.4::IComposer/default; touch /tmp/injected','vendor.evil@1.0::IThing/default','android.hardware.graphics.composer@2.2::IComposer/default']
        r=self.fixture(flags={'services':services});self.assertEqual(self.execute(r).returncode,0);c=self.capture_dir(r)
        self.assertEqual((c/'composer-early.selected').read_text().strip(),'android.hardware.graphics.composer@2.2::IComposer/default')
        debug=[json.loads(l.partition(' ')[2]) for l in (r/'events').read_text().splitlines() if l.startswith('lshal ') and '"debug"' in l]
        self.assertTrue(all(a==['debug','android.hardware.graphics.composer@2.2::IComposer/default'] for a in debug))
    def test_named_aidl_fallback_without_broad_dumpsys(self):
        r=self.fixture(flags={'services':[],'aidl':True});self.assertEqual(self.execute(r).returncode,0);c=self.capture_dir(r)
        self.assertEqual((c/'composer-early.selected').read_text().strip(),'android.hardware.graphics.composer3.IComposer/default')
        calls=[json.loads(l.partition(' ')[2]) for l in (r/'events').read_text().splitlines() if l.startswith('dumpsys ')]
        self.assertEqual(len(calls),2);self.assertTrue(all(a==['-t','3','android.hardware.graphics.composer3.IComposer/default'] for a in calls))
    def test_worst_case_payload_remains_below_aggregate_two_mib(self):
        r=self.fixture(flags={'large':True});p=self.execute(r);self.assertEqual(p.returncode,0,p.stderr);c=self.capture_dir(r)
        total=sum(p.stat().st_size for p in c.iterdir() if p.is_file());self.assertLess(total,2*1024*1024)
        self.assertEqual((c/'kernel-config.gz').stat().st_size,131072);self.assertEqual((c/'kernel-modules.txt').stat().st_size,32768)
        self.assertEqual((c/'composer-early.txt').stat().st_size,131072);self.assertEqual((c/'boot.log.lines').read_text().strip(),'1000')
        self.assertTrue(all(len(line)<=911 for line in (c/'boot.log').read_bytes().splitlines()))
if __name__=='__main__':unittest.main()
