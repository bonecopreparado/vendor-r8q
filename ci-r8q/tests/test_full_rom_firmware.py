"""Real firmware bundle coherence plus actual ext4 replacement and metadata."""
from pathlib import Path
import base64
import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0,str(ROOT/'tools'))
from vendor_security import full_rom as firmware
ext4=firmware.image_labels.ext4


class BundleTests(unittest.TestCase):
    def test_real_two_programs_derive_all_twelve_exact_R2_files(self):
        files=firmware.payloads();self.assertEqual(len(files),12)
        self.assertEqual(files['ipa_uc.mdt'],files['ipa_uc.b00']+files['ipa_uc.b01'])
        self.assertEqual(files['ipa_fws.mdt'],files['ipa_fws.b00']+files['ipa_fws.b01'])
        plan=dict(schema_version=1,source_image_sha256='a'*64,operations=[])
        candidate,changed=firmware.augment(plan)
        self.assertEqual(len(candidate['operations']),8);self.assertEqual(len(changed),8)
        self.assertEqual(plan['operations'],[])
        self.assertTrue(all(r['op']=='replace'and r['old_sha256']!=r['sha256']for r in candidate['operations']))

    def test_tampered_or_duplicate_programs_and_duplicate_plan_targets_are_refused(self):
        with tempfile.TemporaryDirectory()as td:
            p=Path(td)/'programs.json';original=json.loads(firmware.PROGRAMS.read_text())
            for kind in ('bytes','duplicate','path'):
                value=copy.deepcopy(original)
                if kind=='bytes':value['files'][0]['base64']=base64.b64encode(b'bad').decode()
                elif kind=='duplicate':value['files'][1]=value['files'][0]
                else:value['files'][0]['name']='../anything'
                p.write_text(json.dumps(value))
                with self.subTest(kind=kind),self.assertRaises(ValueError):firmware.payloads(p)
        with self.assertRaises(ValueError):firmware.augment(dict(schema_version=1,operations=[{'path':'/firmware/ipa_fws.elf'}]))


@unittest.skipUnless(shutil.which('mke2fs')and shutil.which('debugfs')and shutil.which('e2fsck'),'Real ext4 tools are required')
class ImageTests(unittest.TestCase):
    def test_real_built_vendor_contains_all_R2_programs_and_preserves_other_metadata(self):
        with tempfile.TemporaryDirectory(prefix='r8q-firmware-ext4-')as td:
            r=Path(td);source=r/'source.img'
            with source.open('wb')as f:f.truncate(32*1024**2)
            subprocess.run(['mke2fs','-q','-t','ext4','-F',source],check=True,capture_output=True)
            fs=ext4.Ext4(source,r);fs.command('mkdir /firmware',writable=True)
            files=firmware.payloads();profile=copy.deepcopy(firmware.image_labels.package.profile())
            old_names={row['name']for row in profile['data']}
            for name,data in files.items():
                if name in old_names:data=('old:'+name).encode()
                local=r/'data';local.write_bytes(data);fs.command('write '+str(local)+' /firmware/'+name,writable=True)
                fs.command('ea_set /firmware/'+name+' user.keep keep-metadata',writable=True)
                for row in profile['data']:
                    if row['name']==name:row['old_sha256']=hashlib.sha256(data).hexdigest()
            before=fs.stat('/firmware/ipa_uc.elf');source_sha=ext4.sha_file(source)
            with patch.object(firmware.image_labels.package,'profile',return_value=profile):
                plan,payloads=firmware.augment(dict(schema_version=1,source_image_sha256=source_sha,operations=[]))
                folder=r/'candidate/vendor/firmware';folder.mkdir(parents=True)
                for name,data in payloads.items():(folder/name).write_bytes(data)
                p=r/'vendor-plan.json';p.write_text(json.dumps(plan))
                result=ext4.patch_image(source,p,r/'output.img')
                report=firmware.inspect(r/'output.img')
            self.assertEqual(ext4.sha_file(source),source_sha)
            self.assertEqual(len(report['files']),12)
            after=ext4.Ext4(r/'output.img',r).stat('/firmware/ipa_uc.elf')
            self.assertTrue(ext4.metadata_equal(before,after))
            self.assertFalse(report['hardware_boot_confirmed'])


if __name__=='__main__':unittest.main()
