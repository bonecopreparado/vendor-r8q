"""Reconstruct the reviewed P1 images from pinned public archives in a clean CI.

This program creates offline regular files only. It never talks to a phone.
The final images are an experimental boot-test candidate, not a stable ROM.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SELINUX_COMMIT = '6423998bc7b154da7f9fe726cfda9ace774dfa94'
PREFIX_SHA = 'a2715d01320391a9dbd2bee3d24a30c1ab45ba5770409f895f4997421eb0d439'
BOOT_SHA = '4283ccbecbf3087bbd520dce1e50e5e449b1f70c4d959e8ee7f24b3ebfde9301'
DTBO_SHA = '3d78f213d52a5d4875b634c4ea914d04dea678bfd70dd81625d6c9f056b60468'
DTBO_SOURCE_SHA = 'eb48bb18ccc54005a16fce07084040441af458a3f9baf96ee81047381a9f5c80'
SOURCE_MODULE = ROOT/'tools/download_verified.py'
WORK = ROOT/'reports/p1/ci-build'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2)+'\n')


def run(script, *arguments):
    print('STEP:', script, flush=True)
    subprocess.run([sys.executable, str(ROOT/script)]+list(map(str, arguments)),
                   cwd=ROOT, check=True)


def source_specifications():
    spec = importlib.util.spec_from_file_location('pinned_p1_sources', SOURCE_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SOURCES


def verify_named_file(path, expected_sha, expected_size=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing regular input: '+str(path))
    if expected_size is not None and path.stat().st_size != expected_size:
        raise ValueError('Input size differs: '+str(path))
    if digest(path) != expected_sha:
        raise ValueError('Input hash differs: '+str(path))


def padded_dtbo(source, destination):
    verify_named_file(source, DTBO_SOURCE_SHA, 4783195)
    data = source.read_bytes()+bytes(10485760-source.stat().st_size)
    if hashlib.sha256(data).hexdigest() != DTBO_SHA:
        raise ValueError('DTBO padded identity differs')
    with destination.open('xb') as stream:
        stream.write(data)


def prepare_compiler_provenance():
    """Bind the verifier to this CI's binaries and the reviewed source commit."""
    actual = subprocess.check_output(
        ['git','-C',str(ROOT/'.deps/selinux'),'rev-parse','HEAD'], text=True).strip()
    if actual != SELINUX_COMMIT:
        raise ValueError('Modern compiler was not built from the reviewed source')
    folder = ROOT/'tools/selinux-modern'
    folder.mkdir(parents=True, exist_ok=False)
    for name in ('secilc-host','check-policy-caps'):
        source = ROOT/'build'/name
        if not source.is_file() or source.is_symlink():
            raise ValueError('Build the modern compiler/checker first')
        shutil.copy2(source, folder/name)
    run_id = os.environ.get('GITHUB_RUN_ID','offline')
    repository = os.environ.get('GITHUB_REPOSITORY','bonecopreparado/vendor-r8q')
    provenance = dict(source_repository='https://github.com/SELinuxProject/selinux',
        source_commit=actual,
        build_workflow_run='https://github.com/'+repository+'/actions/runs/'+run_id,
        secilc_host_sha256=digest(folder/'secilc-host'),
        cap_checker_sha256=digest(folder/'check-policy-caps'),
        source_scope='Built in this workflow from the reviewed source; no expiring artifact is used')
    write_json(folder/'PROVENANCE.json', provenance)
    write_json(WORK/'compiler-provenance.json', provenance)


def independent_super(image_path, report_path):
    """Read back through the unchanged third-party LP implementation."""
    reference = ROOT/'tools/lineage-reference'
    provenance=json.loads((reference/'lp-source.json').read_text())
    verify_named_file(reference/'lp.py',provenance['sha256'])
    package = WORK/'lineage-package/extract_utils'
    package.mkdir(parents=True)
    (package/'__init__.py').write_text('')
    for name in ('lp.py','utils.py'):
        shutil.copyfile(reference/name, package/name)
    sys.path.insert(0,str(package.parent))
    from extract_utils.lp import LpImage
    report = json.loads(report_path.read_text())
    expected = {row['name']:row for row in report['embedded_sources']}
    rows = []
    class HashSink:
        def __init__(self): self.sha=hashlib.sha256(); self.bytes=0
        def write(self, data): self.sha.update(data);self.bytes+=len(data);return len(data)
    with image_path.open('rb') as stream:
        image = LpImage(stream)
        if set(image.get_partition_names()) != set(expected):
            raise ValueError('Independent LP partition set differs')
        for name in image.get_partition_names():
            part = image.find_partition(name);sink = HashSink()
            extents = image._LpImage__extents[part.first_extent_index:part.first_extent_index+part.num_extents]
            for extent in extents:
                if extent.target_type != 0: raise ValueError('Unexpected nonlinear extent')
                image._write_extent_to_file(extent,sink)
            row=dict(name=name,bytes=sink.bytes,sha256=sink.sha.hexdigest())
            if row['bytes']!=expected[name]['bytes'] or row['sha256']!=expected[name]['sha256']:
                raise ValueError('Independent LP readback differs: '+name)
            rows.append(row)
    write_json(WORK/'super-independent-readback.json',dict(
        status='INDEPENDENT_SUPER_HASHES_MATCH_NOT_BOOT_TESTED',partitions=rows,
        reader_provenance=json.loads((reference/'lp-source.json').read_text())))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--discard-downloads',action='store_true',
                    help='CI only: delete the two verified downloaded archives after source image verification')
    ap.add_argument('--host-tools',type=Path,
                    help='Reviewed official otatools directory containing bin/checkvintf and lib64')
    ap.add_argument('--discard-intermediate-images',action='store_true',
                    help='CI only: remove four derived partition files after their exact bytes are verified in super')
    ap.add_argument('--minimum-free-gib',type=int,default=32)
    args=ap.parse_args()
    for path in (ROOT/'extracted/r8q',ROOT/'extracted/hyperos',ROOT/'candidates/p0',ROOT/'candidates/p1',WORK,ROOT/'tools/selinux-modern'):
        if path.exists() or path.is_symlink():
            raise ValueError('Use a clean checkout; preserving prior work: '+str(path))
    if not 24 <= args.minimum_free_gib <= 128:
        raise ValueError('Minimum free-space bound must be between 24 and 128 GiB')
    if shutil.disk_usage(ROOT).free < args.minimum_free_gib*1024**3:
        raise ValueError('Insufficient build space; use a clean runner with at least '+str(args.minimum_free_gib)+' GiB free')
    for name in ('mkfs.erofs','dump.erofs','fsck.erofs'):
        binary=ROOT/'tools/image-tools/root/usr/bin'/name
        if not binary.is_file() or not os.access(binary,os.X_OK):
            raise ValueError('Missing required EROFS tool before downloading sources: '+name)
    for name in ('debugfs','e2fsck'):
        binary=ROOT/'tools/image-tools/bin'/name
        if not (binary.is_file() and os.access(binary,os.X_OK)) and not shutil.which(name):
            raise ValueError('Missing required ext4 tool before downloading sources: '+name)
    verify_named_file(ROOT/'reports/device/super-first-1MiB.bin', PREFIX_SHA, 1048576)
    for path in ('originals','extracted','candidates','reports/r8q','reports/hyperos'):
        (ROOT/path).mkdir(parents=True,exist_ok=True)
    WORK.mkdir(parents=True)
    prepare_compiler_provenance()
    sources=source_specifications()
    for key,row in sources.items():
        destination=ROOT/'originals'/row['name']
        if destination.exists():verify_named_file(destination,row['sha256'],row['size'])
        else:run('tools/download_verified.py',key)
    run('tools/reconstruct_r8q.py')
    run('tools/unpack_hyperos.py')
    reviewed=json.loads((ROOT/'reports/composition-proposed.json').read_text())
    for row in reviewed['partitions']:
        verify_named_file(ROOT/row['file'],row['sha256'],row['bytes'])
    write_json(WORK/'verified-sources.json',dict(sources=sources,
        filesystem_sources=reviewed['partitions'],all_source_images_verified=True))
    if args.discard_downloads:
        for row in sources.values():
            (ROOT/'originals'/row['name']).unlink()
    # These donor-only images are not R8Q hardware support and are not embedded.
    for name in ('vendor.img','odm.img','boot.img'):
        (ROOT/'extracted/hyperos'/name).unlink()
    run('tools/build_boot_candidate.py')
    boot=ROOT/'candidates/p0/boot-r8q-hyperos-p0.img'
    verify_named_file(boot,BOOT_SHA,67108864)
    padded_dtbo(ROOT/'extracted/r8q/dtbo.img',ROOT/'candidates/p0/dtbo-r8q-p0.img')
    run('tools/prepare_p1_plans.py')
    plans=ROOT/'patches/0007-policy-integration';out=ROOT/'candidates/p1';out.mkdir()
    for part in ('system','system_ext'):
        run('tools/rebuild_erofs_candidate.py','--source',ROOT/'extracted/hyperos'/(part+'.img'),
            '--plan',plans/(part+'-plan.json'),'--output',out/(part+'.img'),
            '--report',WORK/(part+'-build.json'))
    for part in ('vendor','odm'):
        report=WORK/(part+'-build.json')
        run('tools/patch_ext4_candidate.py','--source',ROOT/'extracted/r8q'/(part+'.img'),
            '--plan',plans/(part+'-plan.json'),'--output',out/(part+'.img'),'--report',report)
        run('tools/verify_ext4_tree_diff.py','--before',ROOT/'extracted/r8q'/(part+'.img'),
            '--after',out/(part+'.img'),'--build-report',report,'--report',WORK/(part+'-tree-diff.json'))
    run('tools/verify_p1_policy.py','--checker',ROOT/'build/check-contexts','--require-checker',
        '--output',WORK/'policy')
    policy=json.loads((WORK/'policy/result.json').read_text())
    if policy['status']!='ACTUAL_P1_CIL_CAPABILITIES_AND_CONTEXTS_PASSED_HOST_ONLY' or policy['contexts']['invalid']:
        raise ValueError('Actual rebuilt policy/context checks did not pass')
    if args.host_tools:
        host=args.host_tools.resolve();pin=json.loads((ROOT/'ci-r8q/pins/official-otatools.json').read_text())
        verify_named_file(host/'bin/checkvintf',pin['checkvintf_sha256'])
        link=ROOT/'tools/p1-host/aosp';link.parent.mkdir(parents=True,exist_ok=False);link.symlink_to(host,target_is_directory=True)
        run('tools/verify_p1_vintf.py','--output',WORK/'vintf')
    composition=dict(reviewed)
    composition['partitions']=[dict(row)for row in reviewed['partitions']]
    for row in composition['partitions']:
        if row['partition']=='product':continue
        image=out/(row['partition']+'.img')
        row.update(file=str(image.relative_to(ROOT)),bytes=image.stat().st_size,sha256=digest(image),source='P1 reconstructed current build')
    composition.update(status='P1_REBUILT_HOST_CHECKED_NOT_BOOT_TESTED',boot_confirmed=False)
    plan=WORK/'composition.json';write_json(plan,composition)
    super_image=out/'super-r8q-hyperos-p1.img';super_report=WORK/'super-build.json'
    run('tools/build_super_p1.py','--plan',plan,'--output',super_image,'--report',super_report)
    independent_super(super_image,super_report)
    images=[dict(partition='super',file=str(super_image.relative_to(ROOT)),bytes=super_image.stat().st_size,sha256=digest(super_image)),
            dict(partition='boot',file=str(boot.relative_to(ROOT)),bytes=67108864,sha256=BOOT_SHA),
            dict(partition='dtbo',file='candidates/p0/dtbo-r8q-p0.img',bytes=10485760,sha256=DTBO_SHA)]
    write_json(WORK/'package-images.json',dict(name='HyperOS4-R8Q-P1',
        status='EXPERIMENTAL_BOOT_TEST_NOT_STABLE',boot_confirmed=False,images=images,
        limits=['Host kernel/FCM4/HAL compatibility findings remain; no stable ROM claim.',
                'Raw ext4/LP hashes are computed per build because filesystem bookkeeping timestamps may differ.']))
    if args.discard_intermediate_images:
        removed=[]
        for row in composition['partitions']:
            if row['partition']=='product':continue
            image=ROOT/row['file']
            verify_named_file(image,row['sha256'],row['bytes'])
            image.unlink()
            removed.append(dict(file=row['file'],sha256=row['sha256'],bytes=row['bytes'],
                                recovery='Verified logical partition '+row['partition']+' in '+str(super_image.relative_to(ROOT))))
        write_json(WORK/'intermediate-cleanup.json',dict(removed=removed,original_source_images_removed=False,
                   reason='Free temporary space for gzip staging and final single ZIP; verified bytes retained in super'))
    print('P1 reconstruction and readback finished. Images ready for the separate single-ZIP packager.',flush=True)


if __name__=='__main__':main()
