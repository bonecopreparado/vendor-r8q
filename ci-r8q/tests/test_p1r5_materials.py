"""Reject firmware/label reports that do not bind the actual packaged Super."""
from pathlib import Path
import copy
import json
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from vendor_security import full_rom
import p1r5_materials as material


class Tests(unittest.TestCase):
    def fixture(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);root=Path(t.name)
        files=full_rom.payloads();bundle=full_rom.sha(full_rom.PROGRAMS.read_bytes())
        rows=[dict(name=n,bytes=len(d),sha256=full_rom.sha(d))for n,d in sorted(files.items())]
        firmware=dict(status='R2_FIRMWARE_VERIFIED_IN_BUILT_VENDOR_NOT_BOOT_TESTED',files=rows,
                      image_sha256='a'*64,bundle_sha256=bundle,hardware_boot_confirmed=False)
        changes=[dict(path='/'if r['path']=='.'else '/'+r['path'],expected=r['label'])for r in full_rom.image_labels.package.profile()['labels']]
        labels=dict(status='VENDOR_LABELS_REPAIRED_OFFLINE_NOT_BOOT_TESTED',file_contents_preserved=True,
                    candidate_e2fsck={'exit':0},candidate_sha256='a'*64,hardware_boot_confirmed=False,changes=changes)
        stage=dict(bundle_sha256=bundle,firmware={r['name']:r['sha256']for r in rows},operations_added=8,hardware_boot_confirmed=False)
        manifest=dict(build_label='P1r5',vendor_firmware=firmware,vendor_label_repair=labels,firmware_stage=stage)
        images=[dict(partition='super',sha256='b'*64)]
        p=root/'reports/p1/ci-build/super-independent-readback.json';p.parent.mkdir(parents=True)
        report=dict(status='INDEPENDENT_SUPER_HASHES_MATCH_NOT_BOOT_TESTED',super_image_sha256='b'*64,
                    partitions=[dict(name='vendor',sha256='a'*64)])
        p.write_text(json.dumps(report))
        return root,manifest,images,p,report

    def test_coherent_actual_vendor_and_super_evidence_is_accepted(self):
        root,manifest,images,_,_=self.fixture();r=material.bind(manifest,root,images)
        self.assertTrue(r['stock_firmware_preflight_required']);self.assertTrue(r['direct_storage_readback_required'])
        self.assertEqual(len(r['vendor_security']['firmware']['files']),12)

    def test_missing_or_substituted_firmware_label_or_super_proof_is_rejected(self):
        root,manifest,images,p,report=self.fixture()
        for kind in ('firmware','labels','different_vendor','stage'):
            bad=copy.deepcopy(manifest)
            if kind=='firmware':bad['vendor_firmware']['files'][0]['sha256']='0'*64
            elif kind=='labels':bad['vendor_label_repair']['changes'][0]['expected']='u:object_r:wrong:s0'
            elif kind=='different_vendor':bad['vendor_firmware']['image_sha256']='0'*64
            else:bad['firmware_stage']['operations_added']=0
            with self.subTest(kind=kind),self.assertRaises(ValueError):material.bind(bad,root,images)
        for kind in ('super','vendor'):
            bad=copy.deepcopy(report)
            if kind=='super':bad['super_image_sha256']='0'*64
            else:bad['partitions'][0]['sha256']='0'*64
            p.write_text(json.dumps(bad))
            with self.subTest(kind=kind),self.assertRaises(ValueError):material.bind(manifest,root,images)


if __name__=='__main__':unittest.main()
