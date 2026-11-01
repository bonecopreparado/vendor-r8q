"""Regression identity must include status and source references, not just names."""
from pathlib import Path
import ast
import copy
import json
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads((ROOT/'ci-r8q/inputs/context-baseline.json').read_text())
MEASURED = json.loads((ROOT/'reports/audit-20261101/round2/contexts/first-binary-check/result.json').read_text())
SOURCE = ROOT/'ci-r8q/tools/run_context_audit.py'
NODE = next(n for n in ast.parse(SOURCE.read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name == 'unchanged_measured_finding')
NAMESPACE = {'known': BASELINE['known_invalid_contexts']}
exec(compile(ast.fix_missing_locations(ast.Module(body=[NODE], type_ignores=[])), str(SOURCE), 'exec'), NAMESPACE)
UNCHANGED = NAMESPACE['unchanged_measured_finding']


class ContextRegressionBaselineTests(unittest.TestCase):
    def test_first_real_measurement_retained_all_nine_unresolved(self):
        self.assertEqual(BASELINE['schema_version'], 2)
        self.assertEqual(BASELINE['measurement']['invalid'], 9)
        self.assertEqual(len(BASELINE['known_invalid_contexts']), 9)
        self.assertTrue(all(UNCHANGED(row) for row in MEASURED['invalid']))
        self.assertTrue(all(row['disposition'].startswith('UNRESOLVED')
                            for row in BASELINE['known_invalid_contexts'].values()))

    def test_new_invalid_context_is_not_known(self):
        row = copy.deepcopy(MEASURED['invalid'][0]); row['context'] = 'u:r:new_invalid_domain:s0'
        self.assertFalse(UNCHANGED(row))

    def test_different_parse_error_is_not_hidden_by_known_name(self):
        row = copy.deepcopy(MEASURED['invalid'][0]); row['parse_status'] = -1
        self.assertFalse(UNCHANGED(row))

    def test_different_check_status_is_not_hidden_by_known_name(self):
        row = copy.deepcopy(MEASURED['invalid'][0]); row['check_status'] = -2
        self.assertFalse(UNCHANGED(row))

    def test_new_source_reference_is_a_changed_finding(self):
        row = copy.deepcopy(MEASURED['invalid'][0]); row['references'].append(dict(
            partition='system', path='/etc/selinux/new_contexts', line=1, kind='literal_context'))
        self.assertFalse(UNCHANGED(row))

    def test_changed_reference_location_is_a_changed_finding(self):
        row = copy.deepcopy(MEASURED['invalid'][0]); row['references'][0]['line'] += 1
        self.assertFalse(UNCHANGED(row))

    def test_first_real_measurement_has_ci_and_exact_policy_provenance(self):
        self.assertEqual(BASELINE['policy_sha256'], MEASURED['policy_sha256'])
        self.assertEqual(BASELINE['measurement']['checker_sha256'], MEASURED['checker_sha256'])
        self.assertIn('/actions/runs/41319419220', BASELINE['measurement']['workflow_run'])


if __name__ == '__main__': unittest.main()
