"""Run the one-ZIP installer under real mksh with bounded mock partitions."""
from pathlib import Path
import ast,hashlib,json,os,struct,subprocess,sys,tempfile,zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import package_p1_single as package
from p1_single_template import template

REPORT=Path(os.environ.get('R8Q_TEST_REPORT',ROOT/'reports/p1/single-zip-tests')).resolve()
REPORT.mkdir(parents=True,exist_ok=True)
SHELL=os.environ.get('MKSH_BINARY','mksh')
SOURCE_BASE=ROOT/'ci-r8q/regression/installer_mock_mksh.py'

with tempfile.TemporaryDirectory(prefix='r8q-single-harness-') as td:
    work=Path(td);helper=work/'zipread'
    subprocess.run(['cc','-D_FILE_OFFSET_BITS=64','-Os','-Wall','-Wextra','-Werror',str(ROOT/'tools/single_zip_helper.c'),'-o',str(helper)],check=True)
    blob=package.helper_blob(helper,False)
    source=work/'single-template.sh'
    source.write_text(template().replace('@@HELPER_BLOCKS@@',str(len(blob)//4096)).replace('@@HELPER_BYTES@@',str(len(blob))).replace('@@HELPER_SHA@@',hashlib.sha256(blob).hexdigest()))
    # Reuse the battery fixture's bounded setup and cat wrapper, but not its
    # external-directory layout assertions, which do not apply to a single ZIP.
    text=(ROOT/'ci-r8q/regression/battery_installer_tests.py').read_text()
    tree=ast.parse(text);prefix=[]
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name)and t.id=='namespace'for t in node.targets):break
        prefix.append(ast.get_source_segment(text,node))
    settings={'__name__':'__single_fixture_setup__','__file__':str(ROOT/'ci-r8q/regression/battery_installer_tests.py')}
    original=dict(os.environ)
    try:
        os.environ.update(R8Q_PROJECT_ROOT=str(ROOT),R8Q_TEST_SOURCE=str(source),R8Q_TEST_REPORT=str(REPORT),MKSH_BINARY=SHELL)
        exec(compile('\n'.join(prefix),'<battery-fixture-setup>','exec'),settings)
    finally:os.environ.clear();os.environ.update(original)
    fixture=settings['fixture_text']
    # Gzip now reads stdin. Preserve the injected failure-counter semantics by
    # exporting the current member name inside the fixture-only inflate wrapper.
    fixture=fixture.replace("name=Path(args[-1]).name if args else 'stdin'", "name=os.environ.get('R8Q_CURRENT_PAYLOAD') or (Path(args[-1]).name if args else 'stdin')")
    needle="  script=script.replace('@@PAYLOAD_ROWS@@'"
    assert fixture.count(needle)==1
    fixture=fixture.replace(needle,"  script=script.replace('inflate_part() {\\n','inflate_part() {\\n    R8Q_CURRENT_PAYLOAD=\\\"$1\\\"; export R8Q_CURRENT_PAYLOAD\\n')\n"+needle)
    # All mutations of compressed data/rows occur before this point. Build the
    # same small stored ZIP representation used by the production package.
    needle="  p=root/'installer';p.write_text(script)"
    setup='''  import zipfile
  with zipfile.ZipFile(zip_path,'w',allowZip64=True) as archive:
   entry=zipfile.ZipInfo('tools/r8q-zipread');pad=4096-30-len(entry.filename)
   entry.extra=struct.pack('<HH',0xA11E,pad-4)+b'\\0'*(pad-4)
   archive.writestr(entry,__single_helper_blob__)
   for payload_file in sorted(payload.iterdir()):
    if payload_file.name.endswith('.gz'):
     info=zipfile.ZipInfo('payloads/'+payload_file.name)
     with archive.open(info,'w',force_zip64=True) as output:output.write(payload_file.read_bytes())
'''
    assert fixture.count(needle)==1;fixture=fixture.replace(needle,setup+needle)
    module=ast.parse(fixture);nodes=[]
    for node in module.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name)and t.id=='cases'for t in node.targets):break
        nodes.append(ast.get_source_segment(fixture,node))
    namespace={'__name__':'__single_fixture__','__single_helper_blob__':blob,
               '__battery_cat_wrapper__':settings['CAT_WRAPPER'],'shlex':settings['shlex']}
    original=dict(os.environ)
    try:
        os.environ.update(R8Q_PROJECT_ROOT=str(ROOT),R8Q_TEST_SOURCE=str(source),R8Q_TEST_REPORT=str(REPORT),MKSH_BINARY=SHELL)
        exec(compile('\n'.join(nodes),'<single-zip-fixture>','exec'),namespace)
    finally:os.environ.clear();os.environ.update(original)
    # Reuse every applicable original success/failure scenario; only two guards
    # for external payload directories are replaced by the ZIP's source guard.
    base=SOURCE_BASE.read_text();parsed=ast.parse(base)
    for node in parsed.body:
        targets=node.targets if isinstance(node,ast.Assign) else [node.target]if isinstance(node,ast.AugAssign)else []
        if any(isinstance(t,ast.Name)and t.id in {'cases','failures'}for t in targets):
            exec(compile(ast.get_source_segment(base,node),'<inherited-cases>','exec'),namespace)
    cases=namespace['cases'];failures=[(n,k)for n,k in namespace['failures'] if not k.get('bind_payload') and not k.get('symlink_protected')]
    results=[]
    for name,kw in cases+failures:
        r=namespace['run_case'](name,**kw);results.append(r)
        if (name,kw) in cases:
            assert r['exit']==0 and len(r['changed'])==3 and r['prefix_preserved'] and r['super_body_matches'],r
        else:assert r['exit']!=0 and not r['changed'] and r['prefix_preserved'],r
        print(name,'PASS',flush=True)
    power=[('low_battery',dict(battery_capacity='19'),False),
           ('charging_twenty',dict(battery_capacity='20',battery_status='Charging'),True),
           ('unplug_during_preflight',dict(battery_capacity='49',battery_status='Charging',second_status='Discharging'),False),
           ('capacity_read_fails_late',dict(second_capacity_error=True),False)]
    for name,kw,ok in power:
        r=namespace['run_case'](name,**kw);results.append(r)
        assert (r['exit']==0 and len(r['changed'])==3)if ok else(r['exit']!=0 and not r['changed']),r
        print(name,'PASS',flush=True)
    for name,kw in [('gzip_failure_during_write',dict(fail_second_read=True)),('short_after_verified_source',dict(short_second_read=True))]:
        r=namespace['run_case'](name,**kw);results.append(r)
        assert r['exit']!=0 and r['changed']==['super'] and r['prefix_preserved'],r
        print(name,'PASS',flush=True)
    (REPORT/'single-installer-results.json').write_text(json.dumps(results,indent=2)+'\n')
    (REPORT/'single-test-summary.json').write_text(json.dumps(dict(passed=len(results),shell=SHELL,
        fixture='real single ZIP with native 64-bit reader; bounded mock partitions',physical_writes=False,boot_test=False),indent=2)+'\n')
    print('Single-ZIP mksh scenarios:',len(results),'PASS')
