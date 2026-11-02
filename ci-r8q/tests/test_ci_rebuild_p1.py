"""Bounded identity/boot-padding guards for the CI reconstruction orchestrator."""
from pathlib import Path
import hashlib
import importlib.util
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('ci_rebuild_p1',ROOT/'tools/rebuild_p1_ci.py')
build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)


class Tests(unittest.TestCase):
    def test_verified_file_requires_exact_size_and_hash(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'source';p.write_bytes(b'source')
            sha=hashlib.sha256(p.read_bytes()).hexdigest()
            build.verify_named_file(p,sha,6)
            with self.assertRaisesRegex(ValueError,'size'):
                build.verify_named_file(p,sha,7)
            with self.assertRaisesRegex(ValueError,'hash'):
                build.verify_named_file(p,'0'*64,6)

    def test_symlink_source_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'source';p.write_bytes(b'source');link=Path(td)/'alias';link.symlink_to(p)
            with self.assertRaisesRegex(ValueError,'regular'):
                build.verify_named_file(link,hashlib.sha256(p.read_bytes()).hexdigest())

    def test_dtbo_refuses_unrelated_source_without_output(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'source';p.write_bytes(b'wrong');destination=Path(td)/'candidate'
            with self.assertRaisesRegex(ValueError,'size'):
                build.padded_dtbo(p,destination)
            self.assertFalse(destination.exists())

    def test_exact_dtbo_padding_keeps_every_original_byte(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'source';source=b'D'*4783195;p.write_bytes(source);destination=Path(td)/'candidate'
            expected=hashlib.sha256(source+bytes(10485760-len(source))).hexdigest()
            with patch.object(build,'DTBO_SOURCE_SHA',hashlib.sha256(source).hexdigest()),patch.object(build,'DTBO_SHA',expected):
                build.padded_dtbo(p,destination)
            actual=destination.read_bytes()
            self.assertEqual(actual[:len(source)],source)
            self.assertFalse(any(actual[len(source):]))
            self.assertEqual(hashlib.sha256(actual).hexdigest(),expected)

    def test_public_inputs_are_the_reviewed_complete_archives(self):
        sources=build.source_specifications()
        self.assertEqual(set(sources),{'hyperos','r8q'})
        self.assertEqual(sources['hyperos']['size'],5376154497)
        self.assertEqual(sources['hyperos']['sha256'],'c5eff65d1f963c44c4c44e627cfb789ec7168706685be64030135a44e63fe11d')
        self.assertEqual(sources['r8q']['size'],931453816)
        self.assertEqual(sources['r8q']['sha256'],'d8db5aa65498718a00d55f01e8f7965a4a7918864452be69b483cc48d68674db')


if __name__=='__main__':unittest.main()
