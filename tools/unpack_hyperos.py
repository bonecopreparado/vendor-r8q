"""Verify LP metadata and stream donor logical partitions from zipped super.zst.

Offline only; supports one block device, LP linear/zero extents, raw super images.
Does not execute donor scripts, mount filesystems, or access any block device.
"""
import hashlib
import json
from pathlib import Path
import struct
import zipfile
import zstandard

ROOT = Path(__file__).resolve().parents[1]
SUPER_BYTES = 9126805504

def checked_hash(data, offset):
    expected = data[offset:offset+32]
    value = bytearray(data)
    value[offset:offset+32] = bytes(32)
    if hashlib.sha256(value).digest() != expected:
        raise ValueError('Metadata SHA-256 mismatch')

def name(data):
    value = data.split(b'\0',1)[0].decode('ascii')
    if not value or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for c in value):
        raise ValueError('Unsafe metadata name')
    return value

def parse_lp(prefix, expected_device_size=SUPER_BYTES):
    geometry = prefix[4096:4096+52]
    if struct.unpack_from('<II',geometry) != (0x616c4467,52):
        raise ValueError('Unexpected geometry')
    checked_hash(geometry,8)
    if geometry != prefix[8192:8192+52]:
        raise ValueError('Geometry backups differ')
    max_size,slots,logical_block = struct.unpack_from('<III',geometry,40)
    if not (0 < max_size <= 4*1024*1024 and 0 < slots <= 4 and logical_block == 4096):
        raise ValueError('Unexpected geometry limits')
    magic,major,minor,header_size = struct.unpack_from('<IHHI',prefix,12288)
    if magic != 0x414c5030 or major != 10 or minor not in (0,1,2) or header_size not in (128,256):
        raise ValueError('Unsupported LP header version')
    header = prefix[12288:12288+header_size]
    if len(header) != header_size:
        raise ValueError('Incomplete LP header')
    checked_hash(header,12)
    table_size = struct.unpack_from('<I',header,44)[0]
    tables = prefix[12288+header_size:12288+header_size+table_size]
    if table_size + header_size > max_size or len(tables) != table_size:
        raise ValueError('Incomplete metadata tables')
    if hashlib.sha256(tables).digest() != header[48:80]:
        raise ValueError('Table SHA-256 mismatch')

    def table(index,size):
        offset,count,stride = struct.unpack_from('<III',header,80+12*index)
        if stride != size or offset+count*stride > len(tables):
            raise ValueError('Invalid table bounds')
        return [tables[offset+i*stride:offset+(i+1)*stride] for i in range(count)]

    p_table = table(0,52)
    e_table = table(1,24)
    g_table = table(2,48)
    d_table = table(3,64)
    if len(d_table) != 1:
        raise ValueError('Multiple block devices unsupported')
    first_sector,alignment,alignment_offset,device_size = struct.unpack_from('<QIIQ',d_table[0])
    if expected_device_size is not None and device_size != expected_device_size:
        raise ValueError('Unexpected donor super size')
    groups = [dict(name=name(g[:36]), flags=struct.unpack_from('<I',g,36)[0],
                   maximum_size=struct.unpack_from('<Q',g,40)[0]) for g in g_table]
    partitions = []
    segments = []
    seen = set()
    for p in p_table:
        pname = name(p[:36])
        if pname in seen:
            raise ValueError('Duplicate partition')
        seen.add(pname)
        attributes,first,count,group = struct.unpack_from('<4I',p,36)
        if first+count > len(e_table) or group >= len(groups):
            raise ValueError('Invalid partition extent/group index')
        logical_offset = 0
        extents = []
        for e in e_table[first:first+count]:
            sectors,kind,target,source = struct.unpack('<QIQI',e)
            length = sectors*512
            if source != 0 or kind not in (0,1):
                raise ValueError('Unsupported extent')
            if kind == 0:
                if target < first_sector or target*512+length > device_size:
                    raise ValueError('Extent outside donor super data bounds')
                segments.append((target*512,target*512+length,pname,logical_offset))
            extents.append(dict(bytes=length,type=kind,target_sector=target,source=source))
            logical_offset += length
        partitions.append(dict(name=pname, bytes=logical_offset, attributes=attributes,
                               group=groups[group]['name'],extents=extents))
    segments.sort()
    if any(segments[i][0] < segments[i-1][1] for i in range(1,len(segments))):
        raise ValueError('Overlapping physical extents')
    return dict(geometry_max_size=max_size,metadata_slots=slots,super_bytes=device_size,
                metadata_major_version=major,metadata_minor_version=minor,header_size=header_size,
                block_device_alignment=alignment,block_device_alignment_offset=alignment_offset,
                first_logical_sector=first_sector,
                groups=groups, partitions=partitions,
                validation='Primary slot-0 geometry/header/tables SHA-256 verified; geometry backup matches.'), segments

def main():
    output = ROOT/'extracted/hyperos'
    output.mkdir(exist_ok=False)
    with zipfile.ZipFile(ROOT/'originals/HyperOS4-Umiii-@Jopvan1.zip') as archive:
        with archive.open('super.zst') as compressed, zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
            prefix = stream.read(1024*1024)
            report, segments = parse_lp(prefix)
            print(json.dumps(report,indent=2),flush=True)
            files = {}
            try:
                for p in report['partitions']:
                    f = (output/(p['name']+'.img')).open('xb')
                    files[p['name']] = f
                    f.truncate(p['bytes'])
                position = 0
                digest = hashlib.sha256()
                chunk = prefix
                while chunk:
                    if position+len(chunk) > SUPER_BYTES:
                        raise ValueError('Oversized decompressed super')
                    digest.update(chunk)
                    for start,end,pname,logical in segments:
                        left,right = max(start,position),min(end,position+len(chunk))
                        if left < right:
                            content = chunk[left-position:right-position]
                            if content.count(0) != len(content):
                                f = files[pname]
                                f.seek(logical+left-start)
                                f.write(content)
                    position += len(chunk)
                    chunk = stream.read(1024*1024)
                if position != SUPER_BYTES:
                    raise ValueError('Truncated super image')
                report['raw_super_sha256'] = digest.hexdigest()
            finally:
                for f in files.values():
                    f.close()
        for p in report['partitions']:
            with (output/(p['name']+'.img')).open('rb') as f:
                p['sha256'] = hashlib.file_digest(f,'sha256').hexdigest()
        data = archive.read('boot.img')
        with (output/'boot.img').open('xb') as f:
            f.write(data)
        report['boot'] = dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    (ROOT/'reports/hyperos/super.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Donor logical partitions extracted and hashed.',flush=True)

if __name__ == '__main__':
    main()
