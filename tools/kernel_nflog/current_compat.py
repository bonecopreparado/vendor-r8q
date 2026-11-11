"""Exact, reviewed 4.19 block API overlays for the pinned current source.

No scheduler, zram or writeback feature is disabled to hide compile errors.
Both original and resulting source bytes, and each patch, are independently
pinned. A build may change only these tracked files to these exact bytes.
"""
from pathlib import Path
import hashlib
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_current as audit

PATCH_ROOT = Path(__file__).resolve().parent / 'patches'
PINS = {
    'block/mq-deadline.c': {
        'patch': 'current-mq-deadline.patch',
        'before_sha256': '91bc938a86dea90d74ebc9377b38748e1a78550fb927ccb2abecf853edf0ce3f',
        'after_sha256': '3a21051922d8d04906ba478c712e36f70609cf329d908c58b73b196fc8a56d27',
        'patch_sha256': 'ca3fe52254a2833df902fb5b8242df58c29d6ef8981c13880211625fa1399068',
    },
    'drivers/block/zram/zram_drv.c': {
        'patch': 'current-zram-writeback.patch',
        'before_sha256': 'e4789899ff9cbe812517ca2cf47cbd3398011b5f5a0d488a081093adab83134c',
        'after_sha256': '58a8efaff00878f08806e72a22e43b23bb8f69d41b2596d4c61f8f1dbc814125',
        'patch_sha256': 'fdddef4184a57e3e0fc5c651e51d387f4c183490d63b3946db247224ffc0ccee',
    },
}


def file_sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected regular source/patch: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_report():
    return {'schema': 1, 'source_commit': audit.SOURCE_COMMIT,
            'files': [{'path': path, **pin} for path, pin in sorted(PINS.items())]}


def validate_report(report, tracked_changes):
    """Validate the exact overlay record used by a later boot packager."""
    if report != expected_report():
        raise ValueError('Source compatibility overlay does not match exact reviewed pins')
    if not isinstance(tracked_changes, str) or tracked_changes.splitlines() != sorted(PINS):
        raise ValueError('Tracked changes are not the exact reviewed compatibility files')
    return report


def verify_applied(source, env):
    for path, pin in PINS.items():
        if file_sha(source / path) != pin['after_sha256']:
            raise ValueError('Reviewed patched source bytes differ: ' + path)
    changes = audit.output(['git', '-C', source, 'diff', '--name-only', 'HEAD', '--'], env)
    validate_report(expected_report(), changes)
    if audit.output(['git', '-C', source, 'diff', '--cached', '--name-only', 'HEAD', '--'], env):
        raise ValueError('Unexpected staged source changes')
    return changes


def apply(source, evidence, env):
    if audit.output(['git', '-C', source, 'rev-parse', 'HEAD'], env) != audit.SOURCE_COMMIT:
        raise ValueError('Compatibility patches require the exact current source commit')
    if audit.output(['git', '-C', source, 'status', '--porcelain', '--untracked-files=all'], env):
        raise ValueError('Compatibility patches require an initially clean source checkout')
    patches = []
    for path, pin in sorted(PINS.items()):
        if file_sha(source / path) != pin['before_sha256']:
            raise ValueError('Original source bytes differ: ' + path)
        patch = PATCH_ROOT / pin['patch']
        if file_sha(patch) != pin['patch_sha256']:
            raise ValueError('Compatibility patch hash differs: ' + pin['patch'])
        patches.append(patch)
    command = ['git', '-C', source, 'apply', '--whitespace=nowarn']
    audit.run(command + ['--check'] + patches, evidence / 'compatibility-check.log', env)
    audit.run(command + patches, evidence / 'compatibility-apply.log', env)
    verify_applied(source, env)
    audit.run(['git', '-C', source, 'diff', '--no-ext-diff', '--no-textconv', 'HEAD', '--'],
              evidence / 'reviewed-source-compatibility.diff', env)
    result = expected_report()
    audit.write_json(evidence / 'reviewed-source-overlay.json', result)
    return result
