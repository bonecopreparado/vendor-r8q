"""Bind the planner to real baseline bytes, including the missing final LF."""
from pathlib import Path
import hashlib
import json
import sys
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/display_group'))
import prepare_image_plans as stage


class Tests(unittest.TestCase):
    def inputs(self):
        with zipfile.ZipFile(ROOT/'ci-r8q/vendor_audit/data/baseline-vendor.zip') as archive:
            original=archive.read('configs/etc/init/hw/init.qcom.rc')
            legacy=archive.read('configs/ueventd.rc')
        plan=json.loads((ROOT/'patches/0007-policy-integration/vendor-plan.json').read_text())
        row=next(r for r in plan['operations']if r['path']=='/etc/init/hw/init.qcom.rc')
        self.assertEqual(hashlib.sha256(original).hexdigest(),row['old_sha256'])
        generated=stage.previous.remove_unsupported_logdump(original)
        self.assertEqual(hashlib.sha256(generated).hexdigest(),row['sha256'])
        self.assertEqual(generated,(ROOT/'patches/0007-policy-integration'/row['source']).read_bytes())
        return legacy,generated,(ROOT/'tools/ueventd_compat/ueventd.rc').read_bytes()

    def test_real_generator_baseline_and_all_three_pins_agree(self):
        legacy,generated,bridge=self.inputs()
        self.assertFalse(generated.endswith(b'\n'))
        self.assertEqual(tuple(map(stage.sha,(legacy,generated,bridge))),
                         (stage.LEGACY_SHA,stage.INIT_SHA,stage.BRIDGE_SHA))
        plans={p:dict(schema_version=1,source_image_sha256='1'*64,operations=[])
               for p in ('system','system_ext','vendor','odm')}
        with patch.object(stage.sf,'transform',return_value=b'fixture ELF already covered separately'):
            result,payloads=stage.augment(plans,b'fixture',legacy,generated,
                b'import /vendor/etc/ueventd.rc\n',bridge)
        self.assertEqual(len(result['vendor']['operations']),1)
        self.assertEqual(payloads['candidate/vendor/etc/ueventd.rc'],bridge)

    def test_normalizing_any_real_configuration_is_rejected(self):
        values=self.inputs()
        plans={p:dict(schema_version=1,source_image_sha256='1'*64,operations=[])
               for p in ('system','system_ext','vendor','odm')}
        for index in range(3):
            changed=list(values);changed[index]+=b'\n'
            with self.subTest(index=index),self.assertRaisesRegex(ValueError,'SHA differs'):
                stage.augment(plans,b'fixture',changed[0],changed[1],
                    b'import /vendor/etc/ueventd.rc\n',changed[2])


if __name__=='__main__':unittest.main()
