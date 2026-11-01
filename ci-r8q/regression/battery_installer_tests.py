"""Exercise P0r8 power guards and inherited checks using bounded mock files.

No real battery supply, block device, phone, image or mount is opened. The
existing real-mksh fixture is extended only with mock battery files and a cat
wrapper that can change their readings between preflight and target writes.
"""
from pathlib import Path
import json
import os
import shlex
import subprocess

ROOT = Path(os.environ.get('R8Q_PROJECT_ROOT', Path(__file__).resolve().parents[2])).resolve()
SOURCE = Path(os.environ.get('R8Q_TEST_SOURCE', ROOT / 'delivery/Ready-P0r8/installer-template-ready.sh')).resolve()
REPORT = Path(os.environ.get('R8Q_TEST_REPORT', ROOT / 'reports/audit-20261101/battery')).resolve()
REPORT.mkdir(parents=True, exist_ok=True)
SHELL = os.environ.get('MKSH_BINARY', 'mksh')
BASE = ROOT / 'ci-r8q/regression/installer_mock_mksh.py'

CAT_WRAPPER = '''import json, subprocess, sys
from pathlib import Path
config = json.loads(Path(__file__).with_suffix('.json').read_text())
if sys.argv[1:] == [config['capacity_path']]:
    counter = Path(config['counter_path'])
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    if count >= 2:
        if config['second_capacity_error']:
            sys.exit(1)
        if config['second_capacity'] is not None:
            sys.stdout.write(config['second_capacity'])
            sys.exit(0)
elif sys.argv[1:] == [config['status_path']]:
    counter = Path(config['counter_path'])
    count = int(counter.read_text()) if counter.exists() else 0
    if count >= 2 and config['second_status'] is not None:
        sys.stdout.write(config['second_status'])
        sys.exit(0)
sys.exit(subprocess.run(['/usr/bin/cat'] + sys.argv[1:]).returncode)
'''

fixture_text = BASE.read_text()
needle = "table_mutation=''):"
assert fixture_text.count(needle) == 1
fixture_text = fixture_text.replace(needle,
    "table_mutation='',battery_capacity='75',battery_status='Discharging',"
    "capacity_missing=False,status_missing=False,second_capacity=None,"
    "second_status=None,second_capacity_error=False,ready_layout='adjacent'):")

needle = "  script=SOURCE.read_text()"
assert fixture_text.count(needle) == 1
setup = '''  battery=root/'battery';battery.mkdir()
  if not capacity_missing:(battery/'capacity').write_text(battery_capacity+'\\n')
  if not status_missing:(battery/'status').write_text(battery_status+'\\n')
  battery_count=root/'battery-read-count'
  cat_wrapper=root/'battery-cat.py';cat_wrapper.write_text(__battery_cat_wrapper__)
  cat_wrapper.with_suffix('.json').write_text(json.dumps(dict(capacity_path=str(battery/'capacity'),status_path=str(battery/'status'),counter_path=str(battery_count),second_capacity=second_capacity,second_status=second_status,second_capacity_error=second_capacity_error)))
  exe('cat','exec python3 '+shlex.quote(str(cat_wrapper))+' "$@"\\n')
  if ready_layout=='inside':
   new_zip=payload/zip_path.name;zip_path.rename(new_zip);zip_path=new_zip
  elif ready_layout=='flat':
   for part_file in payload.iterdir():part_file.rename(root/part_file.name)
   payload.rmdir();payload=root
  elif ready_layout=='missing_folder':payload.rename(root/'unrelated-files')
  elif ready_layout=='symlink_folder':
   actual=root/'actual-payloads';payload.rename(actual);payload.symlink_to(actual,target_is_directory=True)
  elif ready_layout!='adjacent':raise ValueError(ready_layout)
'''
fixture_text = fixture_text.replace(needle, setup + needle)
needle = "  script=script.replace('@@PAYLOAD_ROWS@@'"
assert fixture_text.count(needle) == 1
fixture_text = fixture_text.replace(needle,
    "  script=script.replace('BATTERY_SYSFS=/sys/class/power_supply/battery','BATTERY_SYSFS='+shlex.quote(str(battery)))\n"
    # Some mksh builds have a cat builtin. A fixture-only function directs
    # reads through our mock-state wrapper rather than that builtin.
    "  script=script.replace('set -o pipefail\\n','set -o pipefail\\ncat() { '+shlex.quote(str(bins/'cat'))+' \\\"$@\\\"; }\\n')\n" + needle)
needle = '  return dict(case=name,'
assert fixture_text.count(needle) == 1
fixture_text = fixture_text.replace(needle,
    "  return dict(battery_reads=int(battery_count.read_text()) if battery_count.exists() else 0,case=name,")

namespace = {'__name__': '__battery_installer_fixture__',
             '__battery_cat_wrapper__': CAT_WRAPPER, 'shlex': shlex}
original_env = dict(os.environ)
try:
    os.environ.update(R8Q_PROJECT_ROOT=str(ROOT), R8Q_TEST_SOURCE=str(SOURCE),
                      R8Q_TEST_REPORT=str(REPORT), MKSH_BINARY=SHELL)
    # The original 37 scenarios execute with a healthy default mock battery.
    exec(compile(fixture_text, str(BASE) + ':battery-extension', 'exec'), namespace)
finally:
    os.environ.clear()
    os.environ.update(original_env)
baseline = json.loads((REPORT / 'installer-results.json').read_text())
assert len(baseline) == 37

power_cases = [
    ('fifty_percent_unplugged', dict(battery_capacity='50'), 'success'),
    ('full_percent_unplugged', dict(battery_capacity='100', battery_status='Full'), 'success'),
    ('forty_nine_unplugged', dict(battery_capacity='49'), 'preflight'),
    ('forty_nine_charging', dict(battery_capacity='49', battery_status='Charging'), 'success'),
    ('twenty_charging', dict(battery_capacity='20', battery_status='Charging'), 'success'),
    ('nineteen_charging', dict(battery_capacity='19', battery_status='Charging'), 'preflight'),
    ('zero_charging', dict(battery_capacity='0', battery_status='Charging'), 'preflight'),
    ('fifty_unknown_status', dict(battery_capacity='50', battery_status='Unknown'), 'success'),
    ('forty_nine_unknown_status', dict(battery_capacity='49', battery_status='Unknown'), 'preflight'),
    ('forty_nine_not_charging', dict(battery_capacity='49', battery_status='Not charging'), 'preflight'),
    ('fifty_missing_status', dict(battery_capacity='50', status_missing=True), 'success'),
    ('forty_nine_missing_status', dict(battery_capacity='49', status_missing=True), 'preflight'),
    ('missing_capacity', dict(capacity_missing=True), 'preflight'),
    ('battery_dropped_during_preflight', dict(battery_capacity='80', second_capacity='49'), 'before-write'),
    ('charger_removed_during_preflight', dict(battery_capacity='30', battery_status='Charging', second_status='Discharging'), 'before-write'),
    ('capacity_read_failed_during_preflight', dict(second_capacity_error=True), 'before-write'),
    ('capacity_invalid_during_preflight', dict(second_capacity=''), 'before-write'),
    ('charged_above_threshold_during_preflight', dict(battery_capacity='30', battery_status='Charging', second_capacity='50', second_status='Discharging'), 'success'),
]
for number, capacity in enumerate(['', '-1', '+50', '101', '050', ' 50', '50 ',
                                    '50.0', '50\n51', '4294967346', '0x32']):
    power_cases.append((f'invalid_capacity_{number}', dict(battery_capacity=capacity), 'preflight'))

results = []
for name, options, expected in power_cases:
    result = namespace['run_case'](name, **options)
    result['expected_phase'] = expected
    results.append(result)
    if expected == 'success':
        assert result['exit'] == 0 and len(result['changed']) == 3, result
        assert result['prefix_preserved'] and result['super_body_matches'], result
        assert result['battery_reads'] == 2, result
        assert 'Battery (before-write):' in result['stdout'], result
    else:
        assert result['exit'] != 0 and not result['changed'], result
        assert result['prefix_preserved'] and 'Battery ' in result['stdout'], result
        if expected == 'preflight':
            assert result['battery_reads'] == 1 and not result['counts'], result
        else:
            assert result['battery_reads'] == 2, result
            # Every mock payload finished its preflight inflate exactly once;
            # no image-writing inflate started after the failed second guard.
            assert len(result['counts']) == 4 and set(result['counts'].values()) == {1}, result
            assert 'Gravando super' not in result['stdout'], result
    print(name, 'PASS', flush=True)

layout_results = []
for name, layout, expected_ok in [('adjacent_payloads', 'adjacent', True),
                                 ('zip_inside_payloads', 'inside', True),
                                 ('flat_payload_directory', 'flat', True),
                                 ('missing_payload_directory', 'missing_folder', False),
                                 ('symlink_payload_directory', 'symlink_folder', False)]:
    result = namespace['run_case'](name, ready_layout=layout, path_spaces=True)
    layout_results.append(result)
    if expected_ok:
        assert result['exit'] == 0 and len(result['changed']) == 3, result
        assert result['prefix_preserved'] and result['super_body_matches'], result
    else:
        assert result['exit'] != 0 and not result['changed'] and result['prefix_preserved'], result
    print(name, 'PASS', flush=True)

(REPORT / 'battery-results.json').write_text(json.dumps(results, indent=2) + '\n')
(REPORT / 'ready-layout-results.json').write_text(json.dumps(layout_results, indent=2) + '\n')
summary = dict(source=str(SOURCE.relative_to(ROOT)), shell=SHELL,
               baseline_cases=len(baseline), battery_cases=len(results),
               layout_cases=len(layout_results),
               passed=len(baseline)+len(results)+len(layout_results),
               scope='bounded mock files only; no physical battery/device or boot test')
(REPORT / 'battery-test-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
