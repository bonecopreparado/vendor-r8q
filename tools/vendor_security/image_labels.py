"""Audit or repair only the pinned Vendor labels in a separate ext4 image copy."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import patch_ext4_candidate as ext4
import package_vendor_security as package


def decode_label(metadata):
    value = bytes.fromhex(metadata['xattrs'].get('security.selinux', ''))
    label = value.rstrip(b'\0').decode('ascii')
    if not re.fullmatch(r'u:object_r:[a-z0-9_]+:s0', label):
        raise ValueError('Missing or unsupported original SELinux label')
    return label


def inspect(image, workspace, targets):
    fs = ext4.Ext4(image, workspace)
    rows = []
    for spec in targets:
        relative = spec['path']
        path = '/' if relative == '.' else ext4.checked_path('/'+relative)
        for ancestor in reversed(Path(path).parents):
            if fs.stat(str(ancestor))['type'] != 'directory':
                raise ValueError('A label target crosses a symlink/non-directory')
        metadata = fs.stat(path) if path == '/' else fs.regular(path)
        if path == '/':
            if metadata['type'] != 'directory':
                raise ValueError('Vendor root must be a directory')
        elif hashlib.sha256(fs.content(path)).hexdigest() != spec['sha256']:
            raise ValueError('Pinned Vendor context content differs: '+path)
        current = decode_label(metadata)
        allowed = {spec['label'], 'u:object_r:vendor_file:s0'}
        allowed.add('u:object_r:vendor_apex_file:s0' if path == '/' else 'u:object_r:vendor_configs_file:s0')
        if current not in allowed:
            raise ValueError('Unreviewed original Vendor label: '+path)
        rows.append(dict(path=path, current=current, expected=spec['label'],
                         correct=current == spec['label'], metadata=metadata))
    return rows


def repair(source, output, source_sha256, targets=None):
    source, output = Path(source), Path(output)
    if source.is_symlink() or not source.is_file() or output.exists() or output.is_symlink() or source.resolve() == output.resolve():
        raise ValueError('Use a regular source image and a new, separate output')
    if not ext4.valid_digest(source_sha256) or ext4.sha_file(source) != source_sha256:
        raise ValueError('Source image SHA256 differs')
    if targets is None:
        targets = package.profile()['labels']
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='r8q-vendor-labels-') as name:
        work = Path(name)
        ext4.fsck(source)
        rows = inspect(source, work, targets)
        fd, name = tempfile.mkstemp(prefix='.r8q-vendor-labels-', suffix='.img', dir=output.parent)
        os.close(fd)
        stage = Path(name)
        try:
            shutil.copyfile(source, stage)
            if ext4.sha_file(stage) != source_sha256:
                raise ValueError('Independent source image copy differs')
            fs = ext4.Ext4(stage, work)
            for row in rows:
                expected = copy.deepcopy(row['metadata'])
                expected['xattrs']['security.selinux'] = (row['expected'].encode()+b'\0').hex()
                fs.restore(row['path'], expected)
                if not ext4.metadata_equal(expected, fs.stat(row['path'])):
                    raise ValueError('Unrelated inode metadata changed: '+row['path'])
            after = inspect(stage, work, targets)
            if not all(row['correct'] for row in after):
                raise ValueError('Vendor label readback failed')
            check = ext4.fsck(stage)
            if ext4.sha_file(source) != source_sha256:
                raise ValueError('Source image changed during repair')
            candidate_sha = ext4.sha_file(stage)
            with stage.open('rb') as stream:
                os.fsync(stream.fileno())
            os.link(stage, output)
        finally:
            if stage.exists(): stage.unlink()
    return dict(status='VENDOR_LABELS_REPAIRED_OFFLINE_NOT_BOOT_TESTED',
                source_sha256=source_sha256, candidate_sha256=candidate_sha,
                source_preserved=True, file_contents_preserved=True,
                changes=[{k: r[k] for k in ('path','current','expected','correct')} for r in rows],
                candidate_e2fsck=check, hardware_boot_confirmed=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--source-sha256', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    if a.report.exists() or a.report.is_symlink() or a.report.resolve() in {a.source.resolve(), a.output.resolve()}:
        raise ValueError('Use a fresh report path distinct from the image paths')
    result = repair(a.source, a.output, a.source_sha256)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    with a.report.open('x') as stream:
        stream.write(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__': main()
