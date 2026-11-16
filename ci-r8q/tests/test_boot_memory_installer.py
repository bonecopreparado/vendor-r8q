"""Run the actual recovery shell template against private regular-file fixtures."""
from pathlib import Path
import gzip
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('memory_package',ROOT/'tools/package_boot_memory.py')
package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)
BOOT_BYTES=67108864
SHELL=os.environ.get('MKSH_BINARY',shutil.which('bash'))


def sha(data):return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


class Tests(unittest.TestCase):
    def fixture(self,flags=None):
        temp=tempfile.TemporaryDirectory(prefix='r8q-memory-shell-');self.addCleanup(temp.cleanup)
        r=Path(temp.name)
        for p in ('bin','dev','data','tmp','battery'):(r/p).mkdir()
        (r/'flags').write_text(json.dumps(flags or {}))
        (r/'battery/capacity').write_text('80\n');(r/'battery/status').write_text('Discharging\n')
        (r/'dev/userdata').write_bytes(b'filesystem-fixture')
        with (r/'dev/boot').open('wb')as stream:
            for _ in range(64):stream.write(b'O'*1048576)
        (r/'dev/bootlink').symlink_to(r/'dev/boot')
        (r/'proc-mounts').write_text(str(r/'dev/userdata')+' '+str(r/'data')+' f2fs rw,relatime 0 0\n')
        original=file_sha(r/'dev/boot');candidate=sha(b'N'*BOOT_BYTES)
        fixed={'root':str(r),'flags':str(r/'flags'),'events':str(r/'events')}
        prelude='#!/usr/bin/env python3\nimport sys,os,json,shutil\nfrom pathlib import Path\ncfg='+repr(fixed)+'\nflags=json.loads(Path(cfg["flags"]).read_text())\n'
        helper=(prelude+'''
op=sys.argv[1]
with open(cfg['events'],'a')as f:f.write('helper '+op+'\\n')
if op=='--version':print('R8Q_BOOTIO_PRODUCTION_BLOCK_ONLY_V1');sys.exit(0)
if op=='--check':sys.exit(0 if Path(sys.argv[2]).stat().st_size==67108864 else 1)
if op=='--sync-file':sys.exit(1 if flags.get('backup_flush_error') else 0)
if op=='--sync-directory':sys.exit(0)
if op=='--read':
    data=Path(sys.argv[2]).read_bytes()
    marker=Path(cfg['root'])/'readback-failed'
    if flags.get('readback_error') and data[:1]==b'N' and not marker.exists():
        marker.write_text('injected once');sys.stdout.buffer.write(b'corrupt');sys.exit(0)
    sys.stdout.buffer.write(data);sys.exit(0)
if op=='--write':
    data=Path(sys.argv[2]).read_bytes()
    with open(cfg['events'],'a')as f:f.write('write '+('candidate' if data[:1]==b'N' else 'restore')+'\\n')
    with open(sys.argv[3],'r+b')as f:
        if flags.get('write_error') and data[:1]==b'N':f.write(data[:1024]);sys.exit(1)
        f.write(data)
    sys.exit(0)
sys.exit(1)
''').encode()
        security=('''#!/bin/sh
printf 'security-r2\\n' >> '''+str(r/'events')+'''
'''+('exit 1\n' if (flags or {}).get('r2_error') else 'exit 0\n')).encode()
        compressed=gzip.compress(b'N'*BOOT_BYTES,mtime=0)
        with zipfile.ZipFile(r/'fixture.zip','w')as z:
            z.writestr('tools/bootio',helper);z.writestr('scripts/security-r2.sh',security)
            z.writestr('images/boot.img.gz',compressed)
        script=package.render(candidate,sha(compressed),sha(helper),sha(security)).decode()
        script=script.replace('ORIGINAL='+package.ORIGINAL,'ORIGINAL='+original)
        script=script.replace('[ -b "$BOOT" ]','[ -f "$BOOT" ]').replace('[ -b "$DATA_DEVICE" ]','[ -f "$DATA_DEVICE" ]')
        paths={'/dev/block/bootdevice/by-name/boot':str(r/'dev/bootlink'),'/proc/mounts':str(r/'proc-mounts'),
               '/sys/class/power_supply/battery/':str(r/'battery')+'/', '/data':str(r/'data'),'/tmp':str(r/'tmp')}
        script=re.sub('|'.join(re.escape(p)for p in sorted(paths,key=len,reverse=True)),lambda m:paths[m.group()],script)
        (r/'run.sh').write_text(script)
        stat=shutil.which('stat')
        wrappers={
          'id':"#!/bin/sh\nprintf '0\\n'\n",
          'getprop':prelude+"p={'ro.product.device':'r8q','ro.bootloader':'G781BXXSIHYJ2','ro.bootmode':'recovery'}\nprint(p.get(sys.argv[1],''))\n",
          'df':"#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\nfixture 2097152 0 1048576 0%% /fixture\\n'\n",
          'stat':prelude+"import subprocess\nfmt=sys.argv[2];p=Path(sys.argv[3])\nif fmt=='%d': print('20' if p==Path(cfg['root'])/'data' else '10');sys.exit(0)\ns=subprocess.check_output(["+repr(stat)+",*sys.argv[1:]],text=True).strip()\nif fmt.startswith('%u:'): s='0:'+s.split(':',1)[1]\nprint(s)\n"}
        for name,body in wrappers.items():(r/'bin'/name).write_text(body);(r/'bin'/name).chmod(0o755)
        return r,original,candidate

    def run_script(self,r):
        env=dict(os.environ,PATH=str(r/'bin')+os.pathsep+os.environ['PATH'])
        return subprocess.run([SHELL,str(r/'run.sh'),'3','1',str(r/'fixture.zip')],env=env,capture_output=True,text=True,timeout=45)

    def events(self,r):return (r/'events').read_text()if(r/'events').exists()else ''

    def backup(self,r,original):return r/'data/r8q-boot-backups'/('P1r4-'+original+'.img')

    def test_success_and_idempotence_preserve_original_before_vendor_and_boot(self):
        r,original,candidate=self.fixture();result=self.run_script(r)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('R8Q memory R3 applied',result.stdout)
        self.assertEqual(file_sha(r/'dev/boot'),candidate)
        self.assertEqual(file_sha(self.backup(r,original)),original)
        events=self.events(r);self.assertLess(events.index('helper --sync-file'),events.index('security-r2'))
        self.assertLess(events.index('security-r2'),events.index('write candidate'))
        result=self.run_script(r);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(self.events(r).count('write candidate'),1)
        self.assertEqual(file_sha(self.backup(r,original)),original)
        self.assertEqual(list((r/'tmp').iterdir()),[])

    def test_low_battery_readonly_or_ram_data_aborts_without_vendor_or_boot_write(self):
        for kind in ('battery','ro','ram'):
            with self.subTest(kind=kind):
                r,original,_=self.fixture()
                if kind=='battery':(r/'battery/capacity').write_text('49\n')
                else:
                    text=(r/'proc-mounts').read_text().replace(' rw,',' ro,')if kind=='ro'else (r/'proc-mounts').read_text().replace(' f2fs ',' tmpfs ')
                    (r/'proc-mounts').write_text(text)
                result=self.run_script(r);self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertNotIn('security-r2',self.events(r));self.assertNotIn('write candidate',self.events(r))
                self.assertEqual(file_sha(r/'dev/boot'),original)

    def test_unknown_installed_boot_is_not_backed_up_or_replaced(self):
        r,_,_=self.fixture()
        with (r/'dev/boot').open('r+b')as f:f.write(b'unknown')
        before=file_sha(r/'dev/boot');result=self.run_script(r)
        self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertEqual(file_sha(r/'dev/boot'),before)
        self.assertFalse((r/'data/r8q-boot-backups').exists());self.assertNotIn('security-r2',self.events(r))

    def test_bad_existing_backup_and_symlink_are_preserved_without_writes(self):
        for kind in ('hash','symlink','hardlink'):
            with self.subTest(kind=kind):
                r,original,_=self.fixture();p=self.backup(r,original);p.parent.mkdir(mode=0o700)
                if kind=='symlink':p.symlink_to(r/'dev/boot')
                else:
                    shutil.copyfile(r/'dev/boot',p);p.chmod(0o600)
                    if kind=='hash':
                        with p.open('r+b')as f:f.write(b'bad')
                    else:os.link(p,r/'hardlink')
                result=self.run_script(r);self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertEqual(file_sha(r/'dev/boot'),original)
                self.assertNotIn('security-r2',self.events(r));self.assertNotIn('write candidate',self.events(r))
                if kind=='symlink':self.assertTrue(p.is_symlink())

    def test_backup_flush_or_security_component_failure_never_writes_boot(self):
        for flag in ('backup_flush_error','r2_error'):
            with self.subTest(flag=flag):
                r,original,_=self.fixture({flag:True});result=self.run_script(r)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertEqual(file_sha(r/'dev/boot'),original);self.assertNotIn('write candidate',self.events(r))
                if flag=='backup_flush_error':self.assertNotIn('security-r2',self.events(r))

    def test_partial_write_or_fresh_readback_error_restores_original(self):
        for flag in ('write_error','readback_error'):
            with self.subTest(flag=flag):
                r,original,_=self.fixture({flag:True});result=self.run_script(r)
                self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('Original boot restored and read back',result.stdout)
                self.assertEqual(file_sha(r/'dev/boot'),original)
                self.assertEqual(file_sha(self.backup(r,original)),original)
                self.assertIn('write restore',self.events(r));self.assertNotIn('R8Q memory R3 applied:',result.stdout)

    def test_missing_original_backup_on_already_installed_candidate_is_rejected(self):
        r,_,candidate=self.fixture()
        with (r/'dev/boot').open('wb')as f:
            for _ in range(64):f.write(b'N'*1048576)
        result=self.run_script(r);self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertEqual(file_sha(r/'dev/boot'),candidate);self.assertNotIn('security-r2',self.events(r))

    def test_production_template_has_no_runtime_test_mode_or_wipe_commands(self):
        text=(ROOT/'tools/boot_memory/installer.sh').read_text()
        self.assertIn('[ -b "$BOOT" ]',text);self.assertIn('[ -b "$DATA_DEVICE" ]',text)
        self.assertNotIn('R8Q_TEST_REGULAR_FILES',text)
        self.assertIsNone(re.search(r'\b(?:mkfs|mke2fs|wipefs|blkdiscard|dmsetup)\b',text))
        for bad in ('../boot','g'*64,'0'*63):
            with self.assertRaises(ValueError):package.render(bad,'0'*64,'0'*64,'0'*64)


if __name__=='__main__':unittest.main()
