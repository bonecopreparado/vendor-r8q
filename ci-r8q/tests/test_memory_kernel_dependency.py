"""Reject substituted runs, expired artifacts and unbound kernel dependencies."""
from pathlib import Path
import copy
import importlib.util
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('memory_dependency',ROOT/'ci-r8q/tools/fetch_memory_kernel.py')
dependency=importlib.util.module_from_spec(spec);spec.loader.exec_module(dependency)


class Tests(unittest.TestCase):
    def run_record(self):
        return dict(head_sha=dependency.SOURCE_COMMIT,head_branch=dependency.BRANCH,
                    path=dependency.WORKFLOW,status='completed',conclusion='success',
                    repository={'full_name':dependency.trusted.REPO})

    def test_only_completed_successful_exact_source_workflow_in_our_repository_is_accepted(self):
        good=self.run_record();self.assertTrue(dependency.valid_run(good))
        for key,wrong in dict(head_sha='0'*40,head_branch='main',path='.github/workflows/unrelated.yml',
                              status='in_progress',conclusion='failure',repository={'full_name':'someone/fork'}).items():
            with self.subTest(key=key):self.assertFalse(dependency.valid_run(good|{key:wrong}))

    def artifact(self):
        return dict(name=dependency.ARTIFACT,expired=False,id=3,size_in_bytes=1000,digest='sha256:'+'a'*64)

    def test_unexpired_artifact_with_github_digest_and_bounded_size_is_required(self):
        good=self.artifact();self.assertEqual(dependency.select_artifact([good]),good)
        for key,wrong in dict(name='some-other-kernel',expired=True,id=0,size_in_bytes=0,digest='').items():
            with self.subTest(key=key),self.assertRaises(ValueError):dependency.select_artifact([good|{key:wrong}])
        for key,wrong in [('size_in_bytes',512*1024**2+1),('size_in_bytes',True),('id','3')]:
            with self.subTest(key=key,wrong=wrong),self.assertRaises(ValueError):dependency.select_artifact([good|{key:wrong}])

    def test_missing_or_duplicate_matching_artifact_is_not_guessed(self):
        for rows in ([],[self.artifact(),self.artifact()|{'id':4}]):
            with self.assertRaises(ValueError):dependency.select_artifact(rows)


if __name__=='__main__':unittest.main()
