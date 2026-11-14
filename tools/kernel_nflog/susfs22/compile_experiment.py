"""Compile the complete pinned SUSFS/NFLOG candidate for offline review only.

No boot repack, installer, release or phone access is performed. The original
five source-compatibility fixes and compiler/config guards remain mandatory.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import build_current as build
import current_compat as original

PINS = json.loads((HERE/'pins.json').read_text())
PATCH = HERE/'a265-susfs22.patch'
PATCH_SHA = '8132f13f45e7bc72699758b013e7437ab1d0ea50de26dfa37f4b3d326bed785f'
ROWS = PINS['files']
NEW = sorted(row['path'] for row in ROWS if row['before_sha256'] is None)
TRACKED = sorted(set(original.PINS) | {row['path'] for row in ROWS if row['before_sha256'] is not None})
SUSFS_SYMBOLS=frozenset((
    'susfs_init','susfs_start_sdcard_monitor_fn','susfs_add_sus_path',
    'susfs_add_sus_path_loop','susfs_is_inode_sus_path','susfs_add_sus_map',
    'susfs_extra_works','susfs_set_uname','susfs_get_enabled_features'))


def expected_overlay():
    return dict(status='EXPERIMENTAL_SUSFS22_SOURCE_NOT_HARDWARE_TESTED',
                original_compatibility=original.expected_report(),susfs22=PINS,
                susfs_disabled=False,boot_image_created=False)


def sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected regular source file: '+str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(source, env):
    for row in ROWS:
        if sha(source/row['path']) != row['after_sha256']:
            raise ValueError('Derived SUSFS source differs: '+row['path'])
    for path, pin in original.PINS.items():
        if sha(source/path) != pin['after_sha256']:
            raise ValueError('Original compatibility fix differs: '+path)
    tracked = build.audit.output(['git','-C',source,'diff','--name-only','HEAD','--'],env)
    untracked = build.audit.output(['git','-C',source,'ls-files','--others','--exclude-standard'],env)
    if tracked.splitlines() != TRACKED or untracked.splitlines() != NEW:
        raise ValueError('Unexpected tracked/untracked source changes')
    if build.audit.output(['git','-C',source,'diff','--cached','--name-only','HEAD','--'],env):
        raise ValueError('Unexpected staged source changes')
    return tracked


def apply(source, evidence, env):
    before = original.apply(source,evidence,env)
    if sha(PATCH) != PATCH_SHA or PINS['patch_sha256'] != PATCH_SHA:
        raise ValueError('Derived patch hash differs')
    for row in ROWS:
        path = source/row['path']
        if row['before_sha256'] is None:
            if path.exists() or path.is_symlink():
                raise ValueError('New SUSFS file already exists')
        elif sha(path) != row['before_sha256']:
            raise ValueError('Canonical source differs: '+row['path'])
    command = ['git','-C',source,'apply','--whitespace=nowarn']
    build.audit.run(command+['--check',PATCH],evidence/'susfs22-check.log',env)
    build.audit.run(command+[PATCH],evidence/'susfs22-apply.log',env)
    verify(source,env)
    # Exercise the real patched ownership statements before starting a long
    # build; no patched kernel binary or Android ELF is executed on the host.
    build.audit.run([sys.executable,HERE/'test_ownership.py',source],evidence/'susfs22-ownership-test.log',env)
    build.audit.run([sys.executable,HERE/'test_scheduler.py',source],evidence/'scheduler-util-test.log',env)
    report = expected_overlay()
    if report['original_compatibility']!=before:
        raise ValueError('Original compatibility record changed')
    build.audit.write_json(evidence/'susfs22-overlay.json',report)
    return report


if __name__ == '__main__':
    if '--without-susfs' in sys.argv:
        raise SystemExit('This experiment must preserve SUSFS')
    build.current_compat = SimpleNamespace(apply=apply, verify_applied=verify)
    build.REQUIRED_SYMBOLS = build.REQUIRED_SYMBOLS | SUSFS_SYMBOLS
    build.main()
