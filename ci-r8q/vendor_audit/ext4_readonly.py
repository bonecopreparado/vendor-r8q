"""Bounded ext4 reader for offline inspection only; never writes to an image.

Supports normal block-group descriptors (including 64-bit), extents and classic
indirect blocks, sparse/unwritten ranges, directory records and symlinks.
Not an fsck: metadata/data checksums, journal replay and xattrs are not verified.
Unsupported layout/encoding features are rejected rather than guessed.
"""
from pathlib import Path
import struct
import stat as statmod

class Ext4Error(ValueError): pass

def u16(b,o): return struct.unpack_from('<H',b,o)[0]
def u32(b,o): return struct.unpack_from('<I',b,o)[0]

class Ext4:
    def __init__(self,path):
        self.path=Path(path)
        self.f=self.path.open('rb')
        try:
            self.image_bytes=self.path.stat().st_size
            sb=self._at(1024,1024)
            if u16(sb,56)!=0xef53: raise Ext4Error('Not an ext2/3/4 superblock')
            log=u32(sb,24)
            if log>6: raise Ext4Error('Unsupported block size')
            self.block_size=1024<<log
            self.incompat=u32(sb,96);self.ro_compat=u32(sb,100)
            # compression, journal device, meta_bg, inline data, encryption,
            # casefold: parsing or path semantics not implemented here.
            unsupported=self.incompat & (0x1|0x8|0x10|0x8000|0x10000|0x20000)
            if unsupported: raise Ext4Error('Unsupported ext4 incompat feature: '+hex(unsupported))
            if self.incompat & 0x4: raise Ext4Error('Journal recovery required; reader does not replay journal')
            if self.ro_compat & 0x200: raise Ext4Error('Bigalloc layout unsupported')
            known=0x2|0x40|0x80|0x100|0x200|0x400|0x1000|0x2000|0x4000
            if self.incompat & ~known: raise Ext4Error('Unknown ext4 incompat feature: '+hex(self.incompat & ~known))
            self.block_count=u32(sb,4)+(u32(sb,336)<<32 if self.incompat & 0x80 else 0)
            self.first_data=u32(sb,20);self.blocks_per_group=u32(sb,32)
            self.inodes_per_group=u32(sb,40);self.inode_count=u32(sb,0)
            self.inode_size=u16(sb,88) if u32(sb,76) else 128
            self.desc_size=u16(sb,254) if self.incompat & 0x80 else 32
            if not (self.block_count and self.blocks_per_group and self.inodes_per_group and self.inode_count): raise Ext4Error('Zero geometry')
            if self.block_count*self.block_size>self.image_bytes: raise Ext4Error('Filesystem exceeds image')
            if self.inode_size<128 or self.inode_size>self.block_size or self.inode_size%4: raise Ext4Error('Invalid inode size')
            if self.desc_size<32 or self.desc_size>self.block_size or self.desc_size%8: raise Ext4Error('Invalid descriptor size')
            if self.incompat & 0x80 and self.desc_size<64: raise Ext4Error('Short 64-bit descriptor')
            self.groups=(self.block_count-self.first_data+self.blocks_per_group-1)//self.blocks_per_group
            if (self.inode_count+self.inodes_per_group-1)//self.inodes_per_group>self.groups: raise Ext4Error('Inode geometry exceeds groups')
            self.desc_start=(self.first_data+1)*self.block_size
            if self.desc_start+self.groups*self.desc_size>self.block_count*self.block_size: raise Ext4Error('Descriptor bounds')
            self._inodes={};self._extent_cache={};self._indirect_cache={}
        except Exception:
            self.f.close();raise
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    def close(self): self.f.close()
    def _at(self,offset,length):
        if offset<0 or length<0 or offset+length>self.image_bytes: raise Ext4Error('Read outside image')
        self.f.seek(offset);data=self.f.read(length)
        if len(data)!=length: raise Ext4Error('Short image read')
        return data
    def _block(self,n):
        if n<=0 or n>=self.block_count: raise Ext4Error('Physical block out of range')
        return self._at(n*self.block_size,self.block_size)
    def _inode(self,n):
        if n in self._inodes:return self._inodes[n]
        if not 1<=n<=self.inode_count:raise Ext4Error('Invalid inode number')
        group,index=divmod(n-1,self.inodes_per_group)
        desc=self._at(self.desc_start+group*self.desc_size,self.desc_size)
        table=u32(desc,8)+(u32(desc,40)<<32 if self.incompat&0x80 else 0)
        if not 0<table<self.block_count:raise Ext4Error('Invalid inode table')
        data=self._at(table*self.block_size+index*self.inode_size,self.inode_size)
        mode=u16(data,0);size=u32(data,4)
        if statmod.S_ISREG(mode) or statmod.S_ISDIR(mode) or statmod.S_ISLNK(mode):size+=u32(data,108)<<32
        flags=u32(data,32)
        if flags & (0x4|0x800|0x10000000):raise Ext4Error('Compressed, encrypted or inline inode unsupported')
        acl=u32(data,104)+(u16(data,118)<<32 if len(data)>=120 and self.incompat&0x80 else 0)
        item=dict(inode=n,mode=mode,size=size,flags=flags,uid=u16(data,2)+(u16(data,120)<<16 if len(data)>=124 else 0),gid=u16(data,24)+(u16(data,122)<<16 if len(data)>=124 else 0),blocks=u32(data,28),file_acl=acl,raw_blocks=data[40:100])
        self._inodes[n]=item
        return item
    def _extents(self,ino):
        if ino['inode'] in self._extent_cache:return self._extent_cache[ino['inode']]
        records=[];seen=set();nodes=0
        def walk(blob,depth=None):
            nonlocal nodes
            nodes+=1
            if nodes>100000:raise Ext4Error('Extent tree too large')
            if len(blob)<12 or u16(blob,0)!=0xf30a:raise Ext4Error('Invalid extent header')
            count,maximum,d=u16(blob,2),u16(blob,4),u16(blob,6)
            if d>5 or (depth is not None and d!=depth) or count>maximum or 12+maximum*12>len(blob):raise Ext4Error('Invalid extent bounds/depth')
            prior=-1
            for pos in range(12,12+12*count,12):
                logical=u32(blob,pos)
                if logical<=prior:raise Ext4Error('Unsorted extent index')
                prior=logical
                if d:
                    block=u32(blob,pos+4)+(u16(blob,pos+8)<<32)
                    if block in seen:raise Ext4Error('Cyclic/shared extent tree')
                    seen.add(block);walk(self._block(block),d-1)
                else:
                    rawlen=u16(blob,pos+4);unwritten=rawlen>32768;length=rawlen-32768 if unwritten else rawlen
                    physical=u32(blob,pos+8)+(u16(blob,pos+6)<<32)
                    if length<=0 or physical<=0 or physical+length>self.block_count:raise Ext4Error('Invalid extent range')
                    records.append((logical,logical+length,physical,unwritten))
        walk(ino['raw_blocks'])
        records.sort()
        if any(records[i][0]<records[i-1][1] for i in range(1,len(records))):raise Ext4Error('Overlapping extents')
        self._extent_cache[ino['inode']]=records
        return records
    def _classic_block(self,ino,logical):
        b=ino['raw_blocks'];count=self.block_size//4
        if logical<12:return u32(b,logical*4)
        logical-=12
        for depth in (1,2,3):
            capacity=count**depth
            if logical<capacity:
                block=u32(b,(11+depth)*4)
                for level in range(depth,0,-1):
                    if not block:return 0
                    if block not in self._indirect_cache:self._indirect_cache[block]=self._block(block)
                    div=count**(level-1);index,logical=divmod(logical,div)
                    block=u32(self._indirect_cache[block],index*4)
                return block
            logical-=capacity
        raise Ext4Error('Classic block index overflow')
    def _read_inode(self,ino,max_bytes):
        if ino['size']>max_bytes:raise Ext4Error('File exceeds inspection limit')
        if statmod.S_ISLNK(ino['mode']) and ino['size']<=60 and not ino['flags']&0x80000 and ino['blocks']-(self.block_size//512 if ino['file_acl'] else 0)==0:return ino['raw_blocks'][:ino['size']]
        size=ino['size'];out=bytearray(size);bs=self.block_size
        if ino['flags']&0x80000:
            for start,end,physical,unwritten in self._extents(ino):
                left=start*bs;right=min(end*bs,size)
                if left>=size:break
                if not unwritten:out[left:right]=self._at(physical*bs,right-left)
        else:
            for logical in range((size+bs-1)//bs):
                physical=self._classic_block(ino,logical)
                if physical:
                    length=min(bs,size-logical*bs)
                    if physical>=self.block_count:raise Ext4Error('Classic block outside filesystem')
                    out[logical*bs:logical*bs+length]=self._at(physical*bs,length)
        return bytes(out)
    def _directory(self,ino):
        if not statmod.S_ISDIR(ino['mode']):raise NotADirectoryError('Not a directory')
        data=self._read_inode(ino,16*1024*1024);rows=[];position=0;names=set()
        while position<len(data):
            remaining=self.block_size-position%self.block_size
            if remaining<8:raise Ext4Error('Truncated directory entry')
            number=u32(data,position);length=u16(data,position+4)
            namelen=data[position+6] if self.incompat&2 else u16(data,position+6)
            if length<8 or length%4 or length>remaining or position+length>len(data) or namelen>length-8 or namelen>255:raise Ext4Error('Invalid directory entry')
            raw=data[position+8:position+8+namelen]
            if number:
                if b'/' in raw or b'\0' in raw or not raw:raise Ext4Error('Unsafe directory name')
                name=raw.decode('utf-8',errors='strict')
                if name in names:raise Ext4Error('Duplicate directory name')
                names.add(name);rows.append((name,number))
            position+=length
        return rows
    def _resolve(self,path,follow=True,depth=0):
        if depth>16:raise Ext4Error('Symlink depth limit')
        if not isinstance(path,str) or not path.startswith('/') or '\0' in path:raise Ext4Error('Use absolute filesystem path')
        parts=[p for p in path.split('/') if p and p!='.'];current=self._inode(2);resolved=[]
        for index,part in enumerate(parts):
            if part=='..':raise Ext4Error('Parent traversal unsupported')
            rows=dict(self._directory(current))
            if part not in rows:raise FileNotFoundError(path)
            current=self._inode(rows[part])
            if statmod.S_ISLNK(current['mode']) and (follow or index<len(parts)-1):
                target=self._read_inode(current,4096).decode('utf-8')
                # Normalize internal .. safely, never host-path resolution.
                combined=([] if target.startswith('/') else resolved[:])+target.split('/')+parts[index+1:]
                clean=[]
                for c in combined:
                    if c in ('','.'):continue
                    if c=='..':
                        if clean:clean.pop()
                    else:clean.append(c)
                return self._resolve('/'+'/'.join(clean),follow,depth+1)
            resolved.append(part)
        return current
    def stat(self,path,follow_symlinks=True):
        return {k:v for k,v in self._resolve(path,follow_symlinks).items() if k!='raw_blocks'}
    def read_file(self,path,max_bytes=8*1024*1024):
        ino=self._resolve(path)
        if not statmod.S_ISREG(ino['mode']):raise Ext4Error('Not a regular file: '+path)
        return self._read_inode(ino,max_bytes)
    def readlink(self,path):
        ino=self._resolve(path,follow=False)
        if not statmod.S_ISLNK(ino['mode']):raise Ext4Error('Not a symlink: '+path)
        return self._read_inode(ino,4096).decode('utf-8',errors='strict')
    def list_dir(self,path):
        """Return [(name, is_directory), ...], excluding . and .., without following symlinks."""
        return [(name,statmod.S_ISDIR(self._inode(n)['mode'])) for name,n in self._directory(self._resolve(path)) if name not in ('.','..')]
