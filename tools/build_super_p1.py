"""Build an offline raw LP candidate using the measured R8Q geometry.

Images are copied without filesystem reconstruction. This is not a device flash.
LP binary structures follow AOSP metadata_format.h (source kept alongside tools).
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from unpack_hyperos import parse_lp

ROOT=Path(__file__).resolve().parents[1]

def align(n,a):return (n+a-1)//a*a
def cstr(name):
    value=name.encode('ascii')
    if not value or len(value)>36 or any(c not in b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for c in value):
        raise ValueError('Invalid LP name')
    return value.ljust(36,b'\0')
def digest_file(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser(description='Build an offline P1 super with measured R8Q geometry and verify every embedded image')
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() or args.report.exists():raise ValueError('Output/report must be new paths')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    plan=json.loads(args.plan.read_text())
    measurement=json.loads((ROOT/'reports/device/validated.json').read_text())
    prefix=(ROOT/'reports/device/super-first-1MiB.bin').read_bytes()
    device,old_extents=parse_lp(prefix,measurement['block_sizes']['super']['bytes'])
    capacity=device['super_bytes']
    if device['header_size']!=128 or device['metadata_minor_version']!=0:
        raise ValueError('This builder only serializes measured LP10.0')
    geometry=prefix[4096:12288]
    maxsize,slots=device['geometry_max_size'],device['metadata_slots']
    table_end=12288+maxsize*slots*2
    first_sector=device['first_logical_sector']
    if first_sector*512<table_end:raise ValueError('Metadata overlaps data')
    alignment=device['block_device_alignment']
    if device['block_device_alignment_offset']!=0 or alignment<=0:raise ValueError('Unexpected alignment')
    group=next(g for g in device['groups'] if g['name']=='qti_dynamic_partitions')
    groups=device['groups']
    group_index=groups.index(group)
    available={p['partition']:p for p in plan['partitions']}
    order=[p['name'] for p in device['partitions']]
    if set(available)!=set(order):raise ValueError('Partition set mismatch')
    old_header=prefix[12288:12416]
    old_tables=prefix[12416:]
    doff,dcount,dstride=struct.unpack_from('<III',old_header,116)
    if dcount!=1 or dstride!=64:raise ValueError('Unexpected device table')
    block_record=old_tables[doff:doff+64]
    if block_record[24:60]!=cstr('super') or struct.unpack_from('<I',block_record,60)[0]!=0:
        raise ValueError('Unexpected block-device name/flags')
    if struct.unpack_from('<Q',block_record,16)[0]!=capacity:raise ValueError('Capacity mismatch')
    partitions=[];extents=[];writes=[]
    cursor=first_sector*512
    for index,name in enumerate(order):
        source=available[name]
        path=ROOT/source['file']
        if path.stat().st_size!=source['bytes'] or digest_file(path)!=source['sha256']:
            raise ValueError('Source image identity changed: '+name)
        size=source['bytes']
        if size<=0 or size%4096:raise ValueError('Unaligned source size')
        cursor=align(cursor,alignment)
        if cursor+size>capacity:raise ValueError('Physical overflow')
        # All five target filesystems are mounted read-only by the R8Q fstab.
        partitions.append(cstr(name)+struct.pack('<4I',1,index,1,group_index))
        extents.append(struct.pack('<QIQI',size//512,0,cursor//512,0))
        writes.append(dict(name=name,file=source['file'],bytes=size,physical_offset=cursor,sha256=source['sha256']))
        cursor+=size
    logical_total=sum(x['bytes'] for x in writes)
    if logical_total>group['maximum_size']:raise ValueError('Group capacity exceeded')
    blobs=[b''.join(partitions),b''.join(extents),
           b''.join(cstr(g['name'])+struct.pack('<IQ',g['flags'],g['maximum_size']) for g in groups),block_record]
    counts=[len(partitions),len(extents),len(groups),1]
    strides=[52,24,48,64]
    tables=b''.join(blobs)
    header=bytearray(128)
    struct.pack_into('<IHHI',header,0,0x414c5030,10,0,128)
    struct.pack_into('<I',header,44,len(tables))
    header[48:80]=hashlib.sha256(tables).digest()
    offset=0
    for i,blob in enumerate(blobs):
        struct.pack_into('<III',header,80+12*i,offset,counts[i],strides[i]);offset+=len(blob)
    header[12:44]=hashlib.sha256(header).digest()
    metadata=bytes(header)+tables
    if len(metadata)>maxsize:raise ValueError('Metadata slot overflow')
    metadata=metadata.ljust(maxsize,b'\0')
    dest=args.output
    with dest.open('xb') as out:
        out.truncate(capacity)
        # Retain Samsung's reserved prefix verbatim; no signature-validity claim.
        out.seek(0);out.write(prefix[:4096]);out.write(geometry)
        for base in (12288,12288+maxsize*slots):
            for slot in range(slots):
                out.seek(base+slot*maxsize);out.write(metadata)
        for entry in writes:
            print('Embedding',entry['name'],entry['bytes'],flush=True)
            offset=entry['physical_offset']
            with (ROOT/entry['file']).open('rb') as source:
                while data:=source.read(1024*1024):
                    if data.count(0)!=len(data):out.seek(offset);out.write(data)
                    offset+=len(data)
    with dest.open('rb') as image:
        candidate_prefix=image.read(1048576)
        parsed,segments=parse_lp(candidate_prefix,capacity)
        if candidate_prefix[:12288]!=prefix[:12288]:raise ValueError('Changed reserved bytes or geometry')
        if parsed['groups']!=device['groups']:raise ValueError('Changed groups')
        for base in (12288,12288+maxsize*slots):
            for slot in range(slots):
                if candidate_prefix[base+slot*maxsize:base+(slot+1)*maxsize]!=metadata:
                    raise ValueError('Metadata copy mismatch')
        for entry in writes:
            extent=next(p for p in parsed['partitions'] if p['name']==entry['name'])
            if extent['bytes']!=entry['bytes'] or extent['attributes']!=1:raise ValueError('Partition mismatch')
            image.seek(entry['physical_offset'])
            remaining=entry['bytes'];h=hashlib.sha256()
            while remaining:
                data=image.read(min(1024*1024,remaining))
                if not data:raise ValueError('Unexpected end of image')
                h.update(data);remaining-=len(data)
            if h.hexdigest()!=entry['sha256']:raise ValueError('Embedded partition hash mismatch')
    report=dict(status='P1_SUPER_FS_CHANGES_APPLIED_NOT_BOOT_TESTED',bytes=capacity,
                sha256=digest_file(dest),logical_bytes=logical_total,group_limit=group['maximum_size'],
                layout=parsed,embedded_sources=writes,
                reserved_prefix_policy='Original Samsung first4KiB retained verbatim; no firmware signature validity inferred.',
                checks=['source image hashes','geometry/prefix preserved','all primary+backup slots identical',
                        'LP header/table hashes','physical bounds/alignment/non-overlap','group limit',
                        'every embedded partition re-read and SHA256 matched'],
                pending=['AOSP liblp independent reader','runtime mount/boot/framework/HAL tests'])
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print('Super candidate built and embedded hashes verified.',flush=True)

if __name__=='__main__':main()

