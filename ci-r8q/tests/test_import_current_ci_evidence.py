"""Exact-commit CI selection and untrusted ZIP-name handling need no network."""
from pathlib import Path
import importlib.util
import io
import unittest
from unittest.mock import patch
import warnings
import zipfile

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('current_ci',ROOT/'ci-r8q/tools/import_current_ci_evidence.py')
current=importlib.util.module_from_spec(spec);spec.loader.exec_module(current)


def archive(entries):
    stream=io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',UserWarning)
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as output:
            for name,data in entries:output.writestr(name,data)
    return stream.getvalue()


class CurrentEvidenceTests(unittest.TestCase):
    def test_exact_successful_main_workflow_only(self):
        sha='a'*40
        valid=dict(id=3,head_sha=sha,head_branch='main',path=current.WORKFLOW,status='completed',conclusion='success')
        self.assertEqual(current.choose_run([valid],sha),valid)
        for key,value in [('head_sha','b'*40),('head_branch','review'),('path','.github/workflows/other.yml'),
                          ('status','in_progress'),('conclusion','failure'),('conclusion','cancelled')]:
            self.assertIsNone(current.choose_run([dict(valid,**{key:value})],sha))

    def test_newest_success_at_exact_sha_is_selected(self):
        sha='a'*40
        run=dict(head_sha=sha,head_branch='main',path=current.WORKFLOW,status='completed',conclusion='success')
        self.assertEqual(current.choose_run([dict(run,id=10),dict(run,id=11)],sha)['id'],11)

    def test_only_expected_policy_context_and_vintf_paths_are_imported(self):
        blob=archive([('ci-results/policy/result.json',b'{}'),('context-results/result.json',b'{}'),
                      ('context-results/compiler',b'ELF'),('unrelated/input.json',b'{}')])
        self.assertEqual(set(current.decode_reports(current.ARTIFACTS[0],blob)),
                         {'ci-results/policy/result.json','context-results/result.json'})
        blob=archive([('gate.json',b'{}'),('official-build.prop',b'source properties'),('input/manifest.json',b'{}')])
        self.assertEqual(current.decode_reports(current.ARTIFACTS[1],blob),{'vintf-results/gate.json':b'{}'})

    def test_zip_traversal_absolute_backslash_and_noncanonical_names_are_rejected(self):
        for name in ['../escape.json','/gate.json','input\\gate.json','ci-results//policy/result.json',
                     './gate.json']:
            with self.subTest(name=name),self.assertRaises(ValueError):
                current.decode_reports(current.ARTIFACTS[0],archive([(name,b'{}')]))

    def test_duplicate_and_symlink_members_are_rejected(self):
        blob=archive([('gate.json',b'{}'),('gate.json',b'{}')])
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            current.decode_reports(current.ARTIFACTS[1],blob)
        link=zipfile.ZipInfo('gate.json');link.create_system=3;link.external_attr=0o120777<<16
        with self.assertRaisesRegex(ValueError,'Symlink'):
            current.decode_reports(current.ARTIFACTS[1],archive([(link,b'/private')]))

    def test_expansion_bound_applies_to_members_before_reading(self):
        blob=archive([('gate.json',b' '*2048)])
        self.assertLess(len(blob),1024)
        with patch.object(current,'LIMIT',1024),self.assertRaisesRegex(ValueError,'Expanded'):
            current.decode_reports(current.ARTIFACTS[1],blob)

    def test_nontext_and_unknown_artifacts_are_rejected(self):
        blob=archive([('gate.json',b'\0binary')])
        with self.assertRaisesRegex(ValueError,'Non-text'):
            current.decode_reports(current.ARTIFACTS[1],blob)
        with self.assertRaisesRegex(ValueError,'Unexpected'):
            current.decode_reports('old-run-evidence',blob)


if __name__=='__main__':unittest.main()
