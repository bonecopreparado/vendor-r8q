"""Reproduce the shipped boot from the pinned public ZIP and read its IKCONFIG."""
from pathlib import Path
import hashlib,importlib.util,json,subprocess,sys,zipfile,zlib
ROOT=Path(__file__).resolve().parents[1]
EXPECTED='4283ccbecbf3087bbd520dce1e50e5e449b1f70c4d959e8ee7f24b3ebfde9301'
SHA=lambda b:hashlib.sha256(b).hexdigest()
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def bounded_gzip(data,limit):
    d=zlib.decompressobj(31);out=d.decompress(data,limit+1)
    if len(out)>limit or not d.eof:raise ValueError('Missing end or gzip output exceeds bound')
    return out
def extract_config(kernel):
    candidates=[('raw',kernel)]
    if kernel.startswith(b'\x1f\x8b'):candidates.append(('gzip',bounded_gzip(kernel,128*1024*1024)))
    found=[]
    for encoding,blob in candidates:
        offset=0
        while True:
            start=blob.find(b'IKCFG_ST',offset)
            if start<0:break
            offset=start+8;end=blob.find(b'IKCFG_ED',offset)
            if end<0 or end-offset>2*1024*1024:continue
            try:config=bounded_gzip(blob[offset:end],2*1024*1024).decode('ascii')
            except (ValueError,zlib.error,UnicodeDecodeError):continue
            if '# Linux/arm64' in config and 'CONFIG_ARM64=y' in config:found.append((encoding,start,config))
    if len(found)!=1:raise ValueError('Expected one validated ARM64 IKCONFIG, found '+str(len(found)))
    return found[0]
def main():
    for d in ['originals','reports','reports/r8q','extracted/r8q','reports/nflog-input']:(ROOT/d).mkdir(parents=True,exist_ok=True)
    source=load('kernel_input_sources',ROOT/'tools/download_verified.py').SOURCES['r8q']
    archive=ROOT/'originals'/source['name']
    if not archive.exists():subprocess.run([sys.executable,str(ROOT/'tools/download_verified.py'),'r8q'],check=True)
    with archive.open('rb') as f:archive_sha=hashlib.file_digest(f,'sha256').hexdigest()
    if archive.stat().st_size!=source['size'] or archive_sha!=source['sha256']:raise ValueError('Pinned ZIP identity differs')
    with zipfile.ZipFile(archive) as z:
        name='Color os build/boot.img';matches=[i for i in z.infolist() if i.filename==name]
        if len(matches)!=1 or matches[0].file_size!=67108864:raise ValueError('Unexpected direct boot member')
        original=z.read(name)
    p=ROOT/'extracted/r8q/boot.img'
    with p.open('xb') as f:f.write(original)
    (ROOT/'reports/r8q/reconstruction.json').write_text(json.dumps([{'name':'boot.img','sha256':SHA(original),'bytes':len(original),'source':'Direct member of independently hash-pinned public ZIP; no vendor/odm reconstruction performed'}],indent=2)+'\n')
    subprocess.run([sys.executable,str(ROOT/'tools/build_boot_candidate.py')],check=True)
    boot=(ROOT/'candidates/p0/boot-r8q-hyperos-p0.img').read_bytes()
    if SHA(boot)!=EXPECTED:raise ValueError('Reproduced boot differs from exact shipped boot')
    module=load('known_boot_sections',ROOT/'tools/build_boot_candidate.py');parts=module.sections(boot)
    encoding,offset,config=extract_config(parts['kernel']);out=ROOT/'reports/nflog-input'
    (out/'shipped-kernel.config').write_text(config)
    options={}
    for line in config.splitlines():
        if line.startswith('CONFIG_') and '=' in line:k,v=line.split('=',1);options[k]=v
        elif line.startswith('# CONFIG_') and line.endswith(' is not set'):options[line[2:-11]]='n'
    selected={k:v for k,v in options.items() if any(s in k for s in ['NFLOG','NETFILTER_NETLINK','NFNETLINK','DEBUG_KERNEL','KERNEL_DEBUG','MODULES','LOCALVERSION','IKCONFIG','FTRACE'])}
    report={'status':'EXACT_SHIPPED_BOOT_REPRODUCED_IKCONFIG_EXTRACTED','source_zip_sha256':archive_sha,'source_boot_sha256':SHA(original),'shipped_boot_sha256':SHA(boot),'boot_bytes':len(boot),'kernel_bytes':len(parts['kernel']),'kernel_sha256':SHA(parts['kernel']),'kernel_prefix_hex':parts['kernel'][:32].hex(),'config_encoding':encoding,'config_offset':offset,'config_sha256':SHA(config.encode()),'selected_options':selected,'sections':{k:{'bytes':len(parts[k]),'sha256':SHA(parts[k])} for k in ['kernel','ramdisk','dtb','second','recovery_dtbo']}}
    (out/'input-report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
