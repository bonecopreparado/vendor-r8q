"""Stage SF group32 and the proven ueventd bridge in copied P1 image plans.

Offline only. Existing plans/images are preserved. No kernel or ROM is built,
and the result explicitly remains blocked on a complete NFLOG + SUSFS kernel.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare_p1_plans as previous
import patch_ext4_candidate as ext4
import patch_surfaceflinger as sf

LEGACY_SHA = '8debe752a74eb73382de872638462e6869f50041d75bba9f66aa89e2e2530f12'
# This is the generated P1 plan's final init, after removing logdumpd. The
# separate recovery addon's installed-init pin must not be reused here.
INIT_SHA = 'b8fbfbf01ff85843b4e82b64d2515c3894fd17b07df6f222e1c2f2f975e346c8'
BRIDGE_SHA = 'a62d17938582b2205610749a6ede6989b173aa08e6e995ebefc1ff7339ee21b8'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def relative_file(root, name):
    if not isinstance(name, str) or '\\' in name or '\0' in name:
        raise ValueError('Invalid plan source')
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(p in ('.', '..') for p in name.split('/')):
        raise ValueError('Plan source must be a canonical relative file')
    resolved = (root / name).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file() or (root / name).is_symlink():
        raise ValueError('Plan source escapes root or is not a regular file')
    return resolved


def augment(plans, library, legacy, final_init, system_rules, bridge, canonical_exists=False):
    result = copy.deepcopy(plans)
    if not {'system', 'system_ext', 'vendor', 'odm'}.issubset(result):
        raise ValueError('Expected complete P1 partition plans')
    for part, plan in result.items():
        if part not in ('system', 'system_ext', 'vendor', 'odm', 'product'):
            raise ValueError('Unexpected partition')
        rows = plan.get('operations')
        if plan.get('schema_version') != 1 or not re.fullmatch('[0-9a-f]{64}', plan.get('source_image_sha256', '')):
            raise ValueError('Missing pinned image identity')
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get('path'), str) for r in rows):
            raise ValueError('Invalid operation list')
        if len({r['path'] for r in rows}) != len(rows):
            raise ValueError('Duplicate existing operation')
    targets = {'system_ext': '/lib64/libsurfaceflinger.so', 'vendor': '/etc/ueventd.rc'}
    for part, target in targets.items():
        if any(r['path'] == target for r in result[part]['operations']):
            raise ValueError('Boot-fix target already has an operation')
    if canonical_exists:
        raise ValueError('Unexpected existing canonical ueventd file')
    if (sha(legacy), sha(final_init), sha(bridge)) != (LEGACY_SHA, INIT_SHA, BRIDGE_SHA):
        raise ValueError('Expected exact reviewed R8Q ueventd configuration')
    imports = [line.split('#', 1)[0].split() for line in system_rules.decode().splitlines()]
    if imports.count(['import', '/vendor/etc/ueventd.rc']) != 1:
        raise ValueError('Donor System must import canonical Vendor rules exactly once')
    patched = sf.transform(library)
    payloads = {}
    for part, data in (('system_ext', patched), ('vendor', bridge)):
        target = targets[part]
        name = 'candidate/' + part + target
        row = dict(op='replace' if part == 'system_ext' else 'add', path=target,
                   source=name, sha256=sha(data))
        if part == 'system_ext':
            row['old_sha256'] = sf.ORIGINAL_SHA256
        else:
            row['metadata_from'] = '/ueventd.rc'
        result[part]['operations'].append(row)
        payloads[name] = data
    return result, payloads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=previous.ROOT)
    parser.add_argument('--plans', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root, source, output = args.project_root.resolve(), args.plans.resolve(), args.output.absolute()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(source):
        parser.error('Use a new output directory outside the original plans')
    previous.ROOT = root
    ext4.ROOT = root
    plans = {}
    for path in sorted(source.glob('*-plan.json')):
        part = path.name.removesuffix('-plan.json')
        plan = json.loads(path.read_text())
        image = root/'extracted'/('r8q' if part in ('vendor', 'odm') else 'hyperos')/(part + '.img')
        if image.is_symlink() or not image.is_file():
            raise ValueError('Missing regular source image: ' + part)
        with image.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != plan.get('source_image_sha256'):
            raise ValueError('Source image hash differs: ' + part)
        plans[part] = plan
    # Read the final init planned by P1, rather than the unpatched donor file.
    rows = [r for r in plans['vendor']['operations'] if r['path'] == '/etc/init/hw/init.qcom.rc']
    if len(rows) != 1 or rows[0]['op'] != 'replace':
        raise ValueError('Reviewed P1 init operation missing')
    init = relative_file(source, rows[0]['source']).read_bytes()
    if sha(init) != rows[0]['sha256']:
        raise ValueError('Init replacement hash differs')
    with tempfile.TemporaryDirectory() as work:
        vendor = ext4.Ext4(root/'extracted/r8q/vendor.img', Path(work))
        exists = vendor.stat('/etc/ueventd.rc', missing_ok=True) is not None
    updated, payloads = augment(plans,
        previous.read('system_ext', '/lib64/libsurfaceflinger.so'),
        previous.read('vendor', '/ueventd.rc'), init,
        previous.read('system', '/system/etc/ueventd.rc'),
        (root/'tools/ueventd_compat/ueventd.rc').read_bytes(), exists)
    # Validate every preserved replacement before creating any staged output.
    preserved = {}
    for plan in plans.values():
        for row in plan['operations']:
            if row['op'] == 'delete':
                continue
            name = row['source']
            data = relative_file(source, name).read_bytes()
            if sha(data) != row['sha256']:
                raise ValueError('Original plan replacement hash differs')
            if name in preserved and preserved[name] != data:
                raise ValueError('Conflicting original payloads')
            preserved[name] = data
    if set(preserved) & set(payloads):
        raise ValueError('New payload would overwrite an original')
    output.mkdir(parents=True, exist_ok=False)
    for name, data in {**preserved, **payloads}.items():
        dest = output/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as stream:
            stream.write(data)
    for part, plan in updated.items():
        (output/(part + '-plan.json')).write_text(json.dumps(plan, indent=2) + '\n')
    status = dict(status='STAGED_IMAGE_PLANS_ONLY_KERNEL_BLOCKED', flashable=False,
        boot_confirmed=False, kernel_changed=False, susfs_removal_allowed=False,
        legacy_kernel_symlinks_required=True, original_plans_preserved=True,
        blockers=['Complete linked kernel with NFLOG and real SUSFS integration is still required.',
                  'Rebuild and verify all partition images, policy/VINTF, super and the complete recovery ZIP.'])
    (output/'STAGING-RESULT.json').write_text(json.dumps(status, indent=2) + '\n')
    print(json.dumps(status, indent=2))


if __name__ == '__main__':
    main()
