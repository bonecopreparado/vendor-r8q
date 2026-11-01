"""Offline tests for official tool selection and exact metadata coverage."""
from pathlib import Path
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('r8q_checkvintf_runner',ROOT/'ci-r8q/tools/run_checkvintf.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class CheckVintfRunnerTests(unittest.TestCase):
    def classify(self,rc,stdout='',matching=True,extra=None):
        runs=[dict(name='full-metadata-with-candidate-kernel',exit=rc,stdout=stdout)]
        if extra:runs.append(extra)
        return runner.classify_results(matching,runs)['status']

    def test_signal_is_execution_failure(self):
        self.assertEqual(self.classify(-11),'BLOCKED_TOOL_EXECUTION_FAILURE')

    def test_missing_process_is_execution_failure(self):
        self.assertEqual(self.classify(None),'BLOCKED_TOOL_EXECUTION_FAILURE')

    def test_usage_exit_is_not_known_incompatibility(self):
        self.assertEqual(self.classify(64),'BLOCKED_TOOL_EXECUTION_FAILURE')

    def test_software_exit_retains_metadata_error_distinction(self):
        self.assertEqual(self.classify(70),'BLOCKED_VINTF_METADATA_ERROR')

    def test_dataerr_requires_incompatible_marker(self):
        self.assertEqual(self.classify(65,'INCOMPATIBLE\n'),'BLOCKED_VINTF_INCOMPATIBLE')
        self.assertEqual(self.classify(65),'BLOCKED_TOOL_EXECUTION_FAILURE')

    def test_success_requires_compatible_marker(self):
        self.assertEqual(self.classify(0,'COMPATIBLE\n'),'HOST_CHECK_PASSED_WITH_RUNTIME_LIMITS')
        self.assertEqual(self.classify(0),'BLOCKED_TOOL_EXECUTION_FAILURE')

    def test_help_usage_exit_is_expected_but_aux_signal_is_not(self):
        self.assertEqual(self.classify(0,'COMPATIBLE\n',extra=dict(name='help',exit=64)),'HOST_CHECK_PASSED_WITH_RUNTIME_LIMITS')
        self.assertEqual(self.classify(0,'COMPATIBLE\n',extra=dict(name='framework-consistency',exit=-6)),'BLOCKED_TOOL_EXECUTION_FAILURE')

    def test_other_api_does_not_pass(self):
        self.assertEqual(self.classify(0,'COMPATIBLE\n',matching=False),'BLOCKED_TOOL_VERSION_MISMATCH')

    def test_exact_bundle_and_candidate_kernel(self):
        with tempfile.TemporaryDirectory() as td:
            base,manifest,identity=runner.unpack_inputs(Path(td))
            self.assertEqual(identity,runner.INPUT_SHA256)
            self.assertTrue(manifest['kernel']['release'].startswith('4.19.325-'))
            self.assertEqual(hashlib.sha256((base/'kernel.config').read_bytes()).hexdigest(),manifest['kernel']['config_sha256'])
            self.assertEqual(manifest['properties']['ro.product.first_api_level'],'29')
            self.assertEqual(len(manifest['apex']),46)

    def test_factory_apex_fragment_has_partition_selection(self):
        with tempfile.TemporaryDirectory() as td:
            base,manifest,_=runner.unpack_inputs(Path(td))
            nodes=ET.fromstring((base/'root/apex/apex-info-list.xml').read_bytes())
            partitions={n.get('moduleName'):n.get('partition') for n in nodes}
            self.assertEqual(partitions['com.android.virt'],'SYSTEM')
            self.assertEqual(partitions['com.samsung.android.biometrics.fingerprint'],'VENDOR')
            fragments=[r for r in manifest['files'] if r['host'].startswith('apex/com.android.virt/etc/vintf/')]
            self.assertEqual(len(fragments),1)

    def test_at_symbol_manifest_filenames_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            _,manifest,_=runner.unpack_inputs(Path(td))
            names={r['host'] for r in manifest['files']}
            self.assertIn('vendor/etc/vintf/manifest/android.hardware.gnss@2.1-service-qti.xml',names)
            self.assertIn('system_ext/etc/vintf/manifest/android.hidl.allocator@1.0-service.xml',names)
            self.assertEqual(len([n for n in names if '@' in n]),24)

    def test_discovery_prefers_verified_android17_api37(self):
        target='aosp_cf_x86_64_only_phone-userdebug'
        def fetch(url):
            if url.endswith('status.json'):return json.dumps({'targets':[{'name':target,'last_known_good_build':'12345678'}]}).encode()
            return b'ro.system.build.version.release=17\nro.system.build.version.sdk=37\n'
        with tempfile.TemporaryDirectory() as td,patch.object(runner,'fetch',side_effect=fetch):
            row=runner.discover(Path(td))
            self.assertEqual((row['release'],row['sdk']),('17','37'))
            self.assertEqual(row['build_id'],'12345678')

    def test_discovery_does_not_call_android16_aligned(self):
        target='aosp_cf_x86_64_only_phone-userdebug'
        def fetch(url):
            if url.endswith('status.json'):return json.dumps({'targets':[{'name':target,'last_known_good_build':'12345678'}]}).encode()
            return b'ro.system.build.version.release=16\nro.system.build.version.sdk=36\n'
        with tempfile.TemporaryDirectory() as td,patch.object(runner,'fetch',side_effect=fetch):
            row=runner.discover(Path(td))
            self.assertEqual((row['release'],row['sdk']),('16','36'))

    def test_unsafe_discovery_build_id_is_rejected(self):
        bad=json.dumps({'targets':[{'name':'aosp_cf_x86_64_only_phone-userdebug','last_known_good_build':'../unsafe'}]}).encode()
        with tempfile.TemporaryDirectory() as td,patch.object(runner,'fetch',return_value=bad):
            with self.assertRaises(RuntimeError):runner.discover(Path(td))

    def test_download_rejects_reviewed_tool_sha_mismatch(self):
        row=dict(build_id='12345678',target='aosp_cf_x86_64_only_phone-userdebug',sha256='0'*64)
        with tempfile.TemporaryDirectory() as td,patch.object(runner.OPENER,'open',return_value=io.BytesIO(b'untrusted archive')):
            with self.assertRaisesRegex(ValueError,'reviewed lock SHA256'):runner.download_tools(row,Path(td))

    def test_foreign_artifact_redirect_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'redirect host'):
            runner.OfficialRedirects().redirect_request(None,None,302,'',{},'https://example.org/otatools.zip')


if __name__=='__main__':unittest.main()
