"""Package a cumulative P1r4-only kernel experiment after real build checks."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools/kernel_nflog/susfs22'))
import repack_verified
import package_vendor_security
from package_p1_single import helper_blob, info

INSTALLER = 'META-INF/com/google/android/update-binary'
PRODUCTION = b'R8Q_BOOTIO_PRODUCTION_BLOCK_ONLY_V1'
TEST = b'R8Q_BOOTIO_TEST_REGULAR_FILES_V1'
ORIGINAL = 'cb9c55af64889209eafe2c078b349b533b6728146fb859c731ba23067fdf18a6'
SOURCE_COMMIT = '3827a7dcee14c621ed4b230c36609502509be5ea'
README = '''R8Q MEMORY R3 EXPERIMENTAL — CUMULATIVE ADDON FOR INSTALLED P1r4 ONLY

This is not the complete ROM and cannot be installed over Samsung stock.
It includes the R2 Samsung IPA/IPA UC firmware and exact Vendor-label repair.
It additionally installs a fully linked kernel with MEMCG, PSI and v1 freezer
enabled. KernelSU, all enabled SUSFS options, NFLOG, ramdisk, DTB and boot
arguments are preserved. SELinux options are preserved; this does not force
permissive. The cause of the LMKD camopt crash and Android boot remain unproven.

1. Verify the ZIP SHA256 against its GitHub Release checksum.
2. Boot TWRP/OrangeFox, charge to 50% or connect a charger.
3. Mount Data read-write in recovery, with at least 96 MiB free. Do not format.
4. Install this compressed ZIP. No other payload files or installer creation.
5. Require: R8Q memory R3 applied: R2 and kernel verified.
6. Reboot recovery, then System once. If stuck/restarting, return to recovery
   and collect fresh last_kmsg, pstore and recovery.log. Existing V6 captures
   are retained. A recovery getenforce does not describe the attempted Android.

The installer accepts only the exact P1r4 boot or this exact new candidate.
Before Vendor changes or boot writes, it keeps and verifies the original
64 MiB boot at /data/r8q-boot-backups/P1r4-<original-sha256>.img.
Unknown/corrupted existing backups are preserved and cause an abort.
The source is checked using fresh O_DIRECT reads. Writes are flushed and
cache-invalidated, then read again through O_DIRECT. A detected boot write
or readback failure triggers restoration from the persistent verified backup.
R2 may remain applied if the subsequent kernel component fails.
Power interruption may still require restoring boot from recovery/stock.

Data/Metadata/EFS/Persist/bootloader/APNHLOS are not flashed or formatted.
Only the private backup directory is created in Data. Boot and the reviewed
Vendor files/labels inside Super are modified. The Super partition layout,
its other logical partitions, DTBO, recovery and user-media directories are
preserved. If a guard fails,
send recovery.log; do not bypass it. No successful hardware boot is claimed.
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def render(boot_sha, gzip_sha, helper_sha, security_sha):
    values = dict(BOOT_SHA=boot_sha, GZIP_SHA=gzip_sha,
                  HELPER_SHA=helper_sha, SECURITY_SHA=security_sha)
    if any(not re.fullmatch('[0-9a-f]{64}', value) for value in values.values()):
        raise ValueError('Expected exact SHA256 digests')
    if boot_sha == ORIGINAL:
        raise ValueError('The candidate must differ from the original P1r4 boot')
    script = (ROOT/'tools/boot_memory/installer.sh').read_text()
    for key, value in values.items():
        marker = '@@'+key+'@@'
        if script.count(marker) != 1:
            raise ValueError('Installer marker differs: '+key)
        script = script.replace(marker, value)
    if '@@' in script:
        raise ValueError('Unresolved installer marker')
    return script.encode()


def build(output, source, image, summary, helper, provenance, ndk_notice):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Use a new output ZIP; no old build is overwritten')
    if provenance.get('source_commit') != SOURCE_COMMIT:
        raise ValueError('Kernel source workflow commit differs')
    candidate, repack = repack_verified.repack(source, image, summary)
    if provenance.get('kernel_sha256') != sha(image):
        raise ValueError('Dependency provenance does not bind the actual Image')
    native = helper_blob(helper, require_arm64=True)
    if native.count(PRODUCTION) != 1 or TEST in native:
        raise ValueError('Expected production block-only native helper')
    if not ndk_notice or len(ndk_notice) > 8*1024**2:
        raise ValueError('Real bounded Android NDK notices are required')
    security = package_vendor_security.render().encode('utf-8')
    compressed = gzip.compress(candidate, compresslevel=6, mtime=0)
    installer = render(sha(candidate), sha(compressed), sha(native), sha(security))
    report = dict(schema_version=1, status='PACKAGED_EXPERIMENTAL_NOT_BOOT_TESTED',
        original_boot_sha256=ORIGINAL, candidate_boot_sha256=sha(candidate),
        boot_bytes=len(candidate), kernel_source=provenance, repack=repack,
        security_r2_sha256=sha(security), helper_sha256=sha(native),
        helper_source_sha256=sha((ROOT/'tools/boot_memory/boot_io.c').read_bytes()),
        helper_production_block_only=True, persistent_original_boot_backup_required=True,
        direct_block_readback_required=True, external_payloads_required=False,
        data_formatted=False, hardware_boot_confirmed=False)
    members = {INSTALLER: installer, 'META-INF/com/google/android/updater-script': b'# Shell installer\n',
               'tools/bootio': native, 'scripts/security-r2.sh': security,
               'images/boot.img.gz': compressed, 'R3-MANIFEST.json': (json.dumps(report,indent=2)+'\n').encode(),
               'README-ENGLISH.txt': README.encode(),
               'licenses/android-ndk-notices.txt': ndk_notice,
               'licenses/PROJECT-LICENSE.txt': (ROOT/'LICENSE').read_bytes()}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', allowZip64=False) as package:
        for name, data in members.items():
            package.writestr(info(name, name in (INSTALLER, 'tools/bootio')), data)
    with zipfile.ZipFile(output) as package:
        if set(package.namelist()) != set(members) or len(package.infolist()) != len(members):
            raise ValueError('ZIP member table differs')
        for name, data in members.items():
            if package.read(name) != data:
                raise ValueError('ZIP readback differs: '+name)
        if gzip.decompress(package.read('images/boot.img.gz')) != candidate:
            raise ValueError('Actual packaged candidate differs')
    digest = sha(output.read_bytes())
    output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n')
    (output.parent/'R3-TESTER-ENGLISH.txt').write_text(README)
    report.update(zip_sha256=digest, zip_bytes=output.stat().st_size, zip_name=output.name)
    (output.parent/'R3-build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source','image','summary','helper','provenance','ndk-notice','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    paths = (args.source,args.image,args.summary,args.helper,args.provenance,args.ndk_notice)
    if any(p.is_symlink() or not p.is_file() for p in paths):
        parser.error('Expected regular inputs')
    if any(p.stat().st_size > limit for p,limit in zip(paths,(67108864,67108864,1024**2,2*1024**2,1024**2,8*1024**2))):
        parser.error('Input exceeds its bound')
    result = build(args.output,args.source.read_bytes(),args.image.read_bytes(),
        json.loads(args.summary.read_text()),args.helper,json.loads(args.provenance.read_text()),args.ndk_notice.read_bytes())
    print(json.dumps({k:result[k] for k in ('status','zip_name','zip_sha256','zip_bytes','hardware_boot_confirmed')},indent=2))


if __name__ == '__main__': main()
