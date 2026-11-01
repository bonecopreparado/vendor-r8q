"""Read published code; build only bounded temporary fixtures, never device paths."""
from pathlib import Path
import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path('/workspace/hyperos-space')
OUT = Path(__file__).resolve().parent


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


fixture=module('packaging_existing_fixture',ROOT/'ci-r8q/tests/test_p0r7_patcher.py')
p=fixture.p
results=[]
for value in (0.0,False):
    case=fixture.Tests('test_success_reuses_all_payloads_without_changes')
    case.setUp()
    try:
        case.rows[0]['offset']=value
        case.manifest['installer_sha256']=hashlib.sha256(p.render(case.assets['installer-p0r5.sh'],case.rows)).hexdigest()
        case.save_source()
        with contextlib.redirect_stdout(io.StringIO()):
            built=case.build()
        with zipfile.ZipFile(built) as archive:
            script=archive.read(p.INSTALLER).decode()
        begin=script.index('\nfunction fail(s) {')
        end=script.index('\n\' "$WORK/payload.rows"',begin)
        awk=script[begin:end]
        rows=case.root/'rows'
        rows.write_text('\n'.join(' '.join(str(r[k]) for k in p.ROW_KEYS) for r in case.rows)+'\n')
        check=subprocess.run(['awk','-v','super_limit=16384','-v','boot_limit=8192','-v','dtbo_limit=4096',awk,str(rows)],capture_output=True,text=True)
        assert check.returncode!=0 and 'inteiro nao canonico' in check.stdout
        results.append(dict(case='noncanonical_offset_'+type(value).__name__,generator_publishes=True,
                            installer_table_rejects_before_writes=True,exit=check.returncode,diagnostic=check.stdout.strip()))
    finally:case.doCleanups()

for dangling in (False,True):
    case=fixture.Tests('test_success_reuses_all_payloads_without_changes');case.setUp()
    try:
        victim=case.root/'victim'
        if not dangling:victim.write_bytes(b'KEEP')
        destination=case.root/'INSTALAR-P0r7.zip';destination.symlink_to(victim)
        try:
            with contextlib.redirect_stdout(io.StringIO()):case.build()
        except FileExistsError:pass
        else:raise AssertionError('Output alias unexpectedly accepted')
        assert destination.is_symlink()
        assert (not victim.exists()) if dangling else victim.read_bytes()==b'KEEP'
        results.append(dict(case='output_symlink_'+('dangling' if dangling else 'existing'),rejects=True,target_preserved=True))
    finally:case.doCleanups()

case=fixture.Tests('test_success_reuses_all_payloads_without_changes');case.setUp()
try:
    original=p.verify_payloads
    destination=case.root/'INSTALAR-P0r7.zip'
    def race(*args):
        original(*args)
        destination.write_bytes(b'OTHER RESULT')
    with patch.object(p,'verify_payloads',race):
        try:
            with contextlib.redirect_stdout(io.StringIO()):case.build()
        except FileExistsError:pass
        else:raise AssertionError('Output race unexpectedly replaced result')
    assert destination.read_bytes()==b'OTHER RESULT'
    results.append(dict(case='output_appears_after_validation',rejects=True,prior_result_preserved=True))
finally:case.doCleanups()

sys.path.insert(0,str(ROOT/'ci-r8q/vendor_audit'))
vendor=module('packaging_vendor_audit',ROOT/'ci-r8q/vendor_audit/audit_vendor.py')
with tempfile.TemporaryDirectory(prefix='r8q-baseline-probe-') as td:
    path=Path(td)/'baseline.zip';blob=b'ro.vendor.build.version.sdk=99\n'
    row=dict(path='/build.prop',mode=0o100644,uid=0,gid=0,bytes=len(blob),type='regular',sha256=hashlib.sha256(blob).hexdigest())
    baseline=dict(schema_version=1,image=dict(bytes=vendor.BASELINE_BYTES,sha256=vendor.BASELINE_SHA),files=[row],exports=[row])
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('baseline.json',json.dumps(baseline))
        archive.writestr('configs/build.prop',blob)
    loaded,configs=vendor.load_baseline(path)
    assert configs['/build.prop']==blob
    digest=vendor.file_sha(path)
    pins=json.loads((ROOT/'ci-r8q/vendor_audit/data/sources.json').read_text())
    assert digest!=pins['baseline_zip']['sha256']
    workflow=(ROOT/'.github/workflows/r8q-vendor-audit.yml').read_text()
    assert pins['baseline_zip']['sha256'] in workflow and 'sha256sum -c -' in workflow
    results.append(dict(case='standalone_baseline_self_declared_identity',standalone_accepts=True,
                        protected_in_published_workflow_by_pinned_archive_sha=True))

row=dict(path='/etc/fstab.qcom',mode=0o100644,uid=0,gid=0,type='regular',sha256='abc')
changed=dict(row,mode=0o100600)
comparison=vendor.compare(dict(files=[row]),dict(files=[changed]),{}, {})
assert comparison['metadata_changed']==['/etc/fstab.qcom']
assert comparison['config_categories']['fstab']==[]
results.append(dict(case='metadata_only_config_change',reported_in_metadata_changed=True,
                    included_in_content_categories=False,interpretation='Consumers must inspect metadata_changed as well'))

(OUT/'probe-results.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
