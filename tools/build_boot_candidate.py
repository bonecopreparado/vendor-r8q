"""Repack only fstab.qcom in the known R8Q v2/newc boot. Offline candidate."""
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]

def align(n, page=4):
    return (n+page-1)//page*page

def parse_cpio(blob):
    rows=[]
    offset=0
    while offset<len(blob):
        if blob[offset:offset+6]!=b'070701':
            raise ValueError('Expected uncompressed newc archive')
        header=blob[offset:offset+110]
        fields=[int(header[6+i*8:14+i*8],16) for i in range(13)]
        namesize,size=fields[11],fields[6]
        start=align(offset+110+namesize)
        if namesize<1 or start+size>len(blob):
            raise ValueError('Invalid newc bounds')
        rawname=blob[offset+110:offset+110+namesize]
        if rawname[-1:]!=b'\0': raise ValueError('Invalid newc name')
        rows.append(dict(header=header,name=rawname[:-1],rawname=rawname,data=blob[start:start+size],
                         record=blob[offset:align(start+size)]))
        offset=align(start+size)
        if rows[-1]['name']==b'TRAILER!!!':
            if any(blob[offset:]): raise ValueError('Unexpected newc trailer data')
            return rows,blob[offset:]
    raise ValueError('Missing newc trailer')

def sections(blob):
    if blob[:8]!=b'ANDROID!': raise ValueError('Not Android boot')
    fields=struct.unpack_from('<10I',blob,8)
    ks,_,rs,_,ss,_,_,page,version,_=fields
    if version!=2 or page!=4096 or struct.unpack_from('<I',blob,1644)[0]!=1660:
        raise ValueError('Unexpected source header')
    recovery_size=struct.unpack_from('<I',blob,1632)[0]
    if recovery_size: raise ValueError('Recovery DTBO not supported in this candidate')
    dtb_size=struct.unpack_from('<I',blob,1648)[0]
    result={}
    offset=page
    for name,size in [('kernel',ks),('ramdisk',rs),('second',ss),('recovery_dtbo',recovery_size),('dtb',dtb_size)]:
        if offset+size>len(blob): raise ValueError('Boot section out of bounds')
        result[name]=blob[offset:offset+size]
        offset+=align(size,page)
    result['tail']=blob[offset:]
    result['page']=page
    return result

def boot_id(parts):
    h=hashlib.sha1()
    for key in ('kernel','ramdisk','second','recovery_dtbo','dtb'):
        data=parts[key]
        h.update(data);h.update(struct.pack('<I',len(data)))
    return h.digest()+bytes(12)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main():
    source=ROOT/'extracted/r8q/boot.img'
    original=source.read_bytes()
    known=json.loads((ROOT/'reports/r8q/reconstruction.json').read_text())
    expected=next(p['sha256'] for p in known if p['name']=='boot.img')
    if sha(original)!=expected: raise ValueError('Source boot hash changed')
    limits=json.loads((ROOT/'reports/device/validated.json').read_text())['block_sizes']
    if len(original)!=limits['boot']['bytes']: raise ValueError('Unexpected partition capacity')
    parts=sections(original)
    if original[576:608]!=boot_id(parts): raise ValueError('Source boot ID invalid')
    rows,tail=parse_cpio(parts['ramdisk'])
    matches=[r for r in rows if r['name']==b'fstab.qcom']
    if len(matches)!=1: raise ValueError('Expected one fstab')
    new_fstab=(ROOT/'patches/0001-first-stage-mounts/fstab.qcom.proposed').read_bytes()
    patch_state=json.loads((ROOT/'patches/0001-first-stage-mounts/status.json').read_text())
    if sha(matches[0]['data'])!=patch_state['base_sha256'] or sha(new_fstab)!=patch_state['candidate_sha256']:
        raise ValueError('fstab patch lineage mismatch')
    rebuilt=bytearray()
    for row in rows:
        if row['name']!=b'fstab.qcom':
            rebuilt.extend(row['record']);continue
        header=bytearray(row['header'])
        header[54:62]=f'{len(new_fstab):08x}'.encode('ascii')
        rebuilt.extend(header);rebuilt.extend(row['rawname'])
        rebuilt.extend(bytes(align(len(rebuilt))-len(rebuilt)))
        rebuilt.extend(new_fstab)
        rebuilt.extend(bytes(align(len(rebuilt))-len(rebuilt)))
    rebuilt.extend(tail)
    parts['ramdisk']=bytes(rebuilt)
    header=bytearray(original[:parts['page']])
    struct.pack_into('<I',header,16,len(rebuilt))
    header[576:608]=boot_id(parts)
    candidate=bytearray(header)
    for key in ('kernel','ramdisk','second','recovery_dtbo','dtb'):
        candidate.extend(parts[key])
        candidate.extend(bytes(align(len(candidate),parts['page'])-len(candidate)))
    # Samsung source has only its 16-byte marker and zero capacity padding here.
    if not parts['tail'].startswith(b'SEANDROIDENFORCE\0') or any(parts['tail'][16:]):
        raise ValueError('Unexpected source trailer/signature; refuse generic repack')
    candidate.extend(b'SEANDROIDENFORCE\0')
    if len(candidate)>len(original): raise ValueError('Boot candidate exceeds target capacity')
    candidate.extend(bytes(len(original)-len(candidate)))
    check=sections(candidate)
    for key in ('kernel','second','recovery_dtbo','dtb'):
        if check[key]!=parts[key]: raise ValueError('Changed preserved section '+key)
    new_rows,_=parse_cpio(check['ramdisk'])
    if [r['name'] for r in new_rows]!=[r['name'] for r in rows]: raise ValueError('Changed cpio member order')
    for before,after in zip(rows,new_rows):
        if before['name']!=b'fstab.qcom' and before['record']!=after['record']:
            raise ValueError('Changed unrelated cpio member')
        if before['name']==b'fstab.qcom' and after['data']!=new_fstab:
            raise ValueError('fstab replacement mismatch')
    if candidate[576:608]!=boot_id(check): raise ValueError('Rebuilt boot ID mismatch')
    changed=[i for i,(a,b) in enumerate(zip(original[:4096],candidate[:4096])) if a!=b]
    if any(i not in range(16,20) and i not in range(576,608) for i in changed):
        raise ValueError('Unexpected header changes')
    out=ROOT/'candidates/p0'
    out.mkdir(parents=True,exist_ok=True)
    dest=out/'boot-r8q-hyperos-p0.img'
    with dest.open('xb') as f:f.write(candidate)
    report=dict(status='OFFLINE_CANDIDATE_NOT_BOOT_TESTED',source_sha256=sha(original),
                candidate_sha256=sha(candidate),bytes=len(candidate),kernel_sha256=sha(check['kernel']),
                dtb_sha256=sha(check['dtb']),cpio_entries=len(new_rows),
                changed_cpio_members=['fstab.qcom'],changed_header_byte_offsets=changed,
                preserved=['kernel','dtb','cmdline','non-fstab cpio members with uid/gid/mode','Samsung trailer'],
                validation=['source SHA256','source and candidate boot IDs','section bounds','capacity',
                            'reparsed CPIO records, preserved bytes and fstab patch lineage'],
                pending=['AVB context','target LP layout','vendor fstab consistency','init/framework/HAL compatibility','actual boot logs'])
    (ROOT/'reports/boot-candidate-p0.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
