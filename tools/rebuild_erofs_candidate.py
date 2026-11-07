"""Rebuild an offline EROFS candidate from a complete metadata-preserving PAX TAR.

All original inodes are inspected, all file content is read from the source,
and a streaming TAR feeds the official mkfs tool. No host chown/mount, inode
byte patch, partial filesystem layer or device write is used. Logical readback
of every inode, xattr, symlink and file is mandatory after fsck.
"""
from pathlib import Path, PurePosixPath
import argparse, base64, hashlib, io, json, os, re, shutil, stat, struct, subprocess, tarfile, uuid

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
PREFIXES = {1:b'user.',2:b'system.posix_acl_access',3:b'system.posix_acl_default',4:b'trusted.',6:b'security.'}

def sha(data): return hashlib.sha256(data).hexdigest()
def file_sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
def run(argv):
    p=subprocess.run(list(map(str,argv)),capture_output=True,timeout=180)
    if p.returncode: raise RuntimeError('Command failed: '+str(argv[0])+'\n'+p.stderr.decode(errors='replace'))
    return p.stdout
def safe_path(name):
    if not isinstance(name,str) or not name.startswith('/') or '\n' in name or '\r' in name or '\0' in name:
        raise ValueError('Invalid filesystem path')
    p=PurePosixPath(name)
    if any(x in {'.','..'} for x in name.split('/')[1:]) or str(p)!=name: raise ValueError('Noncanonical path')
    return p
def rooted(root,name):
    p=(root/name).resolve()
    if not p.is_relative_to(root):raise ValueError('Path outside project')
    return p

class Image:
    def __init__(self,path,tools):
        self.path=Path(path);self.tools=tools
        with self.path.open('rb') as f:f.seek(1024);self.sb=f.read(128)
        if struct.unpack_from('<I',self.sb)[0]!=0xe0f5e1e2:raise ValueError('Not EROFS')
        self.block=1<<self.sb[12];self.meta,self.xattr=struct.unpack_from('<II',self.sb,40)
        self.buildtime,self.buildns=struct.unpack_from('<QI',self.sb,24)
        self.features=struct.unpack_from('<I',self.sb,80)[0]
        self.uuid=str(uuid.UUID(bytes=self.sb[48:64]));self.bytes=struct.unpack_from('<I',self.sb,36)[0]*self.block
    def read(self,path):return run([self.tools/'dump.erofs','--cat','--path='+path,self.path])
    def entry(self,path,read_xattrs=True):
        text=run([self.tools/'dump.erofs','--path='+path,self.path]).decode()
        match=re.search(r'NID: (\d+)\s+Links: (\d+)\s+Layout: (\d+)',text)
        if not match:raise ValueError('Cannot read EROFS inode')
        nid,nlink,layout=map(int,match.groups())
        with self.path.open('rb') as f:
            f.seek(self.meta*self.block+nid*32);b=f.read(64)
            fmt,icount,mode=struct.unpack_from('<HHH',b)
            if fmt&1:
                size=struct.unpack_from('<Q',b,8)[0];uid,gid=struct.unpack_from('<II',b,24)
                sec,ns=struct.unpack_from('<QI',b,32);isize=64
            else:
                size=struct.unpack_from('<I',b,8)[0];uid,gid=struct.unpack_from('<HH',b,24)
                sec,ns=self.buildtime,self.buildns;isize=32
            attrs={}
            def xentry(position):
                f.seek(position);head=f.read(4)
                if len(head)!=4:raise ValueError('Truncated xattr')
                length,index,vsize=struct.unpack('<BBH',head)
                if index not in PREFIXES:raise ValueError('Unsupported xattr prefix '+str(index)+' at '+path+' offset '+str(position))
                suffix=f.read(length);value=f.read(vsize)
                if len(value)!=vsize:raise ValueError('Truncated xattr data')
                key=PREFIXES[index]+suffix
                if key in attrs:raise ValueError('Duplicate xattr')
                attrs[key]=value
                return (4+length+vsize+3)&~3
            if icount and read_xattrs:
                start=self.meta*self.block+nid*32+isize;extent=12+(icount-1)*4
                f.seek(start);header=f.read(12);shared=header[4]
                if 12+shared*4>extent:raise ValueError('Xattr header bounds')
                indices=struct.unpack('<'+'I'*shared,f.read(shared*4)) if shared else []
                for index in indices:xentry(self.xattr*self.block+index*4)
                position=start+12+shared*4
                while position<start+extent:position+=xentry(position)
                if position!=start+extent:raise ValueError('Inline xattr bounds')
        return dict(nid=nid,layout=layout,size=size,mode=mode,uid=uid,gid=gid,
                    inode_offset=(self.meta*self.block+nid*32)%self.block,inode_isize=isize,
                    xattr_isize=(12+(icount-1)*4 if icount else 0),
                    mtime=sec,mtime_ns=ns,nlink=nlink,xattrs={k.decode():base64.b64encode(v).decode() for k,v in attrs.items()})
    def inventory(self):
        queue=['/'];rows={}
        while queue:
            path=queue.pop();entry=self.entry(path);rows[path]=entry
            if stat.S_ISDIR(entry['mode']):
                text=run([self.tools/'dump.erofs','--ls','--path='+path,self.path]).decode()
                for line in text.splitlines():
                    m=re.match(r'^\s*\d+\s+\d+\s+(.+)$',line)
                    if m and m[1] not in {'.','..'}:
                        child=path.rstrip('/')+'/'+m[1];safe_path(child);queue.append(child)
            elif stat.S_ISREG(entry['mode']) or stat.S_ISLNK(entry['mode']):entry['sha256']=sha(self.read(path))
            else:raise ValueError('Unexpected special inode: '+path)
            if len(rows)>100000:raise ValueError('Unexpected tree size')
        return rows


def legacy_symlink_issues(entries,block):
    """Model the old erofs_fill_symlink bounds check, not modern fsck alone."""
    return [dict(path=path,nid=meta['nid'],inode_offset=meta['inode_offset'],
                 inode_isize=meta['inode_isize'],xattr_isize=meta['xattr_isize'],size=meta['size'])
            for path,meta in entries.items()
            if stat.S_ISLNK(meta['mode']) and meta['layout']==2 and 0<=meta['size']<block
            and meta['inode_offset']+meta['inode_isize']+meta['xattr_isize']+meta['size']>block]

def stream_tar(image,entries,patches,process):
    hardlinks={}
    with tarfile.open(fileobj=process.stdin,mode='w|',format=tarfile.PAX_FORMAT) as archive:
        for path,meta in sorted(entries.items(),key=lambda item:(len(PurePosixPath(item[0]).parts),item[0])):
            info=tarfile.TarInfo(path.lstrip('/') or '.')
            info.uid=meta['uid'];info.gid=meta['gid'];info.mode=stat.S_IMODE(meta['mode'])
            info.mtime=meta['mtime'];info.pax_headers['mtime']=str(meta['mtime'])+'.'+str(meta['mtime_ns']).zfill(9)
            for key,value in meta['xattrs'].items():
                info.pax_headers['SCHILY.xattr.'+key]=base64.b64decode(value).decode('utf-8','surrogateescape')
            body=b''
            if stat.S_ISDIR(meta['mode']):info.type=tarfile.DIRTYPE
            elif stat.S_ISLNK(meta['mode']):
                info.type=tarfile.SYMTYPE;info.linkname=image.read(path).decode('utf-8','surrogateescape')
            elif stat.S_ISREG(meta['mode']):
                identity=meta['nid'] if path not in patches else 'patched:'+path
                if identity in hardlinks:
                    info.type=tarfile.LNKTYPE;info.linkname=hardlinks[identity]
                else:
                    info.type=tarfile.REGTYPE;hardlinks[identity]=info.name
                    body=patches[path][1] if path in patches else image.read(path)
                    info.size=len(body)
            else:raise ValueError('Unsupported inode')
            archive.addfile(info,io.BytesIO(body))

def build(root,spec,plan_dir=None,legacy_kernel_symlinks=False):
    root=Path(root).resolve();tools=root/'tools/image-tools/root/usr/bin'
    if spec.get('schema_version',1)!=1:raise ValueError('Unsupported plan schema')
    source=rooted(root,spec['source_image']);dest=rooted(root,spec['output_image'])
    expected_source=spec.get('source_image_sha256',spec.get('source_sha256'))
    if not source.is_file() or source.is_symlink() or dest.exists() or source==dest:raise ValueError('Use a new regular candidate file')
    if file_sha(source)!=expected_source:raise ValueError('Source image SHA differs')
    image=Image(source,tools);patches={};deletions=set();additions={}
    operations=spec.get('operations',spec.get('patches',[]))
    for row in operations:
        path=str(safe_path(row['path']));op=row.get('op','replace')
        if path in patches or path in deletions:raise ValueError('Duplicate patch')
        if op not in {'replace','delete','add'}:raise ValueError('Unsupported operation')
        if op!='add':
            meta=image.entry(path)
            if not stat.S_ISREG(meta['mode']) or meta['nlink']!=1:raise ValueError('Patch requires single-link regular file')
            if sha(image.read(path))!=row['old_sha256']:raise ValueError('Patch identity differs: '+path)
        if op=='delete':deletions.add(path);continue
        source_file=row.get('replacement_file',row.get('source'))
        base=root if 'replacement_file' in row else (plan_dir or root)
        replacement=(base/source_file).resolve()
        if not replacement.is_relative_to(root):raise ValueError('Replacement outside project')
        if replacement.stat().st_size>64*1024**2:raise ValueError('Replacement exceeds 64 MiB config/overlay limit')
        data=replacement.read_bytes()
        if sha(data)!=row['sha256']:raise ValueError('Patch identity differs: '+path)
        patches[path]=(row,data)
        if op=='add':
            metadata_path=str(safe_path(row['metadata_from']));meta=image.entry(metadata_path)
            if not stat.S_ISREG(meta['mode']):raise ValueError('Add metadata source must be regular')
            additions[path]=dict(meta,size=len(data),nlink=1,nid='added:'+path,sha256=sha(data))
    if not operations:raise ValueError('Empty patch set')
    print('Reading every source file and inode...',flush=True);before=image.inventory()
    expected={p:dict(v) for p,v in before.items() if p not in deletions}
    for path in additions:
        if path in before:raise ValueError('Add target already exists')
        parent=str(PurePosixPath(path).parent)
        if parent not in before or not stat.S_ISDIR(before[parent]['mode']):raise ValueError('Add target requires existing parent')
        expected[path]=additions[path]
    for path,(row,data) in patches.items():
        expected[path]['size']=len(data);expected[path]['sha256']=sha(data)
    dest.parent.mkdir(parents=True,exist_ok=True)
    work=dest.parent/(dest.name+'.work');work.mkdir(exist_ok=False)
    mkfs=(root/'tools/erofs-legacy/bin/mkfs.erofs') if legacy_kernel_symlinks else tools/'mkfs.erofs'
    if not mkfs.is_file():raise ValueError('Missing requested EROFS writer')
    command=[mkfs,'--tar=f','-b',str(image.block),'-z','lz4hc','--preserve-mtime',
             '-T',str(image.buildtime),'--mkfs-time','-U',image.uuid,dest]
    with (work/'mkfs.log').open('wb') as log:
        process=subprocess.Popen(list(map(str,command)),stdin=subprocess.PIPE,stdout=log,stderr=log)
        try:
            stream_tar(image,expected,patches,process);process.stdin.close()
            if process.wait(timeout=600):raise RuntimeError('mkfs failed; inspect '+str(work/'mkfs.log'))
        except BaseException:
            process.kill();process.wait();raise
    candidate=Image(dest,tools)
    if candidate.features & ~image.features or candidate.block!=image.block:
        raise ValueError('New filesystem incompat features: '+hex(image.features)+' -> '+hex(candidate.features))
    run([tools/'fsck.erofs','--extract',dest])
    print('Comparing every target file and inode...',flush=True);after=candidate.inventory()
    issues=legacy_symlink_issues(after,candidate.block)
    if legacy_kernel_symlinks and (issues or any(stat.S_ISLNK(v['mode']) and v['layout']!=0 for v in after.values())):
        raise ValueError('Legacy kernel symlink layout guard failed: '+json.dumps(issues))
    if set(expected)!=set(after):raise ValueError('Unexpected filesystem path changes')
    changes=[]
    for path,old in expected.items():
        new=after[path]
        for key in ('mode','uid','gid','mtime','mtime_ns','nlink','xattrs'):
            if old[key]!=new[key]:raise ValueError('Changed inode metadata: '+path+' '+key)
        if new.get('sha256')!=old.get('sha256'):raise ValueError('Changed unexpected file bytes: '+path)
        if path in patches:changes.append(dict(path=path,old_sha256=before.get(path,{}).get('sha256'),sha256=new['sha256']))
    # Original hardlink relationships must survive even though rebuilt NIDs move.
    aliases={}
    for path,meta in expected.items():
        if stat.S_ISREG(meta['mode']) and path not in patches:
            previous=aliases.setdefault(meta['nid'],after[path]['nid'])
            if after[path]['nid']!=previous:raise ValueError('Hardlink relationship changed')
    if file_sha(source)!=expected_source:raise ValueError('Original source image changed')
    report=dict(status='OFFLINE_IMAGE_PATCHED_AND_LOGICALLY_VERIFIED_NOT_BOOT_TESTED',source_sha256=expected_source,
                image_sha256=file_sha(dest),bytes=dest.stat().st_size,entries_verified=len(expected),changes=changes,
                deleted=sorted(deletions),source_incompat_features=image.features,candidate_incompat_features=candidate.features,
                no_new_incompat_features=True,metadata_preserved=True,original_unchanged=True,
                mkfs_sha256=file_sha(mkfs),legacy_kernel_symlinks=legacy_kernel_symlinks,
                legacy_symlink_issues=issues,symlink_count=sum(stat.S_ISLNK(v['mode']) for v in after.values()),dump_sha256=file_sha(tools/'dump.erofs'),
                fsck_sha256=file_sha(tools/'fsck.erofs'),
                limitation='Full PAX rebuild and logical readback do not replace kernel mount/boot tests.')
    (work/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--source',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--report',type=Path)
    parser.add_argument('--project-root',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--legacy-kernel-symlinks',action='store_true')
    args=parser.parse_args();spec=json.loads(args.plan.read_text())
    if args.source:spec['source_image']=str(args.source.resolve())
    if args.output:spec['output_image']=str(args.output.resolve())
    if args.report:
        report_path=args.report.resolve()
        protected={args.plan.resolve(),rooted(args.project_root.resolve(),spec['source_image']),rooted(args.project_root.resolve(),spec['output_image'])}
        if report_path in protected or report_path.exists():raise ValueError('Use a new report path distinct from all image/plan inputs')
    result=build(args.project_root,spec,args.plan.resolve().parent,args.legacy_kernel_symlinks)
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
