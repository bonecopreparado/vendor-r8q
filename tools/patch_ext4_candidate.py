"""Patch a copied ext4 image offline, preserving file labels and metadata.

No block devices, mounted filesystems, or in-place source changes are accepted.
Plans must pin the source image and every changed file. Only regular files with
one link may be replaced or deleted; all parent components must be directories.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SAFE_PATH = re.compile(r'/[A-Za-z0-9_@.+/-]+')
SHA = re.compile(r'[0-9a-f]{64}')


def valid_digest(value):
    return isinstance(value,str) and SHA.fullmatch(value) is not None


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_path(value):
    if value == '/':
        return value
    if not isinstance(value, str) or not SAFE_PATH.fullmatch(value):
        raise ValueError('Unsupported ext4 path characters')
    parts = value[1:].split('/')
    if value != '/' and any(part in ('', '.', '..') for part in parts):
        raise ValueError('Noncanonical ext4 path')
    return value


def tool(name):
    local = ROOT/'tools/image-tools/bin'/name
    return str(local) if local.is_file() else shutil.which(name) or name


class Ext4:
    def __init__(self, image, workspace):
        self.image, self.workspace = Path(image), Path(workspace)

    def command(self, command, writable=False, missing_ok=False):
        argv = [tool('debugfs')] + (['-w'] if writable else []) + ['-R', command, str(self.image)]
        result = subprocess.run(argv, capture_output=True, timeout=120)
        errors = [line for line in result.stderr.decode(errors='replace').splitlines()
                  if line.strip() and not re.fullmatch(r'debugfs [0-9.]+ \([^)]+\)', line)]
        if missing_ok and not result.returncode and errors and all('File not found by ext2_lookup' in line for line in errors):
            return None
        if result.returncode or errors:
            raise ValueError('debugfs operation failed: ' + command.split()[0] + ': ' + '\n'.join(errors))
        return result.stdout

    def stat(self, path, missing_ok=False):
        data = self.command('stat ' + checked_path(path), missing_ok=missing_ok)
        if data is None:
            return None
        text = data.decode()
        first = re.search(r'Inode:\s+(\d+)\s+Type:\s+(\w+)\s+Mode:\s+([0-7]+)\s+Flags:\s+(0x[0-9a-fA-F]+)', text)
        owner = re.search(r'User:\s+(\d+)\s+Group:\s+(\d+)\s+Project:\s+(\d+)\s+Size:\s+(\d+)', text)
        links = re.search(r'Links:\s+(\d+)', text)
        generation = re.search(r'Generation:\s+(\d+)\s+Version:\s+0x([0-9a-f]+):([0-9a-f]+)', text)
        times = {key: [int(low,16), int(extra,16)] for key,low,extra in
                 re.findall(r'^\s*(ctime|atime|mtime|crtime):\s+0x([0-9a-f]+):([0-9a-f]+)', text, re.M)}
        if not all((first, owner, links, generation)) or set(times) != {'ctime','atime','mtime','crtime'}:
            raise ValueError('Unrecognized debugfs inode metadata: ' + path)
        record = dict(inode=int(first[1]), type=first[2], mode=int(first[3],8), flags=int(first[4],16),
                      uid=int(owner[1]), gid=int(owner[2]), project=int(owner[3]), size=int(owner[4]),
                      links=int(links[1]), generation=int(generation[1]),
                      version_hi=int(generation[2],16), version_lo=int(generation[3],16), times=times)
        attr_text = self.command('ea_list ' + path).decode()
        attrs = re.findall(r'^\s+([A-Za-z0-9_.-]+) \(\d+\)', attr_text, re.M)
        attr_lines = [line for line in attr_text.splitlines() if line.strip() and line.strip()!='Extended attributes:']
        if len(attrs) != len(attr_lines):
            raise ValueError('Unsupported extended attribute listing')
        record['xattrs'] = {}
        for index, name in enumerate(attrs):
            destination = self.workspace / ('attribute-' + str(index))
            self.command('ea_get -f ' + str(destination) + ' ' + path + ' ' + name)
            record['xattrs'][name] = destination.read_bytes().hex()
        return record

    def regular(self, path):
        record = self.stat(path)
        if record['type'] != 'regular' or record['links'] != 1:
            raise ValueError('Only single-link regular files may be patched: ' + path)
        if record['flags'] not in (0, 0x80000):
            raise ValueError('Unsupported inode flags; encrypted/verity/immutable files are not patched')
        return record

    def content(self, path, limit=8*1024**2):
        record = self.regular(path)
        if record['size'] > limit:
            raise ValueError('Patchable file exceeds 8 MiB')
        data = self.command('cat ' + path)
        if len(data) != record['size']:
            raise ValueError('Short ext4 file read')
        return data

    def restore(self, path, metadata):
        kind = 0o100000 if metadata['type']=='regular' else 0o040000
        fields = dict(uid=metadata['uid'], gid=metadata['gid'], mode=kind|metadata['mode'],
                      projid=metadata['project'], flags=metadata['flags'],
                      generation=metadata['generation'], version_hi=metadata['version_hi'],
                      version_lo=metadata['version_lo'])
        for key, (low, extra) in metadata['times'].items():
            fields[key] = '0x%x' % low
            fields[key + '_extra'] = extra
        for key, value in fields.items():
            self.command('set_inode_field '+path+' '+key+' '+str(value), writable=True)
        for index, (name, value) in enumerate(metadata['xattrs'].items()):
            source = self.workspace / ('restore-attribute-'+str(index))
            source.write_bytes(bytes.fromhex(value))
            self.command('ea_set -f '+str(source)+' '+path+' '+name, writable=True)


def metadata_equal(a,b):
    # Inode allocation, physical extents and directory byte size may change.
    keys = ('type','mode','flags','uid','gid','project','generation','version_hi','version_lo','times','xattrs')
    return all(a[key] == b[key] for key in keys)


def fsck(image, preen=False):
    argv=[tool('e2fsck'), '-f', '-p' if preen else '-n']
    if preen:argv+=['-E','fixes_only']
    result = subprocess.run(argv+[str(image)], capture_output=True, timeout=180)
    report = dict(argv=argv+[str(image)], exit=result.returncode, stdout=result.stdout.decode(errors='replace'),
                  stderr=result.stderr.decode(errors='replace'))
    if result.returncode not in ((0,1) if preen else (0,)):
        raise ValueError('Read-only e2fsck found errors in image: '+report['stdout']+report['stderr'])
    return report


def source_blob(plan_dir, row):
    value = row.get('source')
    if not isinstance(value,str) or Path(value).is_absolute() or '..' in Path(value).parts:
        raise ValueError('Patch content must be relative to the plan directory')
    path = plan_dir / value
    cursor = plan_dir
    for part in Path(value).parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError('Symlink patch input is forbidden')
    if not path.is_file() or path.stat().st_size > 8*1024**2:
        raise ValueError('Patch content is missing or oversized')
    data = path.read_bytes()
    if not valid_digest(row.get('sha256')) or hashlib.sha256(data).hexdigest()!=row['sha256']:
        raise ValueError('New file SHA256 mismatch')
    return data


def patch_image(source, plan_path, output):
    source, plan_path, output = Path(source), Path(plan_path), Path(output)
    if source.is_symlink() or not source.is_file() or output.exists() or output.is_symlink():
        raise ValueError('Source must be a regular image and output must not exist')
    if source.resolve() == output.resolve():
        raise ValueError('In-place image changes are forbidden')
    plan = json.loads(plan_path.read_text())
    if not isinstance(plan,dict) or type(plan.get('schema_version')) is not int or plan['schema_version'] != 1 or not valid_digest(plan.get('source_image_sha256')):
        raise ValueError('A versioned plan with exact source image SHA256 is required')
    source_sha = sha_file(source)
    if source_sha != plan['source_image_sha256']:
        raise ValueError('Source image SHA256 mismatch')
    operations = plan.get('operations')
    if not isinstance(operations,list) or not operations or len(operations)>128:
        raise ValueError('No operations supplied')
    output.parent.mkdir(parents=True,exist_ok=True)
    # debugfs parses local file arguments itself: use an internal no-space path.
    with tempfile.TemporaryDirectory(prefix='r8q-ext4-') as workspace_name:
        workspace = Path(workspace_name)
        original = Ext4(source, workspace)
        before_fsck = fsck(source)
        prepared=[]; parents={}; seen=set()
        for index,row in enumerate(operations):
            if not isinstance(row,dict):raise ValueError('Operation must be an object')
            path=checked_path(row.get('path'))
            if path=='/' or path in seen or row.get('op') not in {'replace','delete','add'}:
                raise ValueError('Duplicate path or invalid operation')
            seen.add(path)
            for parent in reversed(PurePosixPath(path).parents):
                p=str(parent)
                record=original.stat(p)
                if record['type']!='directory':raise ValueError('Non-directory/symlink image ancestor')
                parents[p]=record
            if row['op']=='add':
                if original.stat(path,missing_ok=True) is not None:raise ValueError('Added file already exists')
                template=checked_path(row.get('metadata_from'))
                for parent in PurePosixPath(template).parents:
                    if original.stat(str(parent))['type']!='directory':
                        raise ValueError('Symlink/non-directory metadata template ancestor')
                metadata=original.regular(template)
                old_sha=None
            else:
                metadata=original.regular(path)
                old_sha=hashlib.sha256(original.content(path)).hexdigest()
                if not valid_digest(row.get('old_sha256')) or old_sha!=row['old_sha256']:
                    raise ValueError('Old file SHA256 mismatch: '+path)
            blob=source_blob(plan_path.parent,row) if row['op']!='delete' else None
            local=workspace/('content-'+str(index))
            if blob is not None:local.write_bytes(blob)
            prepared.append(dict(path=path,op=row['op'],metadata=metadata,old_sha256=old_sha,
                                 sha256=hashlib.sha256(blob).hexdigest() if blob is not None else None,
                                 blob=blob,local=local))
        if shutil.disk_usage(output.parent).free < source.stat().st_blocks*512 + 64*1024**2:
            raise ValueError('Insufficient free space for independent candidate copy')
        fd,stage_name=tempfile.mkstemp(prefix='.r8q-ext4-',suffix='.img',dir=output.parent)
        os.close(fd); stage=Path(stage_name)
        try:
            shutil.copyfile(source,stage)
            candidate=Ext4(stage,workspace)
            for row in prepared:
                if row['op']!='add':
                    # debugfs rm does not free a separately allocated EA block.
                    # Remove attributes explicitly before freeing the inode.
                    for name in row['metadata']['xattrs']:
                        candidate.command('ea_rm '+row['path']+' '+name,writable=True)
                    candidate.command('rm '+row['path'],writable=True)
                if row['op']!='delete':
                    candidate.command('write '+str(row['local'])+' '+row['path'],writable=True)
                    candidate.restore(row['path'],row['metadata'])
            for path,metadata in parents.items():candidate.restore(path,metadata)
            # debugfs removal can leave a freed inode's external EA block in
            # the allocation bitmap. Preen only the private staging copy:
            # e2fsck automatically repairs safe metadata inconsistencies and
            # refuses errors requiring an interactive/forced repair. Keep its
            # complete evidence, then require a fresh read-only clean check.
            try:
                after_fsck=fsck(stage)
                staging_preen=dict(exit=None,skipped=True,reason='Read-only candidate check was already clean; no repair or optimization requested',argv=[])
            except ValueError:
                staging_preen=fsck(stage,preen=True)
                after_fsck=fsck(stage)
            for row in prepared:
                if row['op']=='delete':
                    if candidate.stat(row['path'],missing_ok=True) is not None:raise ValueError('Deletion verification failed')
                else:
                    if candidate.content(row['path'])!=row['blob']:raise ValueError('Content readback mismatch')
                    if not metadata_equal(candidate.stat(row['path']),row['metadata']):raise ValueError('File metadata preservation failed')
            for path,metadata in parents.items():
                if not metadata_equal(candidate.stat(path),metadata):raise ValueError('Parent metadata preservation failed')
            if sha_file(source)!=source_sha:raise ValueError('Original source changed during patching')
            result=dict(status='OFFLINE_EXT4_CANDIDATE_VALIDATED_NOT_BOOT_TESTED',
                        source=str(source),source_sha256=source_sha,output=str(output),
                        output_sha256=sha_file(stage),bytes=stage.stat().st_size,
                        plan_sha256=sha_file(plan_path),source_e2fsck=before_fsck,candidate_e2fsck=after_fsck,
                        staging_e2fsck_preen=staging_preen,
                        changes=[{k:row[k] for k in ('path','op','old_sha256','sha256','metadata')} for row in prepared],
                        preserved_parent_metadata=sorted(parents),boot_confirmed=False)
            # Exclusive publication: never replace an existing candidate or source.
            with stage.open('rb') as stream:os.fsync(stream.fileno())
            os.link(stage,output)
            return result
        finally:
            stage.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists() or args.report.is_symlink() or args.report.resolve() in {args.source.resolve(),args.output.resolve(),args.plan.resolve()}:
        raise ValueError('Report must be a fresh path distinct from image and plan files')
    result=patch_image(args.source,args.plan,args.output)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open('x') as stream:
        stream.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','output','output_sha256','bytes','boot_confirmed')},indent=2))


if __name__=='__main__':main()
