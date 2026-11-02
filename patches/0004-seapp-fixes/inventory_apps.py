"""Inspect every APK in the five original P0 partitions, read-only."""
from pathlib import Path
import hashlib,importlib.util,io,json,re,struct,subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ci-r8q/vendor_audit'))
from ext4_readonly import Ext4
spec=importlib.util.spec_from_file_location('axml_reader',ROOT/'reports/audit-20261101/round2/apex-overlays/audit_apk_resources.py')
ax=importlib.util.module_from_spec(spec);spec.loader.exec_module(ax)

def lp(data,offset=0):
    n=struct.unpack_from('<I',data,offset)[0];start=offset+4
    if start+n>len(data):raise ValueError('APK signing sequence truncated')
    return data[start:start+n],start+n

def certificates(data,archive):
    found=set();cd=archive.start_dir
    if cd>=24 and data[cd-16:cd]==b'APK Sig Block 42':
        n=struct.unpack_from('<Q',data,cd-24)[0];start=cd-(n+8)
        if start<0 or struct.unpack_from('<Q',data,start)[0]!=n:raise ValueError('APK signing block bounds')
        at=start+8
        while at<cd-24:
            size=struct.unpack_from('<Q',data,at)[0];at+=8
            if size<4 or at+size>cd-24:raise ValueError('APK signing pair bounds')
            ident=struct.unpack_from('<I',data,at)[0];blob=data[at+4:at+size];at+=size
            if ident not in (0x7109871a,0xf05368c0,0x1b93ad61):continue
            signers,_=lp(blob);pos=0
            while pos<len(signers):
                signer,pos=lp(signers,pos);signed,_=lp(signer);_,off=lp(signed)
                certs,_=lp(signed,off);off=0
                while off<len(certs):
                    cert,off=lp(certs,off);found.add(hashlib.sha256(cert).hexdigest())
    if not found:
        from cryptography.hazmat.primitives.serialization.pkcs7 import load_der_pkcs7_certificates
        from cryptography.hazmat.primitives.serialization import Encoding
        for name in archive.namelist():
            if re.fullmatch(r'META-INF/[^/]+\.(RSA|DSA|EC)',name,re.I):
                for cert in load_der_pkcs7_certificates(archive.read(name)):
                    found.add(hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest())
    return sorted(found)

def main():
    dump=ROOT/'tools/image-tools/bin/dump.erofs';rows=[];macs=[];paths=[];dirs=0
    for part in ('system','system_ext','product','vendor','odm'):
        erofs=part in ('system','system_ext','product')
        image=ROOT/'extracted'/('hyperos' if erofs else 'r8q')/(part+'.img')
        ext=None if erofs else Ext4(image)
        def run(args):
            p=subprocess.run(list(map(str,args)),capture_output=True,timeout=60)
            if p.returncode:raise ValueError(p.stderr.decode(errors='replace'))
            return p.stdout
        def read(path):return run([dump,'--cat','--path='+path,image]) if erofs else ext.read_file(path,max_bytes=512*1024**2)
        todo=['/']
        while todo:
            directory=todo.pop();dirs+=1
            if dirs>15000:raise ValueError('Unexpected filesystem directory count')
            if erofs:
                entries=[]
                for line in run([dump,'--ls','--path='+directory,image]).decode(errors='replace').splitlines():
                    m=re.match(r'^\s*\d+\s+(\d+)\s+(.+)$',line)
                    if m and m[2] not in ('.','..'):entries.append((m[2],m[1]=='2'))
            else:entries=ext.list_dir(directory)
            for name,isdir in entries:
                if '/' in name or name in ('.','..'):raise ValueError('Unsafe filesystem entry')
                path=directory.rstrip('/')+'/'+name
                if isdir:todo.append(path);continue
                if name.endswith('mac_permissions.xml'):
                    blob=read(path);macs.append(dict(partition=part,path=path,sha256=hashlib.sha256(blob).hexdigest(),xml=blob.decode()))
                if not name.lower().endswith('.apk'):continue
                row=dict(partition=part,path=path)
                try:
                    blob=read(path);row.update(bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest())
                    with zipfile.ZipFile(io.BytesIO(blob)) as z:
                        parsed=ax.axml(z.read('AndroidManifest.xml'))
                        if 'elements' not in parsed:raise ValueError('Nonbinary APK manifest needs explicit parser')
                        row['manifest']=[x for x in parsed['elements'] if x['tag'] in ('manifest','application','uses-sdk')]
                        row['certificates_sha256']=certificates(blob,z)
                        if not row['certificates_sha256']:raise ValueError('No APK signing certificates found')
                except Exception as exc:row['inspection_error']=type(exc).__name__+': '+str(exc)
                rows.append(row)
                print(part,path,'ERROR' if 'inspection_error' in row else 'OK',flush=True)
        if ext:ext.close()
    out=ROOT/'patches/0004-seapp-fixes';out.mkdir(exist_ok=True)
    result=dict(scope='All APK files recursively enumerated across actual P0 system/system_ext/product/vendor/odm images; factory APK identity and certificate metadata, not signature verification or /data inventory',directories=dirs,apks=rows,mac_permissions=macs)
    (out/'app-inventory.json').write_text(json.dumps(result,indent=2)+'\n')
    print('APKs',len(rows),'errors',sum('inspection_error'in x for x in rows),flush=True)

if __name__=='__main__':main()
