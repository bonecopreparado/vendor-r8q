"""Check plan integration without requiring private OEM image fixtures."""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/display_group'))
import prepare_image_plans as stage


class Tests(unittest.TestCase):
    def setUp(self):
        self.plans = {p:dict(schema_version=1, source_image_sha256='1'*64,
            operations=[dict(op='delete',path='/etc/old-'+p,old_sha256='2'*64)])
            for p in ('system','system_ext','vendor','odm','product')}
        self.bridge = b'import /vendor/ueventd.rc\n'
        self.legacy, self.init = b'legacy', b'init'
        self.rules = b'# donor\nimport /vendor/etc/ueventd.rc # exact\n'
        pins = patch.multiple(stage, LEGACY_SHA=stage.sha(self.legacy),
            INIT_SHA=stage.sha(self.init), BRIDGE_SHA=stage.sha(self.bridge))
        pins.start()
        self.addCleanup(pins.stop)
        transform = patch.object(stage.sf, 'transform', return_value=b'corrected-library')
        self.transform = transform.start()
        self.addCleanup(transform.stop)

    def augment(self, **changes):
        args = dict(plans=self.plans, library=b'exact-library', legacy=self.legacy,
            final_init=self.init, system_rules=self.rules, bridge=self.bridge)
        args.update(changes)
        return stage.augment(**args)

    def test_only_two_new_operations_originals_and_metadata_preserved(self):
        original = copy.deepcopy(self.plans)
        plans, payloads = self.augment()
        self.assertEqual(self.plans, original)
        for p in original:
            self.assertEqual(plans[p]['operations'][:1], original[p]['operations'])
            self.assertEqual(plans[p]['source_image_sha256'], original[p]['source_image_sha256'])
            self.assertEqual(len(plans[p]['operations']), 2 if p in ('vendor','system_ext') else 1)
        sf = plans['system_ext']['operations'][-1]
        self.assertEqual((sf['op'],sf['path'],sf['old_sha256']), ('replace','/lib64/libsurfaceflinger.so',stage.sf.ORIGINAL_SHA256))
        bridge = plans['vendor']['operations'][-1]
        self.assertEqual((bridge['op'],bridge['metadata_from']), ('add','/ueventd.rc'))
        self.assertEqual(payloads[sf['source']], b'corrected-library')
        self.assertEqual(payloads[bridge['source']], self.bridge)
        self.transform.assert_called_once_with(b'exact-library')

    def test_foreign_vendor_and_existing_canonical_file_rejected(self):
        for change in (dict(legacy=b'other'),dict(final_init=b'other'),dict(bridge=b'other'),dict(canonical_exists=True)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.augment(**change)

    def test_real_import_required_once(self):
        for rules in (b'# import /vendor/etc/ueventd.rc\n', b'import /vendor/ueventd.rc\n', self.rules*2):
            with self.subTest(rules=rules), self.assertRaises(ValueError):
                self.augment(system_rules=rules)

    def test_conflicting_targets_duplicates_missing_and_unknown_plans(self):
        for part,target in (('vendor','/etc/ueventd.rc'),('system_ext','/lib64/libsurfaceflinger.so')):
            plans = copy.deepcopy(self.plans)
            plans[part]['operations'].append(dict(op='delete',path=target))
            with self.assertRaises(ValueError):
                self.augment(plans=plans)
        for variant in ('missing','unknown','duplicate','unpinned'):
            plans = copy.deepcopy(self.plans)
            if variant=='missing':del plans['odm']
            elif variant=='unknown':plans['boot']=copy.deepcopy(plans['vendor'])
            elif variant=='duplicate':plans['vendor']['operations']*=2
            else:plans['vendor']['source_image_sha256']='unknown'
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                self.augment(plans=plans)

    def test_binary_patch_failure_propagates_without_changing_plans(self):
        original = copy.deepcopy(self.plans)
        self.transform.side_effect = ValueError('unknown library')
        with self.assertRaisesRegex(ValueError,'unknown library'):
            self.augment()
        self.assertEqual(self.plans,original)

    def test_payload_paths_cannot_escape(self):
        with tempfile.TemporaryDirectory() as work:
            root=Path(work)
            (root/'good').write_bytes(b'ok')
            (root/'link').symlink_to(root/'good')
            self.assertEqual(stage.relative_file(root,'good'),root/'good')
            for name in ('../good','/good','./good','a//good','link','missing','a\\good'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    stage.relative_file(root,name)

    def test_hash_guard_survives_python_optimization(self):
        program = '''import sys
sys.path.insert(0,sys.argv[1])
from prepare_p1_plans import require_digest, SHA
require_digest(b'expected',SHA(b'expected'),'valid')
try:
 require_digest(b'changed',SHA(b'expected'),'corrupt')
except ValueError:
 pass
else:
 raise SystemExit('Optimized Python skipped the hash guard')
'''
        for flags in ([],['-O']):
            r=subprocess.run([sys.executable,*flags,'-c',program,str(ROOT/'tools')],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr+r.stdout)


if __name__=='__main__':
    unittest.main()
