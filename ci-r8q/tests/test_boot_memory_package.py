"""Exercise real R2 rendering through the final ZIP writer/readback contract.

Kernel repack has separate actual-layout/linked-config tests; this fixture
substitutes only that expensive input step. Its synthetic ELF is never run.
"""
from pathlib import Path
import gzip
import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('memory_zip_package',ROOT/'tools/package_boot_memory.py')
package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)


class Tests(unittest.TestCase):
    def fixture(self):
        temp=tempfile.TemporaryDirectory(prefix='r8q-memory-package-');self.addCleanup(temp.cleanup)
        r=Path(temp.name);helper=r/'synthetic-structure-only.elf'
        blob=bytearray(64);blob[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',blob,18,183)
        struct.pack_into('<H',blob,54,56);blob.extend(package.PRODUCTION+b'\x00')
        helper.write_bytes(blob)
        image=b'fixture-kernel-step-independently-tested'
        provenance=dict(source_commit=package.SOURCE_COMMIT,kernel_sha256=hashlib.sha256(image).hexdigest())
        return r,helper,image,provenance

    def test_actual_security_renderer_is_encoded_and_embedded_in_complete_readable_zip(self):
        r,helper,image,provenance=self.fixture();out=r/'fixture-only.zip'
        candidate=b'\x00'*67108864
        with patch.object(package.repack_verified,'repack',return_value=(candidate,{'fixture':True})):
            result=package.build(out,b'fixture-source',image,{},helper,provenance,b'fixture-license')
        with zipfile.ZipFile(out)as z:
            self.assertEqual(z.read('scripts/security-r2.sh'),package.package_vendor_security.render().encode('utf-8'))
            self.assertEqual(gzip.decompress(z.read('images/boot.img.gz')),candidate)
            self.assertNotIn(b'@@',z.read(package.INSTALLER))
            self.assertFalse(json.loads(z.read('R3-MANIFEST.json'))['hardware_boot_confirmed'])
        self.assertEqual(result['zip_sha256'],hashlib.sha256(out.read_bytes()).hexdigest())
        self.assertIn(result['zip_sha256'],out.with_suffix('.zip.sha256').read_text())
        self.assertTrue(result['persistent_original_boot_backup_required'])
        self.assertFalse(result['external_payloads_required'])

    def test_wrong_kernel_source_is_rejected_before_a_zip_is_created(self):
        r,helper,image,provenance=self.fixture();out=r/'fixture-only.zip'
        with self.assertRaises(ValueError):package.build(out,b'source',image,{},helper,provenance|{'source_commit':'0'*40},b'license')
        self.assertFalse(out.exists())

    def test_test_mode_helper_is_rejected_even_if_its_elf_structure_is_accepted(self):
        r,helper,image,provenance=self.fixture();out=r/'fixture-only.zip'
        helper.write_bytes(helper.read_bytes()+package.TEST)
        with patch.object(package.repack_verified,'repack',return_value=(b'candidate',{})),self.assertRaises(ValueError):
            package.build(out,b'source',image,{},helper,provenance,b'license')
        self.assertFalse(out.exists())


if __name__=='__main__':unittest.main()
