"""Execute the real recovery script with regular-file fixtures and mock mounts."""
from pathlib import Path
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

ROOT = Path(__file__).resolve().parents[2]
SHELL = shutil.which('mksh') or '/bin/bash'
SHA = lambda b: hashlib.sha256(b).hexdigest()
spec = importlib.util.spec_from_file_location('ipa_package', ROOT/'tools/package_ipa_stock_fix.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
OLD = {
    'ipa_fws.b01': 'f3185a8a9c39e3b7d6edc0c2bd1a1c7a58c0081150aa4c462c561ba89aa64e53',
    'ipa_fws.mdt': '49bd59c7d0189e06e0883fddaca5723ebe7d18906eaef2d6bd98e200355c6dbd',
    'ipa_fws.elf': 'bf08513983e01d9a331eba795e53a96adf0010fd41b65152ff1ec2e29843ebe8',
}
NEW = {
    'ipa_fws.b01': '8bc6bf3243e4a76cd18e5128cccf1cf1b7c6653ee228116d16b3b8e086cf8231',
    'ipa_fws.mdt': '0b2e4533de1cd1cbf81cdf4406926ea12139dbca83f07b6c3fce1bfc9a59ab05',
    'ipa_fws.elf': '94587aaebc7b9edc1935d929c7a0253ca3e35317337cc1359df0efcfa082e209',
}
CODE = {
    'ipa_fws.b00': '6140bd155996ed6134a8d2403ae1f911554a2dfee71b82568bff5bbf90d84c22',
    'ipa_fws.b02': '75042a4ebd0835080c016bb9e22be738db863005bfbd57e230f654122e9ec1e1',
    'ipa_fws.b03': '14024088f436ebd24b097cb113b2177e12c939efdac0211d560c7cc498611507',
    'ipa_fws.b04': '08a996d4efe3ac0d4e4d8948d2a6bcc24fda5138c2e196f9568245fbafee62a3',
}
MOCK = r'''#!/usr/bin/env python3
import json,os,shutil,sys
from pathlib import Path
r=Path(os.environ['FIXTURE_ROOT']);name=Path(sys.argv[0]).name;args=sys.argv[1:]
flags=json.loads((r/'flags.json').read_text())
with (r/'events').open('a') as f:f.write(name+' '+json.dumps(args)+'\n')
if name=='getprop':
 props={'ro.product.device':'r8q','ro.bootloader':'G781BXXSIHYJ2','ro.bootmode':'unknown','ro.orangefox.boot':'1','ro.twrp.boot':'0','init.svc.recovery':'running','ro.twrp.fastbootd':'0'}
 props.update(flags.get('props',{}));print(props.get(args[0],''))
elif name=='id':print('0')
elif name=='ls':print('u:object_r:firmware_file:s0 '+args[-1])
elif name=='stat':
 if args[-2]=='%u:%g:%a':print('0:0:644')
 else:os.execv('/usr/bin/stat',['stat']+args)
elif name in ('chown','chcon'):
 if flags.get(name):sys.exit(1)
elif name=='df':print('Filesystem 1024-blocks Used Available Capacity Mounted on\nfixture 20000 1000 '+str(flags.get('available',19000))+' 5% '+str(r/'vendor'))
elif name=='mount':
 p=r/'proc/mounts';s=p.read_text()
 if '-t' in args:
  if flags.get('stock_mount_fail'):sys.exit(1)
  dest=Path(args[-1]);shutil.copytree(r/'stock',dest,dirs_exist_ok=True)
  s+=str(r/'dev/block/apnhlos')+' '+str(dest)+' vfat ro,relatime 0 0\n'
 else:
  if 'remount,rw' in args and flags.get('rw_fail'):sys.exit(1)
  s=s.replace(' ro,',' rw,') if 'remount,rw' in args else s.replace(' rw,',' ro,')
 p.write_text(s)
elif name=='umount':
 if flags.get('umount_fail'):sys.exit(1)
 dest=Path(args[-1]);p=r/'proc/mounts';p.write_text(''.join(l for l in p.read_text().splitlines(True)if l.split()[1]!=str(dest)))
 shutil.rmtree(dest/'image')
elif name=='mv':
 if flags.get('fail_second_activation')and args[-1]==str(r/'vendor/firmware/ipa_fws.mdt')and '.r8q-ipa-stage.' in args[-2]and '/restore-' not in args[-2]:sys.exit(1)
 os.execv('/usr/bin/mv',['mv']+args)
elif name=='sync':
 if flags.get('fail_install_sync')and (r/'vendor/firmware/ipa_fws.elf').read_bytes()==(r/'expected/ipa_fws.elf').read_bytes():sys.exit(1)
'''


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = tempfile.TemporaryDirectory()
        cls.archive, cls.digest = package.package(Path(cls.t.name))

    @classmethod
    def tearDownClass(cls):
        cls.t.cleanup()

    def fixture(self, flags=None, rw=False):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        r = Path(t.name)
        for p in ['vendor/firmware', 'vendor/etc/init/hw', 'dev/block/bootdevice/by-name',
                  'sys/class/block/dm-vendor/dm', 'sys/class/power_supply/battery',
                  'stock/image', 'expected', 'bin', 'tmp', 'proc']:
            (r/p).mkdir(parents=True, exist_ok=True)
        self.old = {name: (name.encode()+b' OLD') for name in OLD}
        self.new = {name: (name.encode()+b' NEW') for name in NEW}
        self.old['ipa_fws.elf'] = b'ELF'+b'\0'*5000
        self.new['ipa_fws.elf'] = (self.old['ipa_fws.elf'][:4096]+self.new['ipa_fws.b01']+
                                   self.old['ipa_fws.elf'][4096+len(self.new['ipa_fws.b01']):])
        self.code = {name: name.encode()+b' CODE' for name in CODE}
        for name, data in (self.old | self.code).items():
            (r/'vendor/firmware'/name).write_bytes(data)
            (r/'vendor/firmware'/name).chmod(0o644)
        for name, data in self.new.items():
            (r/'expected'/name).write_bytes(data)
            if name != 'ipa_fws.elf': (r/'stock/image'/name).write_bytes(data)
        (r/'vendor/etc/init/hw/init.qcom.rc').write_bytes(b'REVIEWED VENDOR INIT')
        (r/'dev/block/dm-vendor').touch()
        (r/'dev/block/apnhlos').touch()
        (r/'dev/block/bootdevice/by-name/apnhlos').symlink_to('../../apnhlos')
        (r/'sys/class/block/dm-vendor/dm/name').write_text('vendor\n')
        (r/'sys/class/power_supply/battery/capacity').write_text('80\n')
        (r/'sys/class/power_supply/battery/status').write_text('Discharging\n')
        (r/'proc/mounts').write_text(f'{r}/dev/block/dm-vendor {r}/vendor ext4 '+('rw'if rw else 'ro')+',relatime 0 0\n')
        (r/'flags.json').write_text(json.dumps(flags or {}))
        for name in ['getprop','id','ls','stat','chown','chcon','df','mount','umount','mv','sync']:
            path=r/'bin'/name;path.write_text(MOCK);path.chmod(0o755)
        return r

    def execute(self, r):
        with zipfile.ZipFile(self.archive) as z:
            script = z.read('META-INF/com/google/android/update-binary').decode()
        for pins, data in [(OLD,self.old),(NEW,self.new),(CODE,self.code)]:
            for name, digest in pins.items(): script=script.replace(digest,SHA(data[name]))
        script=script.replace('9971fef6dfa6951ec593bd82351203deb71e6185a4eea5354fe2fef3912114ea',SHA(b'REVIEWED VENDOR INIT'))
        # Fixture block devices are ordinary files; no real mount or block I/O.
        script=script.replace('[ -b "$APNHLOS_REAL" ]','[ -f "$APNHLOS_REAL" ]')
        paths=['/vendor','/proc/mounts','/sys/class','/dev/block','/tmp/r8q-ipa.']
        script=re.sub(r'(?<![A-Za-z0-9_./$])(?:'+'|'.join(re.escape(p)for p in sorted(paths,key=len,reverse=True))+')',lambda m:str(r)+m.group(),script)
        (r/'run.sh').write_text(script)
        return subprocess.run([SHELL,str(r/'run.sh'),'3','1',str(self.archive)],
                              env=dict(os.environ,PATH=str(r/'bin')+':'+os.environ['PATH'],FIXTURE_ROOT=str(r)),
                              capture_output=True,text=True,timeout=25)

    def assert_state(self, r, data):
        for name, expected in (data | self.code).items():
            self.assertEqual((r/'vendor/firmware'/name).read_bytes(),expected,name)
        self.assertEqual(list((r/'tmp').iterdir()),[])

    def test_install_backup_idempotence_and_original_mount_mode(self):
        for rw in [False,True]:
            with self.subTest(rw=rw):
                r=self.fixture(rw=rw)
                for _ in range(2):
                    result=self.execute(r);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assert_state(r,self.new)
                    self.assertIn(' '+('rw'if rw else 'ro')+',',(r/'proc/mounts').read_text())
                for name,data in self.old.items():self.assertEqual((r/'vendor/firmware/.r8q-ipa-p1r4-backup'/name).read_bytes(),data)

    def test_unknown_vendor_code_stock_or_auth_aborts_without_vendor_remount(self):
        for path in ['vendor/firmware/ipa_fws.b02','vendor/firmware/ipa_fws.mdt','stock/image/ipa_fws.mdt','vendor/etc/init/hw/init.qcom.rc']:
            r=self.fixture();(r/path).write_bytes(b'UNKNOWN')
            result=self.execute(r);self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertNotIn('remount,rw',(r/'events').read_text())

    def test_device_recovery_and_battery_guards(self):
        cases=[{'ro.product.device':'r8s'},{'ro.bootloader':'G780F-EXYNOS'},
               {'ro.orangefox.boot':'0','ro.twrp.boot':'0'},
               {'ro.orangefox.boot':'0','ro.twrp.boot':'1','ro.twrp.fastbootd':'1'}]
        for props in cases:
            r=self.fixture({'props':props});self.assertNotEqual(self.execute(r).returncode,0)
            self.assertNotIn('mount ',(r/'events').read_text())
        r=self.fixture();(r/'sys/class/power_supply/battery/capacity').write_text('20\n')
        self.assertNotEqual(self.execute(r).returncode,0);self.assertNotIn('mount ',(r/'events').read_text())
        (r/'sys/class/power_supply/battery/status').write_text('Charging\n')
        result=self.execute(r);self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_twrp_unknown_mode_and_g780g_family_are_accepted(self):
        r=self.fixture({'props':{'ro.bootloader':'G780GXXSHEYJ1','ro.orangefox.boot':'0','ro.twrp.boot':'1'}})
        result=self.execute(r);self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_mid_activation_and_post_activation_sync_failure_restore_originals(self):
        for flag in ['fail_second_activation','fail_install_sync']:
            r=self.fixture({flag:True});result=self.execute(r)
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertIn('Original IPA files restored',result.stdout)
            self.assert_state(r,self.old);self.assertIn(' ro,',(r/'proc/mounts').read_text())

    def test_remount_label_and_low_space_failures_preserve_originals(self):
        for flags in [{'rw_fail':True},{'chcon':True},{'available':100}]:
            r=self.fixture(flags);result=self.execute(r)
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assert_state(r,self.old);self.assertIn(' ro,',(r/'proc/mounts').read_text())

    def test_symlinked_firmware_is_rejected(self):
        r=self.fixture();p=r/'vendor/firmware/ipa_fws.mdt';p.rename(p.with_suffix('.elsewhere'));p.symlink_to('ipa_fws.elsewhere')
        self.assertNotEqual(self.execute(r).returncode,0)
        self.assertNotIn('mount ',(r/'events').read_text())

    def test_partial_state_requires_valid_backup_and_can_resume(self):
        r=self.fixture();(r/'vendor/firmware/ipa_fws.b01').write_bytes(self.new['ipa_fws.b01'])
        self.assertNotEqual(self.execute(r).returncode,0)
        backup=r/'vendor/firmware/.r8q-ipa-p1r4-backup';backup.mkdir()
        for name,data in self.old.items():(backup/name).write_bytes(data)
        result=self.execute(r);self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assert_state(r,self.new)

    def test_zip_integrity_checksum_script_permissions_and_no_firmware_blobs(self):
        self.assertEqual(SHA(self.archive.read_bytes()),self.digest)
        with zipfile.ZipFile(self.archive) as z:
            self.assertIsNone(z.testzip());self.assertEqual(len(z.namelist()),4)
            self.assertEqual((z.getinfo('META-INF/com/google/android/update-binary').external_attr>>16)&0o777,0o755)
            self.assertFalse(any(n.endswith(('.mdt','.b01','.elf'))for n in z.namelist()))


if __name__ == '__main__': unittest.main()
