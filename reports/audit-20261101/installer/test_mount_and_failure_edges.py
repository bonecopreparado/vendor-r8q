"""Independent P0r7 edge review on regular temporary fixtures only.

Published sources stay untouched. A separate candidate handles escaped mount
paths; this harness gives umount realistic argument matching/removal semantics.
"""
from pathlib import Path
import json
import os
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
REPORT = Path(__file__).resolve().parent
BASE = ROOT / 'reports/audit-20261031/overnight/reader/test_installer_mock_mksh.py'
PUBLISHED = ROOT / 'delivery/Revisao-P0r7-Windows/p0r7-assets/installer-template.sh'
CANDIDATE = ROOT / 'patches/0002-recovery-mount-paths/installer-template-candidate.sh'
SHELL = os.environ.get('MKSH_BINARY', str(ROOT / 'reports/audit-20261031/overnight/reader/mksh-src/mksh'))
CASE = ''


def hooks(root, bins, target, mf, mi, exe):
    if CASE == 'sar_nested':
        mf.write_text(mf.read_text() + '/dev/block/dm-1 /system_root/system ext4 ro 0 0\n')
        mi.write_text(mi.read_text() + '3 2 253:1 / /system_root/system ro - ext4 /dev/block/dm-1 ro\n')
    umount = root / 'umount_hook.py'
    umount.write_text('''from pathlib import Path
import json,os,re,sys
root=Path(''' + repr(str(root)) + ''')
target=sys.argv[1]
with (root/'umount.jsonl').open('a') as log:log.write(json.dumps(target)+'\\n')
def decode(s):return re.sub(r'\\\\([0-7]{3})',lambda m:chr(int(m.group(1),8)),s)
mounts=Path(os.environ['MOUNTS']);info=Path(os.environ['MOUNTINFO'])
lines=mounts.read_text().splitlines(True)
if os.environ.get('UNMOUNT_FAIL')=='1' or target not in [decode(x.split()[1]) for x in lines]:
 print('umount: no exact mount target '+repr(target),file=sys.stderr);sys.exit(9)
mounts.write_text(''.join(x for x in lines if decode(x.split()[1])!=target))
info.write_text(''.join(x for x in info.read_text().splitlines(True) if decode(x.split()[4])!=target))
''')
    exe('umount', 'exec python3 "' + str(umount) + '" "$@"\n')
    mktemp = root / 'mktemp_hook.py'
    mktemp.write_text('''from pathlib import Path
import subprocess,sys
p=subprocess.run(['/usr/bin/mktemp']+sys.argv[1:],capture_output=True,text=True)
if p.returncode:sys.stderr.write(p.stderr);sys.exit(p.returncode)
Path(''' + repr(str(root / 'tmp-trace')) + ''').write_text(p.stdout.strip())
sys.stdout.write(p.stdout)
''')
    exe('mktemp', 'exec python3 "' + str(mktemp) + '" "$@"\n')
    if CASE == 'sort_failure':
        exe('sort', 'echo sort-fixture-failure >&2\nexit 77\n')
    if CASE in {'target_fsync_failure', 'readback_short_dd'}:
        dd = root / 'dd_hook.py'
        dd.write_text('''import os,subprocess,sys
from pathlib import Path
args=sys.argv[1:];opts=dict(x.split('=',1) for x in args if '=' in x)
case=''' + repr(CASE) + '''
for arg in args:
 if arg.startswith(('iflag=','oflag=')):sys.exit(90)
 if os.environ.get('REJECT_FSYNC')=='1' and arg=='conv=fsync':sys.exit(91)
super_path=''' + repr(str(target / 'super')) + '''
if case=='readback_short_dd' and opts.get('bs')=='4096' and 'if' not in opts:
 try:input_path=os.readlink('/proc/self/fd/0')
 except OSError:input_path=''
 if input_path==super_path:
  args=[('count='+str(int(opts['count'])-1)) if x.startswith('count=') else x for x in args]
rc=subprocess.run(['/usr/bin/dd']+args).returncode
try:output_path=os.readlink('/proc/self/fd/1')
except OSError:output_path=''
if case=='target_fsync_failure' and output_path==super_path and 'conv=fsync' in args:sys.exit(97)
sys.exit(rc)
''')
        exe('dd', 'exec python3 "' + str(dd) + '" "$@"\n')
    if CASE == 'target_sync_failure':
        sync = root / 'sync_hook.py'
        sync.write_text('''from pathlib import Path
import sys
p=Path(''' + repr(str(target / 'super')) + ''')
with p.open('rb') as f:f.seek(12288);b=f.read(1)
sys.exit(98 if b==b'N' else 0)
''')
        exe('sync', 'exec python3 "' + str(sync) + '" "$@"\n')


def collect(root):
    log = root / 'umount.jsonl'
    trace = root / 'tmp-trace'
    work = Path(trace.read_text()) if trace.exists() else None
    return dict(umount_calls=[json.loads(s) for s in log.read_text().splitlines()] if log.exists() else [],
                temporary_directory_removed=not work.exists() if work else None)


source = BASE.read_text().split('\ncases=')[0]
assert source.count('  script=SOURCE.read_text()') == 1
source = source.replace('  script=SOURCE.read_text()', '  review_hooks(root,bins,target,mf,mi,exe)\n  script=SOURCE.read_text()')
source = source.replace('stdout=result.stdout,stderr=result.stderr)',
                        'stdout=result.stdout,stderr=result.stderr,review=review_collect(root))')
ns = {'__file__': str(BASE), 'review_hooks': hooks, 'review_collect': collect}
exec(compile(source, str(BASE), 'exec'), ns)
ns['SHELL'] = SHELL
results = []


def run(name, *, candidate=False, expect_exit=0, expect_changed=None, **kwargs):
    global CASE
    CASE = name
    ns['SOURCE'] = CANDIDATE if candidate else PUBLISHED
    record = ns['run_case'](name, **kwargs)
    record['source'] = 'non_shipping_candidate' if candidate else 'published_p0r7'
    assert (record['exit'] == 0) == (expect_exit == 0), record
    if expect_changed is not None: assert record['changed'] == expect_changed, record
    assert record['prefix_preserved'] and record['review']['temporary_directory_removed'], record
    results.append(record)
    print(record['source'], name, 'PASS', flush=True)
    return record


for name in ['sar_root', 'sar_nested']:
    result = run(name, mount='/system_root', expect_changed=['super', 'boot', 'dtbo'])
    if name == 'sar_nested':assert result['review']['umount_calls'] == ['/system_root/system', '/system_root'], result
for fd in [3, 8, 9]:
    # The base harness has FD9 support. Other FDs use the same genuine inherited
    # descriptor path through a wrapper, retaining mksh inside the installer.
    if fd == 9:
        run('ui_fd9', outfd9=True, expect_changed=['super', 'boot', 'dtbo'])
    else:
        old_shell = ns['SHELL']
        # Use a bash wrapper that rewrites the script's OUTFD argument, without
        # modifying any source inside the published installer.
        with __import__('tempfile').TemporaryDirectory() as td:
            wrapper = Path(td) / 'shell'
            wrapper.write_text('#!/bin/bash\nexec ' + str(fd) + '>&1\nexec "' + SHELL + '" "$1" "$2" ' + str(fd) + ' "$4"\n')
            wrapper.chmod(0o700); ns['SHELL'] = str(wrapper)
            run('ui_fd'+str(fd), expect_changed=['super', 'boot', 'dtbo'])
        ns['SHELL'] = old_shell

escaped = [('space', r'/vendor/cache\040files', '/vendor/cache files'),
           ('tab', r'/vendor/cache\011files', '/vendor/cache\tfiles'),
           ('backslash', r'/vendor/cache\134files', '/vendor/cache\\files'),
           ('literal_octal', r'/vendor/cache\134040files', r'/vendor/cache\040files')]
for name, encoded, decoded in escaped:
    old = run('escaped_'+name, mount=encoded, expect_exit=1, expect_changed=[])
    assert old['review']['umount_calls'] == [encoded] and 'Nao foi possivel desmontar' in old['stdout'], old
    new = run('escaped_'+name, candidate=True, mount=encoded, expect_changed=['super', 'boot', 'dtbo'])
    assert new['review']['umount_calls'] == [decoded], new
refused = run('escaped_newline_refused', candidate=True, mount=r'/vendor/cache\012files', expect_exit=1, expect_changed=[])
assert not refused['review']['umount_calls'] and 'Escape nao suportado' in refused['stdout'], refused
failed = run('escaped_umount_failure', candidate=True, mount=r'/vendor/cache\040files', unmount_fail=True, expect_exit=1, expect_changed=[])
assert failed['review']['umount_calls'] == ['/vendor/cache files'], failed
sort = run('sort_failure', mount='/vendor', expect_exit=1, expect_changed=[])
assert 'sort-fixture-failure' in sort['stderr'] and 'ERRO:' not in sort['stdout'], sort
run('target_fsync_failure', expect_exit=1, expect_changed=['super'])
run('target_sync_failure', reject_fsync=True, expect_exit=1, expect_changed=['super'])
run('readback_short_dd', expect_exit=1, expect_changed=['super'])
(REPORT / 'mount-and-failure-results.json').write_text(json.dumps(results, indent=2) + '\n')
print(len(results), 'edge scenarios PASS', flush=True)
