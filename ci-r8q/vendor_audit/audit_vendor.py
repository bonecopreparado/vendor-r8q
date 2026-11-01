"""Portable offline vendor comparison. No network, mounts or phone operations."""
from pathlib import Path
import argparse
import collections
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import zipfile

from ext4_readonly import Ext4

BLOCK = 4096
SOURCE_BYTES = 936067987
SOURCE_SHA = '2d80788f5336cf82aa1a3e8c625f8942aac410be014a820186369173946199af'
TRANSFER_SHA = '842d27abf8b27160c57ebf8bf0872c358e4adb75c374f15c6b7e947794a70e26'
IMAGE_BYTES = 1687379968
BASELINE_SHA = '18e48f734c31f263f330786ffea841738a733784da05b5b6d86b5e5217d82d5f'
BASELINE_BYTES = 1647726592
MAX_HASH_FILE = 64 * 1024**2
MAX_CONFIG = 8 * 1024**2


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_internal(path):
    return isinstance(path, str) and path.startswith('/') and all(
        p not in ('.', '..') and '\\' not in p and '\0' not in p for p in path.split('/')[1:])


def selected_config(path):
    return path in ('/build.prop', '/default.prop', '/ueventd.rc') or path.startswith('/etc/') and (
        path.startswith('/etc/selinux/') or
        path.endswith(('.cil', '.rc', '.xml', '.prop', '.json', '.sha256', '.txt', '.pb', '.conf')) or
        '/fstab' in path)


def collect(image, destination):
    files, exports = [], []
    todo, seen = ['/'], set()
    with Ext4(image) as fs:
        metadata = dict(block_size=fs.block_size, blocks=fs.block_count,
                        incompat=hex(fs.incompat), ro_compat=hex(fs.ro_compat))
        while todo:
            directory = todo.pop()
            if directory in seen:
                continue
            seen.add(directory)
            # Ext4.list_dir returns (name, is_directory), not dictionaries.
            for name, _ in fs.list_dir(directory):
                path = directory.rstrip('/') + '/' + name
                if not safe_internal(path):
                    raise ValueError('Unsafe filesystem path: ' + repr(path))
                info = fs.stat(path, follow_symlinks=False)
                row = dict(path=path, mode=info['mode'], uid=info['uid'], gid=info['gid'], bytes=info['size'])
                if stat.S_ISDIR(info['mode']):
                    todo.append(path)
                    continue
                if stat.S_ISLNK(info['mode']):
                    row.update(type='symlink', target=fs.readlink(path))
                elif stat.S_ISREG(info['mode']):
                    row['type'] = 'regular'
                    if info['size'] <= MAX_HASH_FILE:
                        data = fs.read_file(path, max_bytes=MAX_HASH_FILE)
                        row['sha256'] = hashlib.sha256(data).hexdigest()
                        if selected_config(path) and len(data) <= MAX_CONFIG:
                            target = destination / 'configs' / path.lstrip('/')
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(data)
                            exports.append(row.copy())
                    else:
                        row['hash_skipped'] = 'regular file exceeds 64 MiB inspection limit'
                else:
                    row['type'] = 'special'
                files.append(row)
                if len(files) > 30000 or len(seen) > 5000:
                    raise ValueError('Filesystem tree exceeds inspection bounds')
                if len(files) % 500 == 0:
                    print('Inventory:', len(files), 'files', flush=True)
    return dict(files=sorted(files, key=lambda r:r['path']), exports=sorted(exports, key=lambda r:r['path']), filesystem=metadata)


def write_archive(output, members):
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 31, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=6)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('Archive CRC failed')


def export_baseline(image, output):
    image, output = Path(image), Path(output)
    if image.stat().st_size != BASELINE_BYTES or file_sha(image) != BASELINE_SHA:
        raise ValueError('Baseline image does not match the verified original R8Q vendor')
    output.mkdir(parents=True, exist_ok=False)
    inventory = collect(image, output)
    baseline = dict(schema_version=1, label='Original Adrian ColorOS vendor used by P0',
                    image=dict(bytes=BASELINE_BYTES, sha256=BASELINE_SHA), **inventory)
    metadata = (json.dumps(baseline, indent=2) + '\n').encode()
    (output / 'baseline.json').write_bytes(metadata)
    members = {'baseline.json': metadata}
    for row in baseline['exports']:
        name = 'configs' + row['path']
        members[name] = (output / name).read_bytes()
    destination = output / 'baseline-vendor.zip'
    write_archive(destination, members)
    print(destination, destination.stat().st_size, file_sha(destination), flush=True)
    return destination


def load_baseline(path):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 5000 or len(set(archive.namelist())) != len(infos):
            raise ValueError('Baseline archive has excessive or duplicate members')
        if sum(i.file_size for i in infos) > 128 * 1024**2 or any(i.flag_bits & 1 for i in infos):
            raise ValueError('Baseline archive is too large or encrypted')
        data = archive.read('baseline.json')
        baseline = json.loads(data)
        if baseline.get('schema_version') != 1 or baseline.get('image') != dict(bytes=BASELINE_BYTES, sha256=BASELINE_SHA):
            raise ValueError('Unexpected baseline identity')
        expected = {'baseline.json'} | {'configs' + r['path'] for r in baseline['exports']}
        if set(archive.namelist()) != expected:
            raise ValueError('Unexpected baseline members')
        configs = {}
        for row in baseline['exports']:
            if not safe_internal(row['path']):
                raise ValueError('Unsafe baseline path')
            blob = archive.read('configs' + row['path'])
            if hashlib.sha256(blob).hexdigest() != row['sha256']:
                raise ValueError('Baseline config hash differs: ' + row['path'])
            configs[row['path']] = blob
        if archive.testzip() is not None:
            raise ValueError('Baseline CRC failed')
    return baseline, configs


def parse_transfer(blob, expected_bytes=IMAGE_BYTES):
    lines = blob.decode('ascii').splitlines()
    if len(lines) < 5 or lines[0] != '4' or lines[2:4] != ['0', '0']:
        raise ValueError('Expected full non-incremental OTA v4 transfer list')
    declared = int(lines[1]) * BLOCK
    if declared != expected_bytes:
        raise ValueError('Transfer header capacity differs')
    commands = []
    for line in lines[4:]:
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 2 or fields[0] not in ('new', 'zero', 'erase'):
            raise ValueError('Unsupported or incremental transfer command')
        numbers = [int(x) for x in fields[1].split(',')]
        if not numbers or numbers[0] != len(numbers)-1 or numbers[0] % 2:
            raise ValueError('Malformed transfer range count')
        pairs = list(zip(numbers[1::2], numbers[2::2]))
        if not pairs or any(a < 0 or b <= a or b * BLOCK > declared for a,b in pairs):
            raise ValueError('Transfer range outside image')
        commands.append((fields[0], pairs))
    spans = sorted((a,b) for _, pairs in commands for a,b in pairs)
    cursor = 0
    for start,end in spans:
        if start != cursor:
            raise ValueError('Transfer ranges overlap or leave unaccounted gaps')
        cursor = end
    if cursor * BLOCK != declared:
        raise ValueError('Transfer list does not cover the full image')
    return commands


def reconstruct(source, transfer_blob, output, expected_bytes=IMAGE_BYTES):
    import brotli
    commands = parse_transfer(transfer_blob, expected_bytes)
    output = Path(output)
    staging = output.with_suffix(output.suffix + '.partial')
    if output.exists():
        raise FileExistsError('Reconstructed image already exists')
    decoder = brotli.Decompressor()
    buffer = bytearray()
    written, next_progress = 0, 128 * 1024**2
    with Path(source).open('rb') as stream, staging.open('xb') as image:
        image.truncate(expected_bytes)
        for command,pairs in commands:
            if command != 'new':
                continue # A newly-created sparse file reads zero in untouched ranges.
            for start,end in pairs:
                image.seek(start * BLOCK)
                left = (end-start) * BLOCK
                while left:
                    count = min(left, 1024**2)
                    while len(buffer) < count:
                        packed = stream.read(256 * 1024)
                        if not packed:
                            raise ValueError('Brotli ended before transfer ranges')
                        buffer.extend(decoder.process(packed))
                    image.write(buffer[:count])
                    del buffer[:count]
                    left -= count; written += count
                    if written >= next_progress:
                        print('Reconstructed new data:', written, 'bytes', flush=True)
                        next_progress += 128 * 1024**2
        if buffer:
            raise ValueError('Transfer list left unconsumed Brotli output')
        while packed := stream.read(256 * 1024):
            if decoder.process(packed):
                raise ValueError('Brotli contains extra data not accounted by transfer list')
        if not decoder.is_finished():
            raise ValueError('Brotli stream is incomplete')
    staging.rename(output)
    return dict(bytes=expected_bytes, sha256=file_sha(output), new_bytes=written,
                commands=dict(collections.Counter(c for c,_ in commands)))


def properties(blob):
    values = {}
    for line in blob.decode('utf-8', errors='replace').splitlines():
        text = line.strip()
        if text and not text.startswith('#') and '=' in text:
            key, value = text.split('=',1)
            values[key] = value
    return values


def compare(baseline, current, old_configs, new_configs):
    old = {r['path']:r for r in baseline['files']}
    new = {r['path']:r for r in current['files']}
    common = old.keys() & new.keys()
    result = dict(added=sorted(new.keys()-old.keys()), removed=sorted(old.keys()-new.keys()),
                  changed_sha256=sorted(p for p in common if old[p].get('sha256') and new[p].get('sha256') and old[p]['sha256']!=new[p]['sha256']),
                  same_sha256=sorted(p for p in common if old[p].get('sha256') and old[p].get('sha256')==new[p].get('sha256')),
                  metadata_changed=sorted(p for p in common if any(old[p].get(k)!=new[p].get(k) for k in ('mode','uid','gid','type','target'))),
                  hash_not_comparable=sorted(p for p in common if not old[p].get('sha256') or not new[p].get('sha256')))
    changed = set(result['changed_sha256']) | set(result['added']) | set(result['removed'])
    result['config_categories'] = {name:sorted(p for p in changed if predicate(p)) for name,predicate in {
        'selinux':lambda p:p.startswith('/etc/selinux/'),
        'vintf':lambda p:p.startswith('/etc/vintf/'),
        'init':lambda p:p.startswith('/etc/init/') and p.endswith('.rc'),
        'fstab':lambda p:'/fstab' in p,
        'properties':lambda p:p.endswith('.prop')}.items()}
    result['property_files'] = {}
    for path in sorted((old_configs.keys() | new_configs.keys())):
        if not path.endswith('.prop'):
            continue
        a,b = properties(old_configs.get(path,b'')), properties(new_configs.get(path,b''))
        result['property_files'][path] = dict(old=a, new=b, changed={k:dict(old=a.get(k),new=b.get(k))
                                                                 for k in sorted(a.keys()|b.keys()) if a.get(k)!=b.get(k)})
    result['counts'] = {k:len(result[k]) for k in ('added','removed','changed_sha256','same_sha256','metadata_changed','hash_not_comparable')}
    return result


def audit(source, transfer, baseline_path, output):
    source, transfer, output = Path(source), Path(transfer), Path(output)
    if source.stat().st_size != SOURCE_BYTES or file_sha(source) != SOURCE_SHA:
        raise ValueError('Downloaded Brotli asset differs from the pinned GitHub release')
    blob = transfer.read_bytes()
    if hashlib.sha256(blob).hexdigest() != TRANSFER_SHA:
        raise ValueError('Transfer list differs from the provided matching full list')
    baseline, old_configs = load_baseline(baseline_path)
    output.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(output).free < IMAGE_BYTES + 256 * 1024**2:
        raise ValueError('Need at least image capacity plus 256 MiB free')
    image = output / 'vendor-coloros1610.img'
    identity = reconstruct(source, blob, image)
    checker = shutil.which('e2fsck')
    fsck = dict(status='not_available', limitation='Ext4 reader does not verify metadata/data checksums or replay journal')
    if checker:
        result = subprocess.run([checker, '-f', '-n', str(image)], capture_output=True, text=True, timeout=180)
        (output / 'e2fsck.txt').write_text(result.stdout+result.stderr)
        fsck = dict(status='checked_read_only', exit_code=result.returncode)
        if result.returncode != 0:
            raise ValueError('e2fsck -fn did not report a clean image; inspect e2fsck.txt')
    current = collect(image, output)
    new_configs = {r['path']:(output/'configs'/r['path'].lstrip('/')).read_bytes() for r in current['exports']}
    comparison = compare(baseline, current, old_configs, new_configs)
    report = dict(schema_version=1, status='OFFLINE_CONTENT_COMPARISON_NOT_BOOT_VALIDATION',
                  claimed_version='ColorOS 16.0.10 per user; compare actual property declarations below',
                  source=dict(bytes=SOURCE_BYTES,sha256=SOURCE_SHA,transfer_sha256=TRANSFER_SHA),
                  image=identity, baseline_image=baseline['image'], fsck=fsck, **current, comparison=comparison,
                  limitations=['No boot, HAL, SELinux compilation or ABI compatibility validation',
                               'Ext4 reader omits xattrs/checksums/journal replay; unsupported features reject',
                               'Files above 64 MiB are not hashed; symlinks compared separately',
                               'Property files describe declarations, not effective Android property load order',
                               'Different contents/version declarations do not prove better suitability'])
    encoded = (json.dumps(report,indent=2)+'\n').encode()
    (output/'analysis.json').write_bytes(encoded)
    members = {'analysis.json':encoded}
    for path, data in old_configs.items(): members['baseline-configs'+path]=data
    for path, data in new_configs.items(): members['new-configs'+path]=data
    if (output/'e2fsck.txt').exists(): members['e2fsck.txt']=(output/'e2fsck.txt').read_bytes()
    archive = output/'RELATORIO-VENDOR-1610.zip'
    write_archive(archive,members)
    print('Comparison counts:', comparison['counts'], flush=True)
    print('REPORT:',archive,archive.stat().st_size,file_sha(archive),flush=True)
    return archive


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    baseline=sub.add_parser('export-baseline')
    baseline.add_argument('--image',type=Path,required=True)
    baseline.add_argument('--output',type=Path,required=True)
    run=sub.add_parser('audit')
    run.add_argument('--source',type=Path,required=True)
    run.add_argument('--transfer',type=Path,required=True)
    run.add_argument('--baseline',type=Path,required=True)
    run.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='export-baseline':export_baseline(args.image,args.output)
    else:audit(args.source,args.transfer,args.baseline,args.output)


if __name__=='__main__':main()
