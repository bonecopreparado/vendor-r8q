"""Bounded parser/coverage controls for fresh actual-image policy validation."""
from pathlib import Path
import importlib.util,unittest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('p1_policy',ROOT/'tools/verify_p1_policy.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
class Tests(unittest.TestCase):
    def test_seapp_process_and_file_types_have_distinct_roles(self):
        rows=v.labels_from_text('vendor','/etc/selinux/vendor_seapp_contexts',b'user=_app domain=vendor_qtelephony type=app_data_file levelFrom=all\n')
        self.assertEqual({r[0]for r in rows},{'u:r:vendor_qtelephony:s0','u:object_r:app_data_file:s0'})
    def test_comments_cannot_inject_labels(self):
        self.assertEqual(v.labels_from_text('vendor','/etc/selinux/file_contexts',b'# u:r:bad:s0\n'),[])
    def test_binary_context_indexes_are_not_guessed_as_text(self):
        self.assertEqual(v.labels_from_text('vendor','file_contexts.bin',b'\0u:r:bad:s0'),[])
    def test_init_explicit_service_and_exec_contexts_are_collected(self):
        rows=v.labels_from_rc('vendor','/etc/init/hw/init.qcom.rc',b' seclabel u:r:vendor_init:s0\n exec u:r:radio:s0 root -- /bin/test\n exec_start daemon\n')
        self.assertEqual([r[0]for r in rows],['u:r:vendor_init:s0','u:r:radio:s0'])
    def test_checker_missing_rows_cannot_pass(self):
        with self.assertRaisesRegex(ValueError,'coverage'):v.check_rows('',{'u:r:init:s0'})
    def test_checker_duplicate_rows_cannot_pass(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):v.check_rows('u:r:init:s0\t0\t0\nu:r:init:s0\t0\t0',{'u:r:init:s0'})
    def test_checker_unknown_rows_cannot_pass(self):
        with self.assertRaisesRegex(ValueError,'Unknown'):v.check_rows('u:r:unexpected:s0\t0\t0',{'u:r:init:s0'})
    def test_failed_label_is_preserved_for_gate(self):
        rows=v.check_rows('u:r:bad:s0\t0\t-1',{'u:r:bad:s0'})
        self.assertEqual(rows[0]['check_status'],-1)
if __name__=='__main__':unittest.main()
