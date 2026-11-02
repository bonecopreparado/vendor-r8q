"""Independently compare all ext4 file bytes through the pure Python reader.

This verifier does not invoke the debugfs writer or mount a filesystem. Every
regular file is hashed, including files over 64 MiB, with a 512 MiB per-file
bound. The reader does not verify xattrs/checksums; those are separate checks.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import re
import stat

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('independent_ext4_reader',ROOT/'ci-r8q/vendor_audit/ext4_readonly.py')
reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
MAX_FILE=512*1024**2
HEX=re.compile('[0-9a-f]{64}')


def sha_file(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def encoded(value):return (json.dumps(value,indent=2,sort_keys=True)+'\n').encode()


def inventory(image):
    entries={};hashes={};seen_dirs=set();inode_paths={};hashed_bytes=0
    with reader.Ext4(image) as fs:
        queue=['/']
        while queue:
            path=queue.pop()
            st=fs.stat(path,follow_symlinks=False)
            row={key:st[key] for key in ('mode','uid','gid','flags')}
            if stat.S_ISDIR(st['mode']):
                if st['inode'] in seen_dirs:raise ValueError('Directory hardlink/cycle is unsupported')
                seen_dirs.add(st['inode'])
                children=sorted(fs.list_dir(path))
                row.update(kind='directory',children=[name for name,is_dir in children])
                queue.extend((path.rstrip('/')+'/'+name) for name,is_dir in reversed(children))
            elif stat.S_ISREG(st['mode']):
                if st['size']>MAX_FILE:raise ValueError('Regular file exceeds full-verification bound: '+path)
                if st['inode'] not in hashes:
                    data=fs.read_file(path,max_bytes=MAX_FILE)
                    if len(data)!=st['size']:raise ValueError('Short independent file read: '+path)
                    hashes[st['inode']]=hashlib.sha256(data).hexdigest();hashed_bytes+=len(data)
                row.update(kind='regular',bytes=st['size'],sha256=hashes[st['inode']])
                inode_paths.setdefault(st['inode'],[]).append(path)
            elif stat.S_ISLNK(st['mode']):
                row.update(kind='symlink',target=fs.readlink(path))
                inode_paths.setdefault(st['inode'],[]).append(path)
            else:
                raise ValueError('Unsupported special filesystem entry: '+path)
            if path in entries:raise ValueError('Duplicate filesystem path')
            entries[path]=row
            if len(entries)>100000:raise ValueError('Tree entry bound exceeded')
    groups=sorted(sorted(paths) for paths in inode_paths.values() if len(paths)>1)
    return dict(entries=entries,hardlink_groups=groups,unique_regular_inodes_hashed=len(hashes),
                unique_regular_bytes_hashed=hashed_bytes,
                counts={kind:sum(row['kind']==kind for row in entries.values()) for kind in ('regular','symlink','directory')},
                regular_logical_bytes=sum(row.get('bytes',0) for row in entries.values()))


def compare(before,after,build):
    old=before['entries'];new=after['entries'];ops=build['changes']
    expected={}
    for op in ops:
        if op.get('op') not in {'replace','delete','add'} or not isinstance(op.get('path'),str) or op['path'] in expected:
            raise ValueError('Invalid or duplicate expected operation')
        expected[op['path']]=op
    added=sorted(set(new)-set(old));removed=sorted(set(old)-set(new));common=sorted(set(old)&set(new))
    expected_added=sorted(path for path,op in expected.items() if op['op']=='add')
    expected_removed=sorted(path for path,op in expected.items() if op['op']=='delete')
    failures=[]
    if added!=expected_added:failures.append('Unexpected added paths')
    if removed!=expected_removed:failures.append('Unexpected removed paths')
    metadata=[];content=[];directories=[]
    for path in common:
        a,b=old[path],new[path]
        if any(a.get(k)!=b.get(k) for k in ('kind','mode','uid','gid','flags')):metadata.append(path)
        if a['kind']=='directory' and b['kind']=='directory':
            if a['children']!=b['children']:
                directories.append(dict(path=path,added=sorted(set(b['children'])-set(a['children'])),removed=sorted(set(a['children'])-set(b['children']))))
        elif any(a.get(k)!=b.get(k) for k in ('bytes','sha256','target')):content.append(path)
    if metadata:failures.append('Mode/owner/flags/type changed')
    if before['hardlink_groups']!=after['hardlink_groups']:failures.append('Hardlink topology changed')
    for path in content:
        if path not in expected or expected[path]['op']!='replace':failures.append('Unplanned content change: '+path)
    for path,op in expected.items():
        if op['op']!='add':
            if path not in old or old[path]['kind']!='regular' or old[path]['sha256']!=op['old_sha256']:
                failures.append('Original expected file differs: '+path)
        if op['op']!='delete':
            if path not in new or new[path]['kind']!='regular' or new[path]['sha256']!=op['sha256']:
                failures.append('Candidate expected file differs: '+path)
    # Every changed directory entry must correspond to an agreed add/delete.
    for row in directories:
        for name in row['added']:
            if row['path'].rstrip('/')+'/'+name not in expected_added:failures.append('Unplanned added directory entry')
        for name in row['removed']:
            if row['path'].rstrip('/')+'/'+name not in expected_removed:failures.append('Unplanned removed directory entry')
    return dict(status='FULL_EXT4_TREE_DIFF_MATCHES_PLAN' if not failures else 'FAILED',
                failures=failures,added=added,removed=removed,content_changed=content,
                metadata_changed=metadata,directory_entries_changed=directories,
                hardlink_topology_preserved=before['hardlink_groups']==after['hardlink_groups'],
                unchanged_entries=sum(old[p]==new[p] for p in common),
                unchanged_regular_files=sum(old[p]==new[p] and old[p]['kind']=='regular' for p in common),
                matched_plan_operations=len(expected),before_counts=before['counts'],after_counts=after['counts'])


def verify(before_image,after_image,build_path,report_path):
    before_image,after_image,build_path,report_path=map(Path,(before_image,after_image,build_path,report_path))
    protected={p.resolve() for p in (before_image,after_image,build_path)}
    destinations=[report_path]+[report_path.with_name(report_path.stem+'-'+name+'-inventory.json') for name in ('before','after')]
    if any(p.resolve() in protected or p.is_symlink() for p in destinations):
        raise ValueError('Report destinations must not replace an image, build report or symlink')
    build=json.loads(build_path.read_text())
    oldsha=sha_file(before_image);newsha=sha_file(after_image)
    if oldsha!=build['source_sha256'] or newsha!=build['output_sha256']:
        raise ValueError('Images do not match the exact build report identities')
    before=inventory(before_image);after=inventory(after_image)
    report=compare(before,after,build)
    if sha_file(before_image)!=oldsha or sha_file(after_image)!=newsha:raise ValueError('An image changed during independent verification')
    report.update(source_sha256=oldsha,candidate_sha256=newsha,build_report_sha256=sha_file(build_path),
                  reader_sha256=sha_file(ROOT/'ci-r8q/vendor_audit/ext4_readonly.py'),
                  read_only=True,regular_file_limit=MAX_FILE,
                  before_unique_regular_bytes_hashed=before['unique_regular_bytes_hashed'],
                  after_unique_regular_bytes_hashed=after['unique_regular_bytes_hashed'],
                  regular_files_skipped=0,boot_confirmed=False,
                  limits=['Independent reader does not validate ext4 metadata/data checksums, journals or xattrs.',
                          'File and parent xattr/timestamp preservation and clean fsck are validated by the separate writer build report.',
                          'Full regular-file byte verification and symlink/owner/mode comparison do not prove Android boot.'])
    report_path.parent.mkdir(parents=True,exist_ok=True)
    for name,value in [('before',before),('after',after)]:
        destination=report_path.with_name(report_path.stem+'-'+name+'-inventory.json')
        data=encoded(value);destination.write_bytes(data)
        report[name+'_inventory']=dict(file=destination.name,sha256=hashlib.sha256(data).hexdigest())
    report_path.write_bytes(encoded(report))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',type=Path,required=True)
    parser.add_argument('--after',type=Path,required=True)
    parser.add_argument('--build-report',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    report=verify(args.before,args.after,args.build_report,args.report)
    print(json.dumps(report,indent=2))
    if report['failures']:raise SystemExit(1)


if __name__=='__main__':main()
