"""Run the cumulative recovery script with regular files and simulated mounts."""
from pathlib import Path
import hashlib
import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SHELL = os.environ.get('MKSH_BINARY', shutil.which('mksh') or '/bin/bash')
SHA = lambda b: hashlib.sha256(b).hexdigest()
spec = importlib.util.spec_from_file_location('security_package', ROOT/'tools/package_vendor_security.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
PROFILE = package.profile()
MOCK = r'''#!/usr/bin/env python3
from pathlib import Path
import json,os,shutil,sys
r=Path(os.environ['FIXTURE_ROOT']);name=Path(sys.argv[0]).name;args=sys.argv[1:]
flags=json.loads((r/'flags.json').read_text());lp=r/'labels.json';labels=json.loads(lp.read_text())
with (r/'events').open('a')as f:f.write(name+' '+json.dumps(args)+'\n')
def relative(path):
 p=Path(path).resolve()
 if p==r/'vendor':return '.'
 if (r/'vendor')in p.parents:return str(p.relative_to(r/'vendor'))
 for parent in [p]+list(p.parents):
  if parent.name=='vendor'and parent.parent.name.startswith('r8q-security.'):
   return str(p.relative_to(parent))
 return str(p)
if name=='getprop':
 props={'ro.product.device':'r8q','ro.bootloader':'G781BXXSIHYJ2','ro.bootmode':'unknown','ro.orangefox.boot':'1','ro.twrp.boot':'0','init.svc.recovery':'running','ro.twrp.fastbootd':'0'}
 props.update(flags.get('props',{}));print(props.get(args[0],''))
elif name=='id':print('0')
elif name=='ls':print(labels.get(relative(args[-1]),'u:object_r:firmware_file:s0')+' '+args[-1])
elif name=='stat':
 if args[-2]=='%u:%g:%a':print('0:0:644')
 elif args[-2]=='%u:%a':print('0:755')
 else:os.execv('/usr/bin/stat',['stat']+args)
elif name=='chown':pass
elif name=='chcon':
 key=relative(args[-1]);context=args[0]
 if flags.get('fail_label')and key=='etc/selinux/vendor_hwservice_contexts'and context=='u:object_r:hwservice_contexts_file:s0':sys.exit(1)
 labels[key]=context;lp.write_text(json.dumps(labels))
elif name=='df':print('Filesystem 1024-blocks Used Available Capacity Mounted on\nfixture 20000 1000 '+str(flags.get('available',19000))+' 5% '+args[-1])
elif name=='mount':
 p=r/'proc/mounts';lines=p.read_text().splitlines(True)
 if '-t'in args:
  dest=Path(args[-1]);kind=args[args.index('-t')+1]
  if flags.get('stock_mount_fail')and kind=='vfat':sys.exit(1)
  shutil.copytree(r/('stock'if kind=='vfat'else'vendor'),dest,dirs_exist_ok=True)
  source=r/'dev/block'/('apnhlos'if kind=='vfat'else'dm-vendor')
  lines.append(str(source)+' '+str(dest)+' '+kind+' ro,relatime 0 0\n')
 else:
  if flags.get('rw_fail')and'remount,rw'in args:sys.exit(1)
  lines=[l.replace(' ro,',' rw,')if 'remount,rw'in args else l.replace(' rw,',' ro,')for l in lines]
 p.write_text(''.join(lines))
elif name=='umount':
 dest=Path(args[-1]);p=r/'proc/mounts';p.write_text(''.join(l for l in p.read_text().splitlines(True)if l.split()[1]!=str(dest)))
 if dest.name=='apnhlos':shutil.rmtree(dest/'image')
 else:
  shutil.copytree(dest,r/'vendor',dirs_exist_ok=True)
  shutil.rmtree(dest);dest.mkdir()
elif name=='mv':
 src,dst=args[-2:]
 if flags.get('fail_activation')and relative(dst)=='firmware/ipa_uc.b00'and '.r8q-security-stage.'in src and '/restore-'not in src:sys.exit(1)
 a,b=relative(src),relative(dst)
 for key in list(labels):
  if key==a or key.startswith(a+'/'):labels[b+key[len(a):]]=labels.pop(key)
 lp.write_text(json.dumps(labels));os.execv('/usr/bin/mv',['mv']+args)
elif name=='sync':
 expected=json.loads((r/'expected-labels.json').read_text())
 if flags.get('fail_install_sync')and all(labels.get(k)==v for k,v in expected.items()):sys.exit(1)
'''


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.archive,cls.digest=package.package(Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def fixture(self,flags=None,prior_r1=False,mounted=True,rw=False):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);r=Path(tmp.name)
        for p in ['vendor/firmware','vendor/etc/init/hw','vendor/etc/selinux','dev/block/bootdevice/by-name',
                  'sys/class/block/dm-vendor/dm','sys/class/power_supply/battery','stock/image','tmp','proc','bin']:
            (r/p).mkdir(parents=True,exist_ok=True)
        old={row['name']:b'old:'+row['name'].encode()for row in PROFILE['data']}
        new={row['name']:b'new:'+row['name'].encode()for row in PROFILE['data']}
        old['ipa_fws.b01']=b'A'*6808;new['ipa_fws.b01']=b'B'*6808
        old['ipa_fws.elf']=b'F'*4096+old['ipa_fws.b01']+b'F'*(37552-4096-6808)
        new['ipa_fws.elf']=old['ipa_fws.elf'][:4096]+new['ipa_fws.b01']+old['ipa_fws.elf'][4096+6808:]
        for n,size,token in [('ipa_uc.b00',148,b'H'),('ipa_uc.b01',6712,b'S'),('ipa_uc.b02',35212,b'C')]:new[n]=token*size
        elf=bytearray(47500);elf[:148]=new['ipa_uc.b00'];elf[4096:4096+6712]=new['ipa_uc.b01'];elf[12288:]=new['ipa_uc.b02'];new['ipa_uc.elf']=bytes(elf)
        self.old,self.new=old,new
        self.original={n:(new[n]if prior_r1 and n.startswith('ipa_fws.')else b)for n,b in old.items()}
        for n,b in self.original.items():(r/'vendor/firmware'/n).write_bytes(b);(r/'vendor/firmware'/n).chmod(0o644)
        self.immutable={row['name']:('code:'+row['name']).encode()for row in PROFILE['immutable']}
        for n,b in self.immutable.items():(r/'vendor/firmware'/n).write_bytes(b)
        for row in PROFILE['stock']:(r/'stock/image'/row['name']).write_bytes(new[row['name']])
        self.metadata={row['path']:('metadata:'+row['path']).encode()for row in PROFILE['labels']if row['path']!='.'}
        for n,b in self.metadata.items():(r/'vendor'/n).write_bytes(b)
        (r/'vendor/etc/init/hw/init.qcom.rc').write_bytes(b'REVIEWED INIT')
        self.labels={row['path']:'u:object_r:vendor_configs_file:s0'for row in PROFILE['labels']}
        self.labels['.']='u:object_r:vendor_apex_file:s0'
        self.labels['etc/selinux/vendor_service_contexts']='u:object_r:vendor_service_contexts_file:s0'
        (r/'labels.json').write_text(json.dumps(self.labels))
        (r/'expected-labels.json').write_text(json.dumps({row['path']:row['label']for row in PROFILE['labels']}))
        (r/'flags.json').write_text(json.dumps(flags or {}))
        for n in ['dm-vendor','apnhlos']:(r/'dev/block'/n).touch()
        (r/'dev/block/bootdevice/by-name/apnhlos').symlink_to('../../apnhlos')
        (r/'sys/class/block/dm-vendor/dm/name').write_text('vendor\n')
        (r/'sys/class/power_supply/battery/capacity').write_text('80\n')
        (r/'sys/class/power_supply/battery/status').write_text('Discharging\n')
        (r/'proc/mounts').write_text(f'{r}/dev/block/dm-vendor {r}/vendor ext4 '+('rw'if rw else'ro')+',relatime 0 0\n'if mounted else'')
        for n in ['getprop','id','ls','stat','chown','chcon','df','mount','umount','mv','sync']:
            p=r/'bin'/n;p.write_text(MOCK);p.chmod(0o755)
        return r

    def execute(self,r):
        with zipfile.ZipFile(self.archive)as z:s=z.read('META-INF/com/google/android/update-binary').decode()
        for row in PROFILE['data']:
            s=s.replace(row['old_sha256'],SHA(self.old[row['name']])).replace(row['new_sha256'],SHA(self.new[row['name']]))
        for row in PROFILE['immutable']:s=s.replace(row['sha256'],SHA(self.immutable[row['name']]))
        for row in PROFILE['labels']:
            if row['path']!='.':s=s.replace(row['sha256'],SHA(self.metadata[row['path']]))
        s=s.replace(PROFILE['init_sha256'],SHA(b'REVIEWED INIT'))
        # Device nodes are ordinary files in these fixtures; mount operations
        # are simulated and never reach the host kernel.
        s=s.replace('[ -b "$APNHLOS_REAL" ]','[ -f "$APNHLOS_REAL" ]').replace('[ -b "$block" ]','[ -f "$block" ]')
        paths=['/vendor','/proc/mounts','/sys/class','/dev/block','/tmp/r8q-security.']
        s=re.sub(r'(?<![A-Za-z0-9_./$])(?:'+'|'.join(re.escape(p)for p in sorted(paths,key=len,reverse=True))+')',lambda m:str(r)+m.group(),s)
        (r/'run.sh').write_text(s)
        return subprocess.run([SHELL,str(r/'run.sh'),'3','1',str(self.archive)],
                              env=dict(os.environ,PATH=str(r/'bin')+':'+os.environ['PATH'],FIXTURE_ROOT=str(r)),
                              capture_output=True,text=True,timeout=45)

    def assert_original(self,r):
        for n,b in self.original.items():self.assertEqual((r/'vendor/firmware'/n).read_bytes(),b,n)
        labels=json.loads((r/'labels.json').read_text())
        for n,b in self.labels.items():self.assertEqual(labels[n],b,n)
        self.assertEqual(list((r/'tmp').iterdir()),[])

    def assert_installed(self,r):
        for n,b in self.new.items():self.assertEqual((r/'vendor/firmware'/n).read_bytes(),b,n)
        for n,b in self.metadata.items():self.assertEqual((r/'vendor'/n).read_bytes(),b,n)
        for n,b in self.immutable.items():self.assertEqual((r/'vendor/firmware'/n).read_bytes(),b,n)
        labels=json.loads((r/'labels.json').read_text())
        for row in PROFILE['labels']:self.assertEqual(labels[row['path']],row['label'])
        self.assertEqual(list((r/'tmp').iterdir()),[])

    def test_cumulative_install_from_original_and_prior_r1_then_idempotence(self):
        for prior in [False,True]:
            r=self.fixture(prior_r1=prior);result=self.execute(r)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assert_installed(r)
            backup=r/'vendor/firmware/.r8q-security-r2-backup'
            for n,b in self.original.items():self.assertEqual((backup/n).read_bytes(),b)
            manifest=(backup/'sha256.txt').read_bytes()
            result=self.execute(r);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual((backup/'sha256.txt').read_bytes(),manifest);self.assert_installed(r)
            self.assertIn(' ro,',(r/'proc/mounts').read_text())

    def test_automatic_read_only_vendor_mount_and_release(self):
        r=self.fixture(mounted=False);result=self.execute(r)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assert_installed(r)
        self.assertEqual((r/'proc/mounts').read_text(),'')

    def test_original_rw_mount_mode_is_preserved(self):
        r=self.fixture(rw=True);result=self.execute(r)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn(' rw,',(r/'proc/mounts').read_text())

    def test_activation_label_and_final_sync_failures_restore_data_and_labels(self):
        for flag in ['fail_activation','fail_label','fail_install_sync']:
            r=self.fixture({flag:True},prior_r1=True);result=self.execute(r)
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertIn('Pre-installation firmware and labels restored',result.stdout)
            self.assert_original(r);self.assertIn(' ro,',(r/'proc/mounts').read_text())

    def test_unknown_stock_metadata_code_or_firmware_aborts_before_rw(self):
        for name in ['stock/image/ipa_uc.mdt','vendor/etc/selinux/vendor_hwservice_contexts',
                     'vendor/firmware/ipa_fws.b02','vendor/firmware/ipa_uc.b02','vendor/etc/init/hw/init.qcom.rc']:
            r=self.fixture();(r/name).write_bytes(b'UNKNOWN');result=self.execute(r)
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertNotIn('remount,rw',(r/'events').read_text())

    def test_device_fastboot_and_low_battery_guards(self):
        for props in [{'ro.product.device':'r8s'},{'ro.bootloader':'G780F'},
                      {'ro.orangefox.boot':'0','ro.twrp.boot':'1','ro.twrp.fastbootd':'1'}]:
            r=self.fixture({'props':props});self.assertNotEqual(self.execute(r).returncode,0)
            self.assertNotIn('mount ',(r/'events').read_text())
        r=self.fixture();(r/'sys/class/power_supply/battery/capacity').write_text('10\n')
        self.assertNotEqual(self.execute(r).returncode,0)
        self.assertNotIn('mount ',(r/'events').read_text())
        (r/'sys/class/power_supply/battery/status').write_text('Charging\n')
        result=self.execute(r);self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_unknown_root_label_and_symlink_targets_are_refused(self):
        r=self.fixture();labels=self.labels|{'.':'u:object_r:system_data_file:s0'};(r/'labels.json').write_text(json.dumps(labels))
        self.assertNotEqual(self.execute(r).returncode,0);self.assertNotIn('remount,rw',(r/'events').read_text())
        r=self.fixture();p=r/'vendor/etc/selinux/vendor_hwservice_contexts';p.rename(p.with_suffix('.elsewhere'));p.symlink_to('vendor_hwservice_contexts.elsewhere')
        self.assertNotEqual(self.execute(r).returncode,0);self.assertNotIn('remount,rw',(r/'events').read_text())

    def test_corrupt_original_backup_refuses_another_install(self):
        r=self.fixture();self.assertEqual(self.execute(r).returncode,0)
        (r/'vendor/firmware/.r8q-security-r2-backup/ipa_uc.b01').write_bytes(b'CORRUPT')
        result=self.execute(r);self.assertNotEqual(result.returncode,0,result.stdout)
        self.assert_installed(r)

    def test_readonly_remount_and_space_failures_preserve_original_state(self):
        for flags in [{'rw_fail':True},{'available':100},{'stock_mount_fail':True}]:
            r=self.fixture(flags);result=self.execute(r)
            self.assertNotEqual(result.returncode,0,result.stdout);self.assert_original(r)

    def test_profile_zip_permissions_checksum_and_no_firmware_payload(self):
        with zipfile.ZipFile(self.archive)as z:
            self.assertIsNone(z.testzip());self.assertEqual(SHA(self.archive.read_bytes()),self.digest)
            self.assertEqual((z.getinfo('META-INF/com/google/android/update-binary').external_attr>>16)&0o777,0o755)
            self.assertFalse(any(n.endswith(('.b00','.b01','.b02','.mdt','.elf'))for n in z.namelist()))
            self.assertNotIn('@@',z.read('META-INF/com/google/android/update-binary').decode())

    def test_profile_rejects_path_escape_duplicate_inputs_and_wrong_context_types(self):
        for section,key,value in [('stock','name','../../efs/key'),('immutable','name','ipa_uc.b01'),
                                  ('labels','path','etc/selinux/..'),('labels','label','u:object_r:system_data_file:s0')]:
            bad=copy.deepcopy(PROFILE);bad[section][0][key]=value
            with patch.object(package.json,'loads',return_value=bad):
                with self.assertRaises(ValueError):package.profile()


if __name__=='__main__':unittest.main()
