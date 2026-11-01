"""Reports packaging must not distribute a flashable archive or source inputs."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('delivery_bundle',ROOT/'ci-r8q/tools/make_delivery_bundle.py')
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


class DeliveryBundleTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix='r8q-reports-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.put(root,'ci-r8q/inputs/release-readiness.json',json.dumps({'status':'HOLD','boot_ready':False}))
        return root

    def put(self,root,name,data):
        path=root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data if isinstance(data,bytes) else data.encode())
        return path

    def test_only_current_text_reports_and_licenses_are_included(self):
        root=self.fixture()
        for name in ['ci-results/unit-tests.txt','context-results/result.json','vintf-results/gate.json',
                     'LICENSE','THIRD_PARTY_NOTICES.md','licenses/upstream.txt']:
            self.put(root,name,'current report or notice')
        self.put(root,'reports/old-run/stale.json','stale evidence')
        result=delivery.build_bundle(root)
        with tarfile.open(result['file']) as archive:
            names=set(archive.getnames())
        self.assertIn('reports/ci-results/unit-tests.txt',names)
        self.assertIn('reports/context-results/result.json',names)
        self.assertIn('reports/vintf-results/gate.json',names)
        self.assertIn('licenses/upstream.txt',names)
        self.assertFalse(any('stale' in name or name.startswith('META-INF/') for name in names))
        self.assertTrue(result['file'].endswith('NOT-FLASHABLE.tar.gz'))

    def test_inputs_binaries_nested_archives_and_phone_logs_are_excluded(self):
        root=self.fixture()
        excluded=['ci-results/input/private.json','context-results/inputs/contexts.txt',
                  'vintf-results/otatools/lib/private.json','ci-results/extracted/config.txt',
                  'ci-results/recovery (1).log','ci-results/logcat-20261031.log',
                  'ci-results/dmesg.log','context-results/all-contexts.json',
                  'ci-results/r8q-device-20261030.json','ci-results/source/firmware.txt',
                  'ci-results/installer.zip','ci-results/secilc-host',
                  'ci-results/pretend-binary.txt']
        for name in excluded:
            self.put(root,name,b'\x7fELF\0binary' if 'pretend-binary' in name else 'excluded')
        members=delivery.collect_members(root)
        self.assertFalse(any(name.startswith('reports/') for name in members))
        manifest=json.loads(members['PACKAGE-MANIFEST.json'])
        self.assertEqual(manifest['skipped_reports'][0]['reason'],'not a text report')

    def test_symlink_file_and_symlink_report_root_are_excluded(self):
        root=self.fixture()
        outside=self.put(root,'private.txt','must not be packaged')
        reports=root/'ci-results';reports.mkdir()
        (reports/'external.txt').symlink_to(outside)
        (root/'context-results').symlink_to(reports,target_is_directory=True)
        members=delivery.collect_members(root)
        self.assertFalse(any(name.startswith('reports/') for name in members))
        self.assertFalse(json.loads(members['PACKAGE-MANIFEST.json'])['current_report_roots']['context-results'])

    def test_deterministic_archive_and_internal_checksums(self):
        root=self.fixture()
        path=self.put(root,'ci-results/tests.txt','one report\n')
        first=delivery.build_bundle(root)
        first_bytes=Path(first['file']).read_bytes()
        os.utime(path,(123,456))
        second=delivery.build_bundle(root)
        self.assertEqual(first_bytes,Path(second['file']).read_bytes())
        self.assertEqual(first['sha256'],hashlib.sha256(first_bytes).hexdigest())
        with tarfile.open(second['file']) as archive:
            checksums=archive.extractfile('SHA256SUMS.txt').read().decode().splitlines()
            for line in checksums:
                sha,name=line.split('  ',1)
                self.assertEqual(sha,hashlib.sha256(archive.extractfile(name).read()).hexdigest())
            self.assertTrue(all(entry.isfile() and entry.mode==0o644 and entry.mtime==0 for entry in archive))

    def test_missing_readiness_is_not_treated_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'readiness'):
                delivery.collect_members(Path(directory))

    def test_stale_candidate_readiness_is_rejected(self):
        root=self.fixture()
        self.put(root,'output/release-readiness.json',json.dumps({'status':'READY','boot_ready':True}))
        with self.assertRaisesRegex(ValueError,'differs'):
            delivery.collect_members(root)

    def test_missing_reports_are_explicit_in_manifest(self):
        root=self.fixture()
        manifest=json.loads(delivery.collect_members(root)['PACKAGE-MANIFEST.json'])
        self.assertEqual(manifest['current_report_roots'],dict.fromkeys(delivery.REPORT_ROOTS,False))
        self.assertFalse(manifest['boot_ready'])


if __name__=='__main__':
    unittest.main()
