"""Package the actual P1 images in one recovery ZIP, with a native ZIP64 reader.

Gzip streams are generated twice with identical settings: first to compute the
table, then directly inside ZIP_STORED members. No external payload directory
or second ROM-sized intermediate is needed. Every final member is read back.
"""
from pathlib import Path
import argparse,gzip,hashlib,io,json,os,re,struct,subprocess,sys,zipfile
from p1_single_template import template

ROOT=Path(__file__).resolve().parents[1]
CHUNK=512*1024**2
BUFFER=4*1024**2
HELPER_NAME='tools/r8q-zipread'
INSTALLER='META-INF/com/google/android/update-binary'
CAPACITIES={'super':10292822016,'boot':67108864,'dtbo':10485760}
FIXED={'boot':'4283ccbecbf3087bbd520dce1e50e5e449b1f70c4d959e8ee7f24b3ebfde9301',
       'dtbo':'3d78f213d52a5d4875b634c4ea914d04dea678bfd70dd81625d6c9f056b60468'}
SHA=lambda data:hashlib.sha256(data).hexdigest()

class Sink:
    def __init__(self,target=None):self.target=target;self.bytes=0;self.digest=hashlib.sha256()
    def write(self,data):
        self.bytes+=len(data);self.digest.update(data)
        if self.target is not None:self.target.write(data)
        return len(data)

def info(name,executable=False):
    result=zipfile.ZipInfo(name,date_time=(2026,11,2,0,0,0));result.create_system=3
    result.external_attr=(0o100755 if executable else 0o100644)<<16
    result.compress_type=zipfile.ZIP_STORED
    return result

def helper_blob(path,require_arm64):
    raw=Path(path).read_bytes()
    if len(raw)<64 or len(raw)>2*1024**2 or raw[:6]!=b'\x7fELF\x02\x01':raise ValueError('Helper must be a bounded ELF64 little-endian executable')
    if require_arm64 and struct.unpack_from('<H',raw,18)[0]!=183:raise ValueError('Recovery helper must be AArch64')
    # A statically linked helper must not request a runtime interpreter.
    phoff=struct.unpack_from('<Q',raw,32)[0];phsize,phcount=struct.unpack_from('<HH',raw,54)
    if phsize<56 or phcount>256 or phoff+phsize*phcount>len(raw):raise ValueError('Helper ELF program headers invalid')
    if require_arm64 and any(struct.unpack_from('<I',raw,phoff+i*phsize)[0]==3 for i in range(phcount)):
        raise ValueError('Recovery helper requires a runtime interpreter; compile with -static')
    return raw.ljust((len(raw)+4095)//4096*4096,b'\0')

def load_images(path,root=ROOT):
    manifest=json.loads(Path(path).read_text());rows=manifest['images']
    if {r.get('partition')for r in rows}!=set(CAPACITIES) or len(rows)!=3:raise ValueError('Exactly super, boot and dtbo are required')
    result=[]
    for part in ('super','boot','dtbo'):
        row=next(r for r in rows if r['partition']==part)
        file=Path(row['file']);file=file if file.is_absolute() else root/file
        if not file.is_file() or file.is_symlink() or type(row['bytes']) is not int or row['bytes']!=CAPACITIES[part] or file.stat().st_size!=row['bytes']:
            raise ValueError('Image capacity/type differs: '+part)
        if not isinstance(row.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',row['sha256']):raise ValueError('Invalid source hash')
        if part in FIXED and row['sha256']!=FIXED[part]:raise ValueError('Boot/dtbo changed from reviewed R8Q sources')
        result.append(dict(partition=part,file=str(file),bytes=row['bytes'],sha256=row['sha256']))
    return result

def image_chunks(images,archive=None,expected=None):
    rows=[]
    for image in images:
        part=image['partition'];whole=hashlib.sha256();total=0
        with Path(image['file']).open('rb') as stream:
            for index,offset in enumerate(range(0,image['bytes'],CHUNK)):
                length=min(CHUNK,image['bytes']-offset);remaining=length;position=0
                name=f'{part}-{index:03d}.gz';raw=hashlib.sha256();readback=hashlib.sha256()
                zipped=archive.open(info('payloads/'+name),'w',force_zip64=True) if archive is not None else None
                sink=Sink(zipped)
                try:
                    with gzip.GzipFile(filename='',mode='wb',compresslevel=1,mtime=0,fileobj=sink) as writer:
                        while remaining:
                            data=stream.read(min(BUFFER,remaining))
                            if not data:raise ValueError('Image truncated during packaging')
                            raw.update(data);whole.update(data)
                            skip=4096 if part=='super' and offset==0 else 0
                            if position+len(data)>skip:readback.update(data[max(0,skip-position):])
                            writer.write(data);remaining-=len(data);position+=len(data);total+=len(data)
                finally:
                    if zipped is not None:zipped.close()
                row=dict(part=part,name=name,bytes=length,sha256=raw.hexdigest(),
                         compressed_bytes=sink.bytes,compressed_sha256=sink.digest.hexdigest(),
                         offset=offset,readback_sha256=readback.hexdigest())
                if expected is not None and row!=expected[len(rows)]:raise ValueError('Gzip/source bytes changed between packaging passes: '+name)
                rows.append(row);print(('Packaged: 'if archive else 'Measured: ')+name,flush=True)
            if stream.read(1):raise ValueError('Image grew during packaging')
        if total!=image['bytes'] or whole.hexdigest()!=image['sha256']:raise ValueError('Source image SHA256 differs: '+part)
    return rows

INSTRUCTIONS='''HyperOS4 R8Q P1 - ONE ZIP - EXPERIMENTAL BOOT TEST

This is one complete recovery ZIP. No Windows, Python, installer creation,
external payloads directory or manual extraction is required on the phone.
Keep this ZIP compressed. It includes the ROM image data and native ZIP64 reader.

IMPORTANT: boot is not confirmed. Official host VINTF still reports legacy
kernel/FCM/HAL contract issues. This is an experimental first-boot test, not a
stable ROM or a claim that network, NFC, fingerprint or camera work.

1. Keep your confirmed backups and working restoration ROM accessible.
2. Download the full ZIP and its .sha256 file. Calculate the ZIP's SHA256 on
   the phone and compare all 64 hexadecimal characters before installation.
3. The ZIP is over 4 GiB: use phone internal storage or an exFAT-compatible
   external card. FAT32 cannot store a single file this large. Check the file
   was not truncated. No second ROM-sized extraction directory is needed.
4. Charge to at least 50%. The installer checks battery twice; at 20..49%
   it also requires active charging, and below 20% it always stops.
5. In OrangeFox Files, select HyperOS4-R8Q-P1-SINGLE-EXPERIMENTAL.zip and swipe
   to install. Use a local file on /data or external storage.
6. After successful writes, reboot to RECOVERY first and save/export recovery.log
   outside /data. The agreed first-boot test needs clean userdata. A separate
   manual OrangeFox Format Data erases internal storage, including downloaded
   ZIPs and backups stored there. Keep backups, the working restoration ROM and
   logs on external SD/USB before choosing it. The installer never formats data.
   After the agreed clean-install procedure, reboot System and record the result.
7. If installation fails, save recovery.log. If any image write started,
   restore your working ROM before booting System. Do not bypass failed guards.

Only super, dtbo and boot are written. The target's first 4 KiB of super are
preserved. No modem, bootloader, vbmeta, recovery, EFS or userdata is written.
The native reader avoids recovery unzip for multi-gigabyte ZIP64 member data;
all compressed hashes, gzip CRCs, raw hashes and partition readbacks remain.
'''

def build(output,helper,images,root=ROOT,require_arm64=True,host_helper=None,ndk_notices=()):
    output=Path(output);root=Path(root)
    if output.exists() or output.is_symlink():raise ValueError('Output must be a new file')
    output.parent.mkdir(parents=True,exist_ok=True)
    blob=helper_blob(helper,require_arm64)
    if require_arm64 and not ndk_notices:raise ValueError('Static Android helper requires corresponding NDK notices')
    license_data=(root/'LICENSE').read_bytes()
    notice_data=(root/'THIRD_PARTY_NOTICES.md').read_bytes()
    for path in ndk_notices:
        path=Path(path)
        if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=32*1024**2:
            raise ValueError('NDK notice input is missing or oversized')
        notice_data+=b'\n\n--- Android NDK notices ---\n\n'+path.read_bytes()
    rows=image_chunks(images)
    keys=('part','name','bytes','sha256','compressed_bytes','compressed_sha256','offset','readback_sha256')
    table='\n'.join(' '.join(str(r[k])for k in keys)for r in rows)
    script=template(root).replace('@@PAYLOAD_ROWS@@',table)
    script=script.replace('@@HELPER_BLOCKS@@',str(len(blob)//4096)).replace('@@HELPER_BYTES@@',str(len(blob))).replace('@@HELPER_SHA@@',SHA(blob))
    if '@@' in script:raise ValueError('Unresolved installer field')
    manifest=dict(name='HyperOS4-R8Q-P1-SINGLE-EXPERIMENTAL',status='EXPERIMENTAL_BOOT_TEST_NOT_STABLE',boot_confirmed=False,
                  known_host_vintf_status='LEGACY_KERNEL_FCM_HAL_CONTRACTS_UNRESOLVED',
                  images=[dict(partition=r['partition'],bytes=r['bytes'],sha256=r['sha256'],
                               representation='concatenated_gzip_members',
                               payload_members=['payloads/'+c['name']for c in rows if c['part']==r['partition']])for r in images],chunks=rows,
                  helper=dict(member=HELPER_NAME,bytes=len(blob),sha256=SHA(blob),data_offset=4096),
                  installer_sha256=SHA(script.encode()),external_payloads_required=False,
                  target_super_prefix_policy='Preserve the actual target first 4096 bytes; first super readback hash excludes them')
    try:
        with zipfile.ZipFile(output,'x',allowZip64=True) as archive:
            first=info(HELPER_NAME,True);padding=4096-30-len(HELPER_NAME.encode())
            first.extra=struct.pack('<HH',0xA11E,padding-4)+b'\0'*(padding-4)
            archive.writestr(first,blob)
            archive.writestr(info(INSTALLER,True),script.encode())
            archive.writestr(info('META-INF/com/google/android/updater-script'),b'# Native ZIP64-backed shell installer\n')
            archive.writestr(info('P1-MANIFEST.json'),(json.dumps(manifest,indent=2)+'\n').encode())
            archive.writestr(info('README-TESTER.txt'),INSTRUCTIONS.encode())
            archive.writestr(info('LICENSE.txt'),license_data)
            archive.writestr(info('THIRD-PARTY-NOTICES.txt'),notice_data)
            image_chunks(images,archive=archive,expected=rows)
        with output.open('rb') as f:
            header=f.read(30);data_offset=30+struct.unpack_from('<H',header,26)[0]+struct.unpack_from('<H',header,28)[0]
            if data_offset!=4096:raise ValueError('Bootstrap helper offset differs')
            f.seek(4096)
            if f.read(len(blob))!=blob:raise ValueError('Bootstrap helper bytes differ')
        with zipfile.ZipFile(output) as archive:
            expected={HELPER_NAME,INSTALLER,'META-INF/com/google/android/updater-script','P1-MANIFEST.json','README-TESTER.txt','LICENSE.txt','THIRD-PARTY-NOTICES.txt'}|{'payloads/'+r['name']for r in rows}
            if len(archive.infolist())!=len(expected) or set(archive.namelist())!=expected:raise ValueError('Final ZIP member set differs')
            if archive.read(INSTALLER)!=script.encode() or archive.getinfo(INSTALLER).external_attr>>16!=0o100755:raise ValueError('Updater content/mode differs')
            for row in rows:
                name='payloads/'+row['name'];member=archive.getinfo(name)
                if member.compress_type!=zipfile.ZIP_STORED or member.file_size!=row['compressed_bytes']:raise ValueError('Payload member format differs')
                compressed=hashlib.sha256();count=0
                with archive.open(name) as stream:
                    while data:=stream.read(BUFFER):compressed.update(data);count+=len(data)
                if count!=row['compressed_bytes'] or compressed.hexdigest()!=row['compressed_sha256']:raise ValueError('Final compressed payload hash differs')
                raw=hashlib.sha256();count=0
                with archive.open(name) as stream,gzip.GzipFile(fileobj=stream) as decompressed:
                    while data:=decompressed.read(BUFFER):
                        count+=len(data)
                        if count>row['bytes']:raise ValueError('Gzip expands beyond expected size')
                        raw.update(data)
                if count!=row['bytes'] or raw.hexdigest()!=row['sha256']:raise ValueError('Final raw payload hash differs')
                if host_helper:
                    with subprocess.Popen([str(Path(host_helper).resolve()),str(output.resolve()),name],stdout=subprocess.PIPE,stderr=subprocess.PIPE) as process:
                        digest=hashlib.sha256();n=0
                        while data:=process.stdout.read(BUFFER):digest.update(data);n+=len(data)
                        error=process.stderr.read();rc=process.wait()
                    if rc or n!=row['compressed_bytes'] or digest.hexdigest()!=row['compressed_sha256']:
                        raise ValueError('Native host ZIP64 readback failed: '+error.decode(errors='replace'))
        with output.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    except Exception:
        # Incomplete output is never given a checksum or success report.
        raise
    output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n')
    output.with_name('P1-TESTER-ENGLISH.txt').write_text(INSTRUCTIONS)
    report=dict(status='SINGLE_ZIP_PACKAGED_AND_READ_BACK_NOT_BOOT_TESTED',file=output.name,bytes=output.stat().st_size,
                sha256=digest,boot_confirmed=False,external_payloads_required=False,zip64=True,
                members=len(expected),payload_chunks=len(rows),native_host_readback=bool(host_helper),
                installer_sha256=manifest['installer_sha256'],helper_sha256=SHA(blob),images=manifest['images'],
                checks=['source image capacities/hashes','two-pass compressed identities','ZIP CRCs','gzip CRCs','raw chunk hashes','early helper offset/bytes','updater executable mode','all members read back'])
    output.with_name('P1-SINGLE-build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--helper',type=Path,required=True)
    ap.add_argument('--images-manifest',type=Path,default=ROOT/'reports/p1/ci-build/package-images.json')
    ap.add_argument('--output',type=Path,default=ROOT/'output/HyperOS4-R8Q-P1-SINGLE-EXPERIMENTAL.zip')
    ap.add_argument('--host-helper',type=Path)
    ap.add_argument('--ndk-notice',type=Path,action='append',default=[])
    args=ap.parse_args()
    report=build(args.output,args.helper,load_images(args.images_manifest),host_helper=args.host_helper,ndk_notices=args.ndk_notice)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
