"""Detect new SELinux audit diagnostics without treating known findings as fixed.

The baseline is a reviewed multiset of the full verbose neverallow diagnostics,
including every printed matching allow. Absolute paths, line numbers and output
order do not identify a finding; CIL file names and rule text do. All original
logs remain available. This tool never edits policy or touches a phone.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = ROOT / 'ci-r8q/baselines/neverallows-v1.json'
FOOTERS = {'Failed to generate binary', 'Failed to build policydb'}


def _location(line):
    match = re.search(r'(?:^|/)([^/\s]+\.cil):[0-9]+(?:\s|$)', line)
    if not match:
        raise ValueError('Unrecognized CIL diagnostic location')
    return match.group(1)


def parse_verbose(text):
    """Fail closed on truncated, incomplete or unknown compiler diagnostics."""
    records = []
    current = None
    pending_allow = None
    pending_expanded_allow = False
    awaiting_assertion = False
    footers = []
    for rawline in text.splitlines():
        line = rawline.strip()
        if not line:
            continue
        if re.match(r'^neverallowx? check failed at ', line):
            if awaiting_assertion or pending_allow is not None or pending_expanded_allow:
                raise ValueError('Incomplete compiler diagnostic')
            current = dict(kind=line.split()[0], file=_location(line), neverallow=None, allows=[])
            records.append(current)
            awaiting_assertion = True
        elif awaiting_assertion and line.startswith('('+current['kind']+' ') and line.endswith(')'):
            current['neverallow'] = ' '.join(line.split())
            awaiting_assertion = False
        elif current is not None and re.match(r'^allowx? at ', line):
            if pending_allow is not None:
                raise ValueError('Missing matching allow rule')
            pending_allow = _location(line)
        elif pending_allow is not None and re.match(r'^\(allowx? ', line) and line.endswith(')'):
            current['allows'].append(dict(file=pending_allow, rule=' '.join(line.split())))
            pending_allow = None
        elif current is not None and current['kind']=='neverallowx' and re.fullmatch(
                r'libsepol\.report_assertion_extended_permissions: neverallowxperm on line [0-9]+ of .+ \(or line [0-9]+ of policy\.conf\) violated by', line):
            pending_expanded_allow = True
        elif pending_expanded_allow and line.startswith('allow ') and line.endswith(';'):
            # libsepol prints a resolved policy rule when the violation is a
            # normal ioctl allow against a neverallowxperm assertion.
            current['allows'].append(dict(file='<expanded-policy>', rule=' '.join(line.split())))
            pending_expanded_allow = False
        elif current is not None and line == '<root>':
            continue
        elif line in FOOTERS:
            footers.append(line)
        else:
            raise ValueError('Unknown or truncated compiler diagnostic: ' + line[:160])
    if awaiting_assertion or pending_allow is not None or pending_expanded_allow:
        raise ValueError('Incomplete compiler diagnostic')
    if records and set(footers) != FOOTERS:
        raise ValueError('Expected complete compiler failure footer')
    for record in records:
        if not record['allows']:
            raise ValueError('Neverallow has no matching allow detail')
        record['allows'].sort(key=lambda item: (item['file'], item['rule']))
    return records


def record_key(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'))


def group(records):
    counts = Counter(record_key(record) for record in records)
    return [dict(record=json.loads(key), count=count) for key, count in sorted(counts.items())]


def compare(records, baseline):
    if baseline.get('schema') != 1:
        raise ValueError('Unsupported neverallow baseline schema')
    expected = Counter()
    for item in baseline['diagnostics']:
        if type(item['count']) is not int or item['count'] <= 0:
            raise ValueError('Invalid baseline occurrence count')
        key = record_key(item['record'])
        if key in expected:
            raise ValueError('Duplicate baseline key')
        expected[key] = item['count']
    actual = Counter(record_key(record) for record in records)
    def expanded(counter):
        return [dict(record=json.loads(key), count=count) for key, count in sorted(counter.items())]
    # Exact occurrences match first. A remaining assertion with fewer matching
    # allows is an improvement too, provided every remaining allow occurred in
    # that same baseline assertion. Match occurrences independently so repeated
    # compiler diagnostics cannot hide a new occurrence or allow.
    exact = actual & expected
    actual_left = [json.loads(key) for key, count in sorted((actual-exact).items()) for _ in range(count)]
    expected_left = [json.loads(key) for key, count in sorted((expected-exact).items()) for _ in range(count)]
    def assertion(record):
        return record['kind'], record['file'], record['neverallow']
    def allows(record):
        return Counter(record_key(item) for item in record['allows'])
    actual_allows = [allows(record) for record in actual_left]
    expected_allows = [allows(record) for record in expected_left]
    edges = [[index for index, old in enumerate(expected_left)
              if assertion(record)==assertion(old) and actual_allows[pos] <= expected_allows[index]]
             for pos, record in enumerate(actual_left)]
    matching = {}
    def assign(pos, visited):
        for index in edges[pos]:
            if index in visited:
                continue
            visited.add(index)
            if index not in matching or assign(matching[index], visited):
                matching[index] = pos
                return True
        return False
    for pos in range(len(actual_left)):
        assign(pos, set())
    matched_actual = set(matching.values())
    new = Counter(record_key(record) for pos, record in enumerate(actual_left) if pos not in matched_actual)
    resolved = Counter(record_key(record) for index, record in enumerate(expected_left) if index not in matching)
    narrowed = Counter((record_key(expected_left[index]), record_key(actual_left[pos]))
                       for index, pos in matching.items())
    return dict(new=expanded(new), resolved=expanded(resolved),
                narrowed=[dict(previous=json.loads(old), current=json.loads(now), count=count)
                          for (old, now), count in sorted(narrowed.items())],
                total_records=sum(actual.values()), unique_diagnostics=len(actual),
                baseline_records=sum(expected.values()), baseline_unique_diagnostics=len(expected))


def check_report(report_path, baseline_path=DEFAULT_BASELINE):
    """Rerun just the strict audit with -v, then gate all compiler/cap results."""
    report_path = Path(report_path)
    report = json.loads(report_path.read_text())
    baseline_path = Path(baseline_path)
    baseline = json.loads(baseline_path.read_text())
    output = report_path.parent
    checks = {f"{item['variant']}/{item['mode']}": item for item in report['commands']}
    if set(checks) != {'original/init', 'candidate/init', 'candidate/neverallow-audit'}:
        raise ValueError('Audit command set changed')
    if report['source_commit'] != baseline['compiler_source_commit']:
        raise ValueError('Compiler source changed; baseline needs review')
    original, candidate, strict = (checks[key] for key in
                                    ('original/init', 'candidate/init', 'candidate/neverallow-audit'))
    original_ok = original['returncode'] != 0 and original.get('expected_namespace_failure') is True
    candidate_ok = candidate['returncode'] == 0 and candidate.get('serialized_version') == 30 and candidate.get('caps_check_returncode') == 0
    command = list(strict['command'])
    if '-N' in command:
        raise ValueError('Strict audit unexpectedly disables neverallow checks')
    if '-v' not in command:
        command.insert(1, '-v')
    completed = subprocess.run(command, text=True, capture_output=True, timeout=180)
    log = output / 'candidate-neverallow-verbose.log'
    log.write_text(completed.stdout + completed.stderr)
    records = parse_verbose(log.read_text())
    if completed.returncode == 0 and records:
        raise ValueError('Successful compiler reported neverallow failures')
    if completed.returncode != 0 and not records:
        raise ValueError('Compiler failed without recognized neverallow diagnostics')
    delta = compare(records, baseline)
    passed = original_ok and candidate_ok and not delta['new']
    result = dict(status='KNOWN_FINDINGS_UNCHANGED_OR_REDUCED_NOT_BOOT_READY' if passed else 'REGRESSION_OR_TOOL_FAILURE_NOT_BOOT_READY',
                  regression_check_passed=passed, boot_ready=False,
                  original_expected_namespace_failure=original_ok,
                  candidate_init_and_capabilities_preserved=candidate_ok,
                  strict_audit_returncode=completed.returncode,
                  strict_audit_log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
                  baseline_sha256=hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
                  diagnostics=delta,
                  limitation='A passing regression gate preserves known findings; it does not make this policy bootable or safe to ship.')
    (output/'neverallow-regression.json').write_text(json.dumps(result, indent=2)+'\n')
    report['regression_status'] = result['status']
    report['boot_ready'] = False
    report['neverallow_regression_report'] = 'neverallow-regression.json'
    report_path.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(status=result['status'], total_records=delta['total_records'],
                          new_records=sum(row['count'] for row in delta['new']),
                          resolved_records=sum(row['count'] for row in delta['resolved'])), indent=2))
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args()
    return check_report(args.report, args.baseline)


if __name__ == '__main__':
    raise SystemExit(main())
