from pathlib import Path
import importlib.util
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('charger_candidate',ROOT/'tools/prepare_charger_candidate.py')
charger=importlib.util.module_from_spec(spec);spec.loader.exec_module(charger)


class ChargerCandidateTests(unittest.TestCase):
    def test_only_strictly_redundant_rc_is_deleted(self):
        manifest=charger.prepare(charger.PATCH/'inputs')
        self.assertEqual(len(manifest['files']),1)
        self.assertEqual(manifest['files'][0]['path'],charger.LEGACY)
        self.assertEqual(manifest['files'][0]['action'],'delete')
        self.assertEqual(manifest['required_retained_files'][0]['path'],charger.CURRENT)

    def test_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name in charger.PINS:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes((charger.PATCH/'inputs'/name).read_bytes())
            path=root/charger.CURRENT;path.write_bytes(path.read_bytes()+b'\non boot\n    stop wlschgd\n')
            with self.assertRaisesRegex(ValueError,'identity differs'):charger.prepare(root)


if __name__=='__main__':unittest.main()
