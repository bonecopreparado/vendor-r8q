"""Run the reviewed AOSP host tool on metadata read from actual P1 images."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,shutil,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
from verify_p1_policy import Filesystem

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'reports/p1/vintf-actual')
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location('vintf_inputs',ROOT/'ci-r8q/tools/run_checkvintf.py')
    source=importlib.util.module_from_spec(spec);spec.loader.exec_module(source)
    base,manifest,bundle_sha=source.unpack_inputs(out)
    pin=json.loads((ROOT/'ci-r8q/pins/official-otatools.json').read_text())
    binary=ROOT/'tools/p1-host/aosp/bin/checkvintf'
    assert hashlib.sha256(binary.read_bytes()).hexdigest()==pin['checkvintf_sha256']
    root=base/'root';records=[];images=[]
    for part in ('system','system_ext','product','vendor','odm'):
        image=ROOT/('extracted/hyperos/product.img' if part=='product' else 'candidates/p1/'+part+'.img')
        with image.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        fs=Filesystem(image);prefix='/system' if part=='system' else ''
        try:
            dest=root/part/'etc/vintf'
            if dest.exists():shutil.rmtree(dest)
            for path in fs.walk(prefix+'/etc/vintf'):
                if not path.endswith('.xml'):continue
                data=fs.read(path);relative=path[len(prefix):].lstrip('/')
                target=root/part/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
                records.append(dict(partition=part,path=path,sha256=hashlib.sha256(data).hexdigest()))
        finally:fs.close()
        images.append(dict(partition=part,path=str(image.relative_to(ROOT)),sha256=digest))
    properties=[];maps=[]
    for key,value in manifest['properties'].items():properties+=['--property',key+'='+value]
    for part in ('system','system_ext','product','vendor','odm','apex'):
        (root/part).mkdir(exist_ok=True);maps+=['--dirmap','/'+part+':'+str(root/part)]
    results=[]
    for name,kernel in [('actual-p1-no-kernel',[]),('actual-p1-with-kernel',['--kernel',manifest['kernel']['release']+':'+str(base/'kernel.config')])]:
        argv=[str(binary),'--check-compat']+maps+properties+kernel
        result=subprocess.run(argv,capture_output=True,text=True,timeout=90,
                              env=os.environ|{'LD_LIBRARY_PATH':str(binary.parent.parent/'lib64')})
        row=dict(name=name,argv=argv,exit=result.returncode,stdout=result.stdout,stderr=result.stderr)
        (out/(name+'.json')).write_text(json.dumps(row,indent=2)+'\n');results.append(row)
        if result.returncode<0:raise ValueError('Host tool crashed')
    report=dict(status='ACTUAL_P1_VINTF_HOST_CHECK_COMPLETE_NOT_BOOT_TESTED',boot_confirmed=False,
                host_compatible=all(r['exit']==0 for r in results),images=images,actual_xml_files=records,
                source_apex_kernel_bundle_sha256=bundle_sha,tool_sha256=pin['checkvintf_sha256'],
                runs=[dict(name=r['name'],exit=r['exit'])for r in results],
                limits=['Factory APEX activation model and kernel configuration from the unchanged pinned P0 boot are retained.',
                        'Full EROFS logical comparison proves factory APEX bytes did not change; actual APEX activation remains a runtime assumption.',
                        'No vendor versions, target FCM, kernel requirements or HAL declarations were removed or spoofed.'])
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(xml_files=len(records),runs=report['runs'],host_compatible=report['host_compatible']),indent=2))

if __name__=='__main__':main()
