"""Package only boot for the existing P1r5 LATEFS installation."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

from package_p1_single import INSTALLER, helper_blob, info

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/kernel_nflog/susfs22'))
import repack_verified as repack

BASE_BOOT = '0d1263cb81848ae5b935d89df1224f42f6160e452950dd627550901926cd66c2'
SOURCE_COMMIT = '80fd3830478095a4cdeae4e1e708f30b9ca5cef8'
BOOT_BYTES = repack.BOOT_BYTES
README = """For the exact P1r5 LATEFS VOLD-LOG already installed on Snapdragon r8q only.
Install R8Q-P1r5-LATEFS-KEYSTORE-LOG.zip in recovery, then reboot once into
recovery and finally into System. If stuck, wait about three minutes and
send a fresh TAR from the same collector. This preserves early keystore warnings and abort details in last_kmsg. Android boot remains unverified.
Keep R8Q-P1r5-LATEFS-RESTORE-VOLD-LOG.zip accessible to restore the previous boot
image after testing. Neither ZIP requires Data mounted.
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def render(before, after, compressed, helper, action):
    values = dict(FROM=before, TO=after, COMPRESSED=compressed, HELPER=helper)
    if not all(re.fullmatch('[0-9a-f]{64}', value) for value in values.values()) or before == after:
        raise ValueError('Expected distinct pinned boot hashes and payload digests')
    if action not in ('diagnostic', 'restore'):
        raise ValueError('Unexpected boot operation')
    template = (ROOT / 'tools/mount_wait/installer.sh').read_text()
    for key, value in dict(values, ACTION=action).items():
        marker = '@@' + key + '@@'
        if template.count(marker) != 1:
            raise ValueError('Expected one recovery template field: ' + key)
        template = template.replace(marker, value)
    if '@@' in template:
        raise ValueError('Unexpected recovery template field')
    return template.encode()


def emit(output, before, target, helper, notice, action, evidence):
    compressed = gzip.compress(target, compresslevel=6, mtime=0)
    after = sha(target)
    installer = render(before, after, sha(compressed), sha(helper), action)
    manifest = dict(status='EXPERIMENTAL_BOOT_ONLY_NOT_HARDWARE_TESTED',
                    action=action, installed_boot_sha256=before, boot_sha256=after,
                    bytes=len(target), helper_sha256=sha(helper), evidence=evidence)
    files = {
        INSTALLER: installer,
        'META-INF/com/google/android/updater-script': b'# Shell installer\n',
        'tools/bootio': helper,
        'images/boot.img.gz': compressed,
        'MOUNT-WAIT-MANIFEST.json': (json.dumps(manifest, indent=2) + '\n').encode(),
        'README-ENGLISH.txt': README.encode(),
        'licenses/android-ndk-notices.txt': notice,
        'licenses/PROJECT-LICENSE.txt': (ROOT / 'LICENSE').read_bytes(),
    }
    with zipfile.ZipFile(output, 'x', allowZip64=False) as package:
        for name, data in files.items():
            package.writestr(info(name, name in (INSTALLER, 'tools/bootio')), data)
    with zipfile.ZipFile(output) as package:
        if package.namelist() != list(files) or any(package.read(name) != data for name, data in files.items()):
            raise ValueError('Package did not round-trip')
        if gzip.decompress(package.read('images/boot.img.gz')) != target:
            raise ValueError('Packed boot bytes differed')
    with output.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    output.with_suffix('.zip.sha256').write_text(f'{digest}  {output.name}\n')
    return dict(file=output.name, sha256=digest, zip_bytes=output.stat().st_size, manifest=manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'previous', 'image', 'summary', 'helper', 'provenance', 'ndk-notice', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for path, maximum in (
        (args.source, BOOT_BYTES), (args.previous, BOOT_BYTES), (args.image, BOOT_BYTES),
        (args.summary, 1024**2), (args.provenance, 1024**2), (args.helper, 2*1024**2),
        (args.ndk_notice, 8*1024**2),
    ):
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
            parser.error('Invalid input size or file: ' + str(path))
    previous = args.previous.read_bytes()
    if len(previous) != BOOT_BYTES or sha(previous) != BASE_BOOT:
        raise ValueError('Reproduced previous boot differs from the published LATEFS VOLD-LOG release')
    kernel = args.image.read_bytes()
    provenance = json.loads(args.provenance.read_text())
    if provenance.get('source_commit') != SOURCE_COMMIT or provenance.get('kernel_sha256') != sha(kernel):
        raise ValueError('The provenance does not bind the trace kernel')
    candidate, proof = repack.repack(args.source.read_bytes(), kernel, json.loads(args.summary.read_text()))
    old_parts, new_parts = repack.sections(previous), repack.sections(candidate)
    for part in ('ramdisk', 'second', 'recovery_dtbo', 'dtb'):
        if old_parts[part] != new_parts[part]:
            raise ValueError('Non-kernel boot section changed: ' + part)
    trailer = b'SEANDROIDENFORCE\0'
    for parts in (old_parts, new_parts):
        if not parts['tail'].startswith(trailer) or any(parts['tail'][len(trailer):]):
            raise ValueError('Unexpected Samsung trailer or padding')
    if old_parts['page'] != new_parts['page']:
        raise ValueError('Boot image page size differs')
    for start, end in ((0, 8), (12, 576), (608, old_parts['page'])):
        if previous[start:end] != candidate[start:end]:
            raise ValueError('Boot load addresses or command line differ')
    helper = helper_blob(args.helper, require_arm64=True)
    if helper.count(b'R8Q_BOOTIO_PRODUCTION_BLOCK_ONLY_V1') != 1 or b'R8Q_BOOTIO_TEST_REGULAR_FILES_V1' in helper:
        raise ValueError('Expected production-only boot helper')
    args.output.mkdir(parents=True, exist_ok=True)
    outputs = []
    for action, suffix, before, target in (
        ('diagnostic', 'KEYSTORE-LOG', BASE_BOOT, candidate),
        ('restore', 'RESTORE-VOLD-LOG', sha(candidate), previous),
    ):
        path = args.output / f'R8Q-P1r5-LATEFS-{suffix}.zip'
        outputs.append(emit(path, before, target, helper, args.ndk_notice.read_bytes(), action,
                            dict(kernel_provenance=provenance, repack=proof)))
    (args.output / 'mount-wait-build.json').write_text(json.dumps(outputs, indent=2) + '\n')


if __name__ == '__main__':
    main()
