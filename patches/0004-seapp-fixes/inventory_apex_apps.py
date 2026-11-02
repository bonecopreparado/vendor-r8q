"""Complete APK package/certificate coverage inside all 46 factory APEX modules."""
from pathlib import Path
import hashlib,importlib.util,io,json,shutil,tempfile,zipfile
ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
fs=module('vintf_export',ROOT/'tools/prepare_checkvintf_inputs.py')
apps=module('apps_inventory',Path(__file__).with_name('inventory_apps.py'))

def main():
    source=json.loads((ROOT/'reports/audit-20261101/checkvintf/inputs/manifest.json').read_text())
    rows=[];modules=[]
    for item in source['apex']:
        part=item['partition'];image=ROOT/'extracted'/('hyperos' if part in ('system','system_ext','product')else'r8q')/(part+'.img')
        blob=fs.read(image,item['path'],fs.is_erofs(image))
        if hashlib.sha256(blob).hexdigest()!=item['container_sha256']:raise ValueError('APEX container identity mismatch')
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            if 'original_apex'in z.namelist():blob=z.read('original_apex')
        with tempfile.TemporaryDirectory(prefix='seapp-apex-') as td,zipfile.ZipFile(io.BytesIO(blob)) as z:
            payload=Path(td)/'payload.img'
            with z.open('apex_payload.img') as src,payload.open('wb') as dst:shutil.copyfileobj(src,dst,1024**2)
            if hashlib.file_digest(payload.open('rb'),'sha256').hexdigest()!=item['payload_sha256']:raise ValueError('APEX payload identity mismatch')
            erofs=fs.is_erofs(payload);todo=['/'];paths=[]
            while todo:
                directory=todo.pop()
                for name,isdir in fs.listing(payload,directory,erofs):
                    path=directory.rstrip('/')+'/'+name
                    if isdir:todo.append(path);continue
                    if not name.endswith('.apk'):continue
                    data=fs.read(payload,path,erofs);paths.append(path)
                    with zipfile.ZipFile(io.BytesIO(data)) as apk:
                        parsed=apps.ax.axml(apk.read('AndroidManifest.xml'))
                        if 'elements'not in parsed:raise ValueError('Unexpected APK XML')
                        certs=apps.certificates(data,apk)
                        if not certs:raise ValueError('APEX APK signing certificate unavailable')
                        rows.append(dict(partition=part,apex=item['module'],path=path,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),manifest=[e for e in parsed['elements']if e['tag']in('manifest','application','uses-sdk')],certificates_sha256=certs))
            modules.append(dict(module=item['module'],container_sha256=item['container_sha256'],payload_sha256=item['payload_sha256'],apk_paths=paths))
            print(item['module'],len(paths),'APKs',flush=True)
    dest=Path(__file__).with_name('apex-app-inventory.json')
    dest.write_text(json.dumps(dict(scope='All 46 recorded factory APEX payloads read and SHA-verified; no /data modules or runtime activation claim',modules=modules,apks=rows),indent=2)+'\n')
    print('APEX modules',len(modules),'APKs',len(rows),flush=True)
if __name__=='__main__':main()
