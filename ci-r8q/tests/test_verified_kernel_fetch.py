from pathlib import Path
import copy
import importlib.util
import json
import tempfile
import unittest
import zipfile
import test_susfs22_linked_verifier as linked

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('verified_fetch_test',ROOT/'ci-r8q/tools/fetch_verified_kernel.py')
fetch=importlib.util.module_from_spec(spec);spec.loader.exec_module(fetch)


class Tests(unittest.TestCase):
    def test_remote_run_and_completed_dependency_are_bound_to_source(self):
        commit='a'*40
        run=dict(status='completed',conclusion='success',head_sha=commit,head_branch=fetch.BRANCH,
                 path=fetch.WORKFLOW,repository=dict(full_name=fetch.REPO))
        fetch.validate_run(run,commit)
        for key,value in (('head_sha','b'*40),('head_branch','unknown'),('conclusion','failure'),('path','other.yml')):
            changed=copy.deepcopy(run);changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):fetch.validate_run(changed,commit)
        run.update(status='in_progress',conclusion=None,head_branch=fetch.COMPLETE_BRANCH,path=fetch.COMPLETE_WORKFLOW)
        fetch.validate_run(run,commit,same_run=True)
        fetch.validate_kernel_job([dict(name=fetch.KERNEL_JOB,status='completed',conclusion='success')])
        for jobs in ([],[dict(name=fetch.KERNEL_JOB,status='completed',conclusion='failure')],
                     [dict(name=fetch.KERNEL_JOB,status='in_progress',conclusion=None)]):
            with self.assertRaises(ValueError):fetch.validate_kernel_job(jobs)

    def test_real_linked_file_hashes_and_embedded_config_are_required(self):
        kernel,summary=linked.fixture()
        summary['independent_linked_image_verification_passed']=True
        bodies={'Image':kernel,'vmlinux':b'linked fixture','System.map':b'symbol fixture'}
        for name,data in bodies.items():summary['outputs'][name]=dict(bytes=len(data),sha256=fetch.hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory()as work:
            root=Path(work);archive=root/'kernel.zip';output=root/'out';output.mkdir()
            with zipfile.ZipFile(archive,'w')as z:
                for name,data in bodies.items():z.writestr(name,data)
                z.writestr('summary.json',json.dumps(summary))
            result=fetch.extract_verified(archive,output)
            self.assertIs(result['susfs_enabled'],True)
            self.assertEqual((output/'Image').read_bytes(),kernel)
            self.assertFalse((output/'vmlinux').exists())

    def test_missing_actual_config_check_or_unsafe_member_is_rejected(self):
        for unsafe in (False,True):
            kernel,summary=linked.fixture()
            if unsafe:summary['independent_linked_image_verification_passed']=True
            with tempfile.TemporaryDirectory()as work:
                root=Path(work);archive=root/'kernel.zip';out=root/'out';out.mkdir()
                with zipfile.ZipFile(archive,'w')as z:
                    for name,data in {'Image':kernel,'vmlinux':b'fixture','System.map':b'fixture','summary.json':json.dumps(summary)}.items():z.writestr(name,data)
                    if unsafe:z.writestr('../escape',b'refuse')
                with self.assertRaises(ValueError):fetch.extract_verified(archive,out)


if __name__=='__main__':unittest.main()
