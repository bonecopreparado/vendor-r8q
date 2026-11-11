"""Report library names in the pinned vendor inventory, without extracting SOs.

Presence in this original inventory does not establish the currently mounted
phone's files, ELF symbols, linker namespace, APEX activation or SELinux access.
"""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BASELINE_BYTES = 2306551
BASELINE_SHA = '320fab260c5b571fb3cde1288d30d67b904ef7c5381e4b1d73715ddf2867699e'
IMAGE_SHA = '18e48f734c31f263f330786ffea841738a733784da05b5b6d86b5e5217d82d5f'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'ci-r8q/vendor_audit/data/baseline-vendor.zip')
    parser.add_argument('--build-report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise ValueError('Output exists; preserving it')
    archive = args.baseline
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size != BASELINE_BYTES:
        raise ValueError('Pinned vendor baseline size/type differs')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != BASELINE_SHA:
        raise ValueError('Pinned vendor baseline SHA256 differs')
    if args.build_report.is_symlink() or args.build_report.stat().st_size > 1024 * 1024:
        raise ValueError('Expected bounded regular build report')
    build = json.loads(args.build_report.read_bytes())
    if build.get('status') != 'COMPILED_AND_ELF_INSPECTED_NOT_PHONE_TESTED':
        raise ValueError('Probe did not pass its actual compile/ELF inspection')
    needed = build['elf']['needed']
    if not isinstance(needed, list) or len(needed) > 20 or any('/' in name for name in needed):
        raise ValueError('Unexpected dependency names')
    with zipfile.ZipFile(archive) as package:
        info = package.getinfo('baseline.json')
        if info.file_size > 16 * 1024 * 1024:
            raise ValueError('Inventory exceeds bound')
        baseline = json.loads(package.read(info))
        if baseline.get('schema_version') != 1 or baseline.get('image', {}).get('sha256') != IMAGE_SHA:
            raise ValueError('Unexpected original image identity/schema')
        files = baseline['files']
        if not isinstance(files, list) or len(files) > 30000:
            raise ValueError('Inventory exceeds file bound')
        libraries = {
            name: {'vendor_inventory_matches': [row for row in files
                   if row.get('path') == '/lib64/' + name],
                   'runtime_resolution_confirmed': False}
            for name in needed
        }
        service_matches = [row for row in files
                           if row.get('path', '').startswith('/bin/') and 'composer' in row['path']]
    report = {'scope': 'ORIGINAL_PINNED_VENDOR_INVENTORY_ONLY_NOT_PHONE_LINKER_TEST',
              'baseline_zip_sha256': BASELINE_SHA, 'vendor_image_sha256': IMAGE_SHA,
              'inventory_file_count': len(files), 'probe_sha256': build['output']['sha256'],
              'libraries': libraries, 'composer_service_inventory': service_matches,
              'note': 'Libraries absent from vendor may be LLNDK/VNDK supplied through system/APEX; absence here is not proof of missing runtime dependency.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
