"""Exercise the READY installer locations using only bounded mock partitions.

The existing 37-case real-mksh suite remains unchanged. Its fixture function is
loaded from its AST, then extended only where the fake ZIP is placed. No ROM or
real block device is opened by this harness.
"""
from pathlib import Path
import ast
import json
import os
import subprocess

ROOT = Path(os.environ.get('R8Q_PROJECT_ROOT', Path(__file__).resolve().parents[2])).resolve()
BASE = ROOT / 'ci-r8q/regression/installer_mock_mksh.py'
SOURCE = Path(os.environ.get('R8Q_TEST_SOURCE', ROOT / 'delivery/Ready-P0r7/installer-template-ready.sh')).resolve()
REPORT = Path(os.environ.get('R8Q_TEST_REPORT', ROOT / 'reports/audit-20261101/ready'))
REPORT.mkdir(parents=True, exist_ok=True)
SHELL = os.environ.get('MKSH_BINARY', 'mksh')
env = os.environ | {'R8Q_PROJECT_ROOT': str(ROOT), 'R8Q_TEST_SOURCE': str(SOURCE),
                    'R8Q_TEST_REPORT': str(REPORT), 'MKSH_BINARY': SHELL}

baseline = subprocess.run(['python3', str(BASE)], env=env, text=True, capture_output=True)
(REPORT / 'baseline-stdout.txt').write_text(baseline.stdout)
(REPORT / 'baseline-stderr.txt').write_text(baseline.stderr)
if baseline.returncode:
    raise RuntimeError('Existing installer suite failed: ' + baseline.stdout + baseline.stderr)
baseline_results = json.loads((REPORT / 'installer-results.json').read_text())
assert len(baseline_results) == 37, len(baseline_results)
print('Existing real-mksh scenarios: 37 PASS', flush=True)

base_text = BASE.read_text()
module = ast.parse(base_text)
prefix = []
for node in module.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'cases' for t in node.targets):
        break
    prefix.append(ast.get_source_segment(base_text, node))
fixture = '\n'.join(prefix)
needle = "table_mutation=''):"
assert fixture.count(needle) == 1
fixture = fixture.replace(needle, "table_mutation='',ready_layout='adjacent'):")
needle = "  sd=root/'sys';sd.mkdir()"
placement = """  if ready_layout=='inside':
   new_zip=payload/zip_path.name;zip_path.rename(new_zip);zip_path=new_zip
  elif ready_layout=='flat':
   for part_file in payload.iterdir():part_file.rename(root/part_file.name)
   payload.rmdir();payload=root
  elif ready_layout=='missing_folder':
   payload.rename(root/'unrelated-files')
  elif ready_layout=='symlink_folder':
   actual=root/'actual-payloads';payload.rename(actual);payload.symlink_to(actual,target_is_directory=True)
  elif ready_layout!='adjacent':raise ValueError(ready_layout)
"""
assert fixture.count(needle) == 1
fixture = fixture.replace(needle, placement + needle)
namespace = {'__name__': '__ready_fixture__'}
original_env = dict(os.environ)
try:
    os.environ.update(env)
    exec(compile(fixture, str(BASE) + ':layout-extension', 'exec'), namespace)
finally:
    os.environ.clear()
    os.environ.update(original_env)

results = []
for name, layout, expected_ok in [('adjacent_payloads', 'adjacent', True),
                                   ('zip_inside_payloads', 'inside', True),
                                   ('flat_payload_directory', 'flat', True),
                                   ('missing_payload_directory', 'missing_folder', False),
                                   ('symlink_payload_directory', 'symlink_folder', False)]:
    result = namespace['run_case'](name, ready_layout=layout, path_spaces=True)
    results.append(result)
    if expected_ok:
        assert result['exit'] == 0 and len(result['changed']) == 3, result
        assert result['prefix_preserved'] and result['super_body_matches'], result
        assert 'READY installer: using payload files in ' in result['stdout'], result
    else:
        assert result['exit'] != 0 and not result['changed'] and result['prefix_preserved'], result
        assert 'Payloads not found' in result['stdout'], result
    print(name, 'PASS', flush=True)
(REPORT / 'ready-layout-results.json').write_text(json.dumps(results, indent=2) + '\n')
(REPORT / 'ready-test-summary.json').write_text(json.dumps({
    'source': str(SOURCE.relative_to(ROOT)), 'shell': SHELL,
    'baseline_cases': len(baseline_results), 'layout_cases': len(results),
    'passed': len(baseline_results) + len(results),
    'scope': 'bounded mock partition files; no physical device and no boot test'
}, indent=2) + '\n')
