from pathlib import Path
import copy
import importlib.util
import struct
import sys
import unittest
from unittest.mock import patch
import test_susfs22_linked_verifier as linked
import test_nflog_boot_repack as old

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/kernel_nflog/susfs22'))
import repack_verified as repack


class Tests(unittest.TestCase):
    def original(self):
        data=old.Tests().boot()
        return data+bytes(512*1024-len(data))

    def test_real_layout_repack_preserves_ramdisk_dtb_header_and_image_bytes(self):
        original=self.original()
        kernel,report=linked.fixture()
        with patch.object(repack,'BOOT_BYTES',len(original)),patch.object(repack,'BOOT_SHA',repack.sha(original)):
            candidate,evidence=repack.repack(original,kernel,report)
        self.assertEqual(len(candidate),len(original))
        before,after=repack.sections(original),repack.sections(candidate)
        self.assertEqual(after['kernel'],kernel)
        for name in ('ramdisk','second','recovery_dtbo','dtb'):
            self.assertEqual(after[name],before[name])
        self.assertEqual(candidate[12:576],original[12:576])
        self.assertEqual(candidate[608:4096],original[608:4096])
        self.assertIs(evidence['raw_image_header_rewritten'],False)
        self.assertIs(evidence['hardware_boot_confirmed'],False)
        self.assertIs(evidence['old_dtb_compatibility_confirmed'],False)

    def test_unknown_source_or_invalid_compile_record_is_refused(self):
        original=self.original();kernel,report=linked.fixture()
        with self.assertRaisesRegex(ValueError,'exact shipped'):
            repack.repack(original,kernel,report)
        report['status']='INPUT_CONFIG_OR_COMPILE_FAILED'
        with patch.object(repack,'BOOT_BYTES',len(original)),patch.object(repack,'BOOT_SHA',repack.sha(original)):
            with self.assertRaisesRegex(ValueError,'successful complete'):
                repack.repack(original,kernel,report)

    def test_changed_arm64_header_is_not_rewritten_to_make_it_pass(self):
        original=self.original();kernel,report=linked.fixture()
        modified=bytearray(kernel);struct.pack_into('<Q',modified,8,0x80000)
        report=copy.deepcopy(report)
        report['outputs']['Image']['sha256']=repack.sha(modified)
        with patch.object(repack,'BOOT_BYTES',len(original)),patch.object(repack,'BOOT_SHA',repack.sha(original)):
            with self.assertRaises(ValueError):
                repack.repack(original,bytes(modified),report)


if __name__=='__main__':unittest.main()
