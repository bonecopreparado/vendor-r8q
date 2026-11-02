"""Bounded tests of the exact Samsung init consolidation, no devices/images."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('hardware_candidate',ROOT/'tools/prepare_hardware_candidate.py')
hardware=importlib.util.module_from_spec(spec);spec.loader.exec_module(hardware)


class HardwareCandidateTests(unittest.TestCase):
    def test_duplicate_is_consolidated_without_hardware_selector_changes(self):
        files,manifest=hardware.prepare(hardware.PATCH/'inputs')
        original=(hardware.PATCH/'inputs'/hardware.MULTI).read_text()
        result=files[hardware.MULTI].decode()
        declaration=original.splitlines(keepends=True)[0]
        self.assertEqual(result.replace('\n'.join(hardware.INTERFACES)+'\n','',1),original)
        self.assertEqual(result.count(declaration),1)
        for interface in hardware.INTERFACES:self.assertEqual(result.count(interface),1)
        self.assertEqual([r['action'] for r in manifest['files']],['replace','delete'])
        self.assertEqual(manifest['files'][1]['path'],hardware.DUPLICATE)
        self.assertEqual(set(files),{hardware.MULTI})

    def test_tampered_input_stops_before_output(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name in hardware.PINS:
                p=root/'input'/name;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes((hardware.PATCH/'inputs'/name).read_bytes())
            p=root/'input'/hardware.MULTI;p.write_bytes(p.read_bytes()+b'\n# changed')
            with self.assertRaisesRegex(ValueError,'identity differs'):
                hardware.write_candidate(root/'input',root/'output')
            self.assertFalse((root/'output').exists())

    def test_candidate_is_idempotent_and_refuses_unrelated_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            first=hardware.write_candidate(hardware.PATCH/'inputs',root)
            self.assertEqual(first,hardware.write_candidate(hardware.PATCH/'inputs',root))
            p=root/hardware.MULTI;p.write_bytes(b'unrelated candidate')
            with self.assertRaisesRegex(ValueError,'Refusing to overwrite'):
                hardware.write_candidate(hardware.PATCH/'inputs',root)
            self.assertEqual(p.read_bytes(),b'unrelated candidate')

    def test_input_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/hardware.MULTI;p.parent.mkdir(parents=True)
            p.symlink_to(hardware.PATCH/'inputs'/hardware.MULTI)
            with self.assertRaisesRegex(ValueError,'linked'):
                hardware.prepare(root)


if __name__=='__main__':unittest.main()
