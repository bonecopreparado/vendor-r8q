"""Export exact immutable P0 VINTF metadata and factory APEX fragments, read-only.

The resulting host root models all factory APEX modules as active. This is an
explicit host-check assumption, not proof of APEX activation or phone boot.
"""
from pathlib import Path
import gzip
import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'reports/audit-20261101/checkvintf'
HOST = OUT/'inputs/root'
TOOLS = ROOT/'tools/image-tools/bin'
PARTS = json.loads((ROOT/'reports/composition-proposed.json').read_text())['partitions']
records = []
apex_records = []


def sha(data): return hashlib.sha256(data).hexdigest()


def command(args):
    return subprocess.run(list(map(str,args)),capture_output=True,timeout=60)


def is_erofs(image):
    with image.open('rb') as f:
        f.seek(1024)
        return f.read(4)==bytes.fromhex('e2e1f5e0')


def listing(image, path, erofs):
    args=[TOOLS/'dump.erofs','--ls','--path='+path,image] if erofs else [TOOLS/'debugfs','-R','ls -p '+path,image]
    r=command(args)
    rows=[]
    for line in r.stdout.decode(errors='replace').splitlines():
        if erofs:
            m=re.match(r'^\s*\d+\s+(\d+)\s+(.+)$',line)
            if m: rows.append((m[2],m[1]=='2'))
        else:
            f=line.split('/')
            if len(f)>=7: rows.append((f[5],int(f[2],8)&0o170000==0o040000))
    return [(n,d) for n,d in rows if n not in ('.','..') and re.fullmatch(r'[A-Za-z0-9_@.+-]+',n)]


def read(image,path,erofs,limit=512*1024**2):
    args=[TOOLS/'dump.erofs','--cat','--path='+path,image] if erofs else [TOOLS/'debugfs','-R','cat '+path,image]
    r=command(args)
    if r.returncode or not r.stdout:return None
    if len(r.stdout)>limit:raise ValueError('Unexpected large file: '+path)
    return r.stdout


def save(relative,data,source):
    path=HOST/relative
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()!=data: raise ValueError('Conflicting host file: '+str(path))
    path.write_bytes(data)
    records.append(dict(host=relative,bytes=len(data),sha256=sha(data),source=source))


def export_vintf(image,base,dest,erofs,source):
    queue=[base];seen=set();count=0
    while queue:
        parent=queue.pop(0)
        if parent in seen:raise ValueError('Recursive VINTF path')
        seen.add(parent)
        if len(seen)>100:raise ValueError('VINTF directory limit')
        for name,directory in listing(image,parent,erofs):
            internal=parent+'/'+name
            if directory:queue.append(internal);continue
            if not name.endswith('.xml'):continue
            data=read(image,internal,erofs,4*1024**2)
            if data is None:raise ValueError('Unable to read '+internal)
            ET.fromstring(data)
            save(dest+internal[len(base):],data,dict(source,internal=internal));count+=1
    return count


def protobuf(blob):
    def varint(pos):
        n=0;shift=0
        while pos<len(blob) and shift<70:
            b=blob[pos];pos+=1;n|=(b&127)<<shift
            if not b&128:return n,pos
            shift+=7
        raise ValueError('Invalid protobuf')
    fields={};p=0
    while p<len(blob):
        tag,p=varint(p);wire=tag&7
        if wire==0:v,p=varint(p)
        elif wire==2:
            n,p=varint(p);v=blob[p:p+n];p+=n
            if len(v)!=n:raise ValueError('Truncated protobuf')
        elif wire in (1,5):n=8 if wire==1 else 4;v=blob[p:p+n];p+=n
        else:raise ValueError('Unsupported protobuf')
        fields.setdefault(tag>>3,[]).append(v)
    return fields


def collect_apex(image,part,base,erofs):
    for name,directory in listing(image,base,erofs):
        if directory:
            # Flattened factory modules use the directory name as their mount name.
            count=export_vintf(image,base+'/'+name+'/etc/vintf','apex/'+name+'/etc/vintf',erofs,
                               dict(partition=part,kind='flattened_factory_apex'))
            apex_records.append(dict(partition=part,path=base+'/'+name,module=name,flattened=True,vintf_files=count))
            continue
        if not name.endswith(('.apex','.capex')):continue
        internal=base+'/'+name
        blob=read(image,internal,erofs)
        if blob is None:raise ValueError('Unable to read APEX '+internal)
        row=dict(partition=part,path=internal,container_sha256=sha(blob),container_bytes=len(blob))
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            if 'original_apex' in archive.namelist():
                if archive.getinfo('original_apex').file_size>512*1024**2:raise ValueError('Oversized CAPEX')
                blob=archive.read('original_apex')
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            manifest=protobuf(archive.read('apex_manifest.pb'))
            module=manifest[1][0].decode();version=manifest[2][0]
            if not re.fullmatch(r'[A-Za-z0-9_.+-]+',module):raise ValueError('Unsafe APEX name')
            if archive.getinfo('apex_payload.img').file_size>512*1024**2:raise ValueError('Oversized APEX payload')
            with tempfile.TemporaryDirectory(prefix='vintf-apex-') as td:
                payload=Path(td)/'payload.img'
                with archive.open('apex_payload.img') as src,payload.open('wb') as dst:shutil.copyfileobj(src,dst,1024*1024)
                row.update(module=module,version=version,payload_sha256=hashlib.file_digest(payload.open('rb'),'sha256').hexdigest())
                row['vintf_files']=export_vintf(payload,'/etc/vintf','apex/'+module+'/etc/vintf',is_erofs(payload),
                                               dict(partition=part,apex=internal,module=module))
        apex_records.append(row)
        print(part,name,'APEX VINTF files:',row['vintf_files'],flush=True)


def main():
    if HOST.exists():raise ValueError('Use a clean checkvintf input export directory')
    HOST.mkdir(parents=True)
    for part in PARTS:
        image=ROOT/part['file'];name=part['partition'];erofs=part['filesystem']=='erofs'
        with image.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual!=part['sha256'] or image.stat().st_size!=part['bytes']:raise ValueError('P0 source identity changed: '+name)
        prefix='/system' if name=='system' else ''
        export_vintf(image,prefix+'/etc/vintf',name+'/etc/vintf',erofs,dict(partition=name,image_sha256=actual))
        for internal in [prefix+'/build.prop',prefix+'/etc/build.prop',prefix+'/default.prop',prefix+'/etc/manifest.xml',prefix+'/etc/compatibility_matrix.xml']:
            data=read(image,internal,erofs,4*1024**2)
            if data is not None:
                save(name+internal[len(prefix):],data,dict(partition=name,internal=internal,image_sha256=actual))
        collect_apex(image,name,prefix+'/apex',erofs)
    info=ET.Element('apex-info-list');modules={}
    for row in apex_records:
        module=row['module']
        if module in modules:raise ValueError('Duplicate factory APEX module requires explicit selection: '+module)
        modules[module]=row
        path='/'+row['partition']+row['path'].removeprefix('/system') if row['partition']=='system' else '/'+row['partition']+row['path']
        ET.SubElement(info,'apex-info',dict(moduleName=module,modulePath=path,preinstalledModulePath=path,
                      versionCode=str(row.get('version',0)),versionName='',isFactory='true',isActive='true',
                      lastUpdateMillis='0',provideSharedApexLibs='false',partition=row['partition'].upper()))
    save('apex/apex-info-list.xml',ET.tostring(info,encoding='utf-8',xml_declaration=True),dict(kind='HOST_MODEL_ALL_FACTORY_APEX_ACTIVE_NOT_PHONE_OBSERVATION'))
    kernel=(ROOT/'candidates/p0/aosp-unpacked/kernel').read_bytes()
    match=re.search(rb'Linux version ([^\x00\s]+)',kernel)
    start=kernel.index(b'IKCFG_ST')+8;end=kernel.index(b'IKCFG_ED',start)
    config=gzip.decompress(kernel[start:end])
    if config!=(ROOT/'reports/r8q/kernel.config').read_bytes():raise ValueError('Candidate kernel config differs from report')
    (OUT/'inputs/kernel.config').write_bytes(config)
    properties={'ro.product.first_api_level':'29','ro.boot.product.hardware.sku':'','ro.boot.product.vendor.sku':''}
    manifest=dict(status='EXACT_METADATA_EXPORT_HOST_FACTORY_APEX_MODEL_NOT_BOOT_TEST',images=PARTS,files=records,apex=apex_records,
                  kernel=dict(release=match[1].decode(),sha256=sha(kernel),config_sha256=sha(config)),properties=properties,
                  properties_provenance={'ro.product.first_api_level':'actual vendor build.prop','ro.boot.product.hardware.sku':'original r8q read-only inventory returned empty','ro.boot.product.vendor.sku':'not collected; empty host assumption, inspect absence of SKU alternatives'},
                  limitations=['All preinstalled APEX modeled active; actual activation/signatures/rollback/data updates not executed',
                               'No on-device OEM libvintf execution or phone boot', 'Vendor SKU not collected; host empty assumption'])
    (OUT/'inputs/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    target=ROOT/'ci-r8q/inputs/checkvintf-inputs.tar.gz'
    with target.open('wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as packed,tarfile.open(fileobj=packed,mode='w|') as archive:
        for source in sorted((OUT/'inputs').rglob('*')):
            if not source.is_file():continue
            data=source.read_bytes();entry=tarfile.TarInfo('checkvintf-inputs/'+source.relative_to(OUT/'inputs').as_posix())
            entry.size=len(data);entry.mode=0o644;archive.addfile(entry,io.BytesIO(data))
    print(json.dumps(dict(file=str(target),bytes=target.stat().st_size,sha256=sha(target.read_bytes()),vintf_files=len(records),apex_modules=len(apex_records)),indent=2))


if __name__=='__main__':main()
