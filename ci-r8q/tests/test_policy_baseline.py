"""Known findings must not hide a new allow, ioctl finding or compiler failure."""
from pathlib import Path
import copy
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('baseline_gate', ROOT/'ci-r8q/tools/check_policy_baseline.py')
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
LOG = '''neverallow check failed at /runner/input/vendor.cil:12
  (neverallow domain device (file (write)))
    <root>
    allow at /runner/input/system.cil:99 from system/sepolicy/private/test.te:4
      (allow app device (file (write)))

Failed to generate binary
Failed to build policydb
'''
EXTENDED = '''neverallowx check failed at /runner/input/vendor.cil:14
  (neverallowx domain domain (ioctl dir (0x0)))
libsepol.report_assertion_extended_permissions: neverallowxperm on line 14 of /runner/input/vendor.cil (or line 14 of policy.conf) violated by
  allow app config:dir { ioctl };

Failed to generate binary
Failed to build policydb
'''


class Tests(unittest.TestCase):
    def baseline(self, rows):
        return dict(schema=1, compiler_source_commit='pin', diagnostics=gate.group(rows))

    def test_paths_lines_and_diagnostic_order_do_not_create_findings(self):
        a = gate.parse_verbose(LOG)
        b = gate.parse_verbose(LOG.replace('/runner/input/', '/other/clone/').replace(':12', ':123').replace(':99', ':999'))
        result = gate.compare(b, self.baseline(a))
        self.assertEqual(result['new'], [])
        self.assertEqual(result['resolved'], [])

    def test_added_matching_allow_is_a_new_finding(self):
        rows = gate.parse_verbose(LOG)
        changed = copy.deepcopy(rows)
        changed[0]['allows'].append(dict(file='new.cil', rule='(allow added device (file (write)))'))
        result = gate.compare(changed, self.baseline(rows))
        self.assertEqual(sum(item['count'] for item in result['new']), 1)

    def test_occurrence_counts_are_preserved(self):
        rows = gate.parse_verbose(LOG)
        self.assertEqual(gate.compare(rows*2, self.baseline(rows))['new'][0]['count'], 1)
        self.assertEqual(gate.compare(rows, self.baseline(rows*2))['resolved'][0]['count'], 1)

    def test_removed_matching_allow_is_an_improvement(self):
        rows = gate.parse_verbose(LOG)
        previous = copy.deepcopy(rows)
        previous[0]['allows'].append(dict(file='other.cil', rule='(allow former device (file (write)))'))
        result = gate.compare(rows, self.baseline(previous))
        self.assertEqual(result['new'], [])
        self.assertEqual(result['resolved'], [])
        self.assertEqual(result['narrowed'][0]['count'], 1)

    def test_reduced_allow_matching_preserves_duplicate_capacity(self):
        a = gate.parse_verbose(LOG)[0]
        b = copy.deepcopy(a); b['allows'].append(dict(file='other.cil', rule='(allow former device (file (write)))'))
        c = copy.deepcopy(b); c['allows'].append(dict(file='third.cil', rule='(allow third device (file (write)))'))
        result = gate.compare([a, b], self.baseline([b, c]))
        self.assertEqual(result['new'], [])
        self.assertEqual(result['resolved'], [])
        self.assertEqual(sum(item['count'] for item in result['narrowed']), 1)

    def test_resolved_finding_is_reported_without_failure(self):
        result = gate.compare([], self.baseline(gate.parse_verbose(LOG)))
        self.assertEqual(result['new'], [])
        self.assertEqual(result['resolved'][0]['count'], 1)

    def test_extended_permissions_are_not_silently_skipped(self):
        rows = gate.parse_verbose(EXTENDED)
        self.assertEqual(rows[0]['kind'], 'neverallowx')
        self.assertEqual(rows[0]['allows'][0]['rule'], 'allow app config:dir { ioctl };')
        self.assertEqual(gate.compare(rows, self.baseline([]))['total_records'], 1)

    def test_extended_allowx_location_is_preserved(self):
        text = '''neverallowx check failed at /runner/vendor.cil:14
  (neverallowx domain domain (ioctl udp_socket (0x8b1b)))
    <root>
    allowx at /runner/system.cil:22
      (allowx app self (ioctl udp_socket (0x8b1b)))
Failed to generate binary
Failed to build policydb
'''
        self.assertEqual(gate.parse_verbose(text)[0]['allows'][0]['file'], 'system.cil')

    def test_unknown_truncated_and_incomplete_logs_fail_closed(self):
        for text in ('syntax error\n'+LOG, LOG.replace('    <root>', 'Only first 4 of 12 matching rules shown'),
                     LOG.replace('Failed to build policydb', ''),
                     LOG.replace('(allow app device (file (write)))', ''),
                     EXTENDED.replace('allow app config:dir { ioctl };', '')):
            with self.subTest(text=text), self.assertRaises(ValueError): gate.parse_verbose(text)

    def test_reviewed_full_baseline_contains_all_338_records(self):
        baseline = json.loads(gate.DEFAULT_BASELINE.read_text())
        self.assertEqual(sum(item['count'] for item in baseline['diagnostics']), 338)
        self.assertEqual(sum(item['count'] for item in baseline['diagnostics'] if item['record']['kind']=='neverallowx'), 3)
        self.assertEqual(len(baseline['diagnostics']), 337)

    def test_gate_keeps_not_boot_ready_and_requires_init_capabilities(self):
        rows = gate.parse_verbose(LOG)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); baseline = root/'baseline.json'; baseline.write_text(json.dumps(self.baseline(rows)))
            report = root/'result.json'
            original = dict(source_commit='pin', status='FAILED_OR_NEVERALLOW_FINDINGS', commands=[
                dict(variant='original', mode='init', returncode=255, expected_namespace_failure=True),
                dict(variant='candidate', mode='init', returncode=0, serialized_version=30, caps_check_returncode=0),
                dict(variant='candidate', mode='neverallow-audit', returncode=255, command=['secilc','-m'])])
            completion = type('Result', (), dict(returncode=255, stdout=LOG, stderr=''))()
            report.write_text(json.dumps(original))
            with patch.object(gate.subprocess, 'run', return_value=completion):
                self.assertEqual(gate.check_report(report, baseline), 0)
            result = json.loads((root/'neverallow-regression.json').read_text())
            self.assertFalse(result['boot_ready'])
            self.assertTrue(result['regression_check_passed'])
            original['commands'][1]['caps_check_returncode'] = 1
            report.write_text(json.dumps(original))
            with patch.object(gate.subprocess, 'run', return_value=completion):
                self.assertEqual(gate.check_report(report, baseline), 1)

    def test_failed_compiler_without_findings_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); baseline=root/'baseline.json'; baseline.write_text(json.dumps(self.baseline([])))
            report=root/'result.json'; report.write_text(json.dumps(dict(source_commit='pin',commands=[
                dict(variant='original',mode='init',returncode=255,expected_namespace_failure=True),
                dict(variant='candidate',mode='init',returncode=0,serialized_version=30,caps_check_returncode=0),
                dict(variant='candidate',mode='neverallow-audit',returncode=255,command=['secilc'])])))
            failed = type('Result', (), dict(returncode=255,stdout='',stderr=''))()
            with patch.object(gate.subprocess, 'run', return_value=failed), self.assertRaises(ValueError):
                gate.check_report(report, baseline)


if __name__ == '__main__': unittest.main()
