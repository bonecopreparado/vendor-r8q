"""Run the reviewed AOSP host tool on metadata read from actual P1 images."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,shutil,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]

def classify_actual_run(row):
    exit_code = row['exit']
    tokens = set(row['stdout'].splitlines())
    if exit_code == 0 and 'COMPATIBLE' in tokens and 'INCOMPATIBLE' not in tokens:
        return 'COMPATIBLE'
    if exit_code == 65 and 'INCOMPATIBLE' in tokens and 'COMPATIBLE' not in tokens:
        return 'INCOMPATIBLE'
    known_missing_matrix = (
        'ERROR: No such file or directory: Cannot find framework matrix at FCM version 4. Looked in:'
    )
    if (exit_code == 70 and row['name'] == 'actual-p1-no-kernel'
            and known_missing_matrix in row['stderr']):
        return 'KNOWN_NO_KERNEL_FCM4_METADATA_ERROR'
    raise ValueError(f"Unexpected checkvintf result for {row['name']} (exit {exit_code}); see raw report")

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'reports/p1/vintf-actual')
    ap.add_argument('--product',type=Path,default=ROOT/'extracted/hyperos/product.img')
    ap.add_argument('--kernel-image',type=Path)
    ap.add_argument('--kernel-summary',type=Path)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    if bool(args.kernel_image)!=bool(args.kernel_summary):
        raise ValueError('Provide both actual kernel Image and trusted build summary')
    from verify_p1_policy import Filesystem
    spec=importlib.util.spec_from_file_location('vintf_inputs',ROOT/'ci-r8q/tools/run_checkvintf.py')
    source=importlib.util.module_from_spec(spec);spec.loader.exec_module(source)
    base,manifest,bundle_sha=source.unpack_inputs(out)
    pin=json.loads((ROOT/'ci-r8q/pins/official-otatools.json').read_text())
    binary=ROOT/'tools/p1-host/aosp/bin/checkvintf'
    if hashlib.sha256(binary.read_bytes()).hexdigest()!=pin['checkvintf_sha256']:
        raise ValueError('Pinned checkvintf binary differs')
    kernel_release=manifest['kernel']['release']
    kernel_config=base/'kernel.config'
    kernel_input=dict(profile='UNCHANGED_PINNED_P0_KERNEL',release=kernel_release,
                      config_sha256=hashlib.sha256(kernel_config.read_bytes()).hexdigest())
    if args.kernel_image:
        for path in (args.kernel_image,args.kernel_summary):
            if path.is_symlink() or not path.is_file():
                raise ValueError('Expected regular current kernel input')
        if args.kernel_image.stat().st_size>64*1024**2 or args.kernel_summary.stat().st_size>1024**2:
            raise ValueError('Current kernel input exceeds bound')
        sys.path.insert(0,str(ROOT/'tools/kernel_nflog/susfs22'))
        import verify_linked
        import audit_boot_kernel_input
        image=args.kernel_image.read_bytes()
        summary=json.loads(args.kernel_summary.read_text())
        evidence=verify_linked.verify(image,summary)
        _,_,text=audit_boot_kernel_input.extract_config(image)
        kernel_config=out/'actual-current-kernel.config'
        kernel_config.write_text(text)
        kernel_release=summary['kernelrelease'].split('-',1)[0]
        kernel_input=dict(profile='ACTUAL_LINKED_SUSFS22_IMAGE',release=kernel_release,
            image_sha256=evidence['kernel_sha256'],config_sha256=evidence['embedded_config_sha256'],
            source_commit=summary['source_commit'],hardware_boot_confirmed=False)
    root=base/'root';records=[];images=[]
    for part in ('system','system_ext','product','vendor','odm'):
        image=args.product.resolve() if part=='product' else ROOT/('candidates/p1/'+part+'.img')
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
    for name,kernel in [('actual-p1-no-kernel',[]),('actual-p1-with-kernel',['--kernel',kernel_release+':'+str(kernel_config)])]:
        argv=[str(binary),'--check-compat']+maps+properties+kernel
        result=subprocess.run(argv,capture_output=True,text=True,timeout=90,
                              env=os.environ|{'LD_LIBRARY_PATH':str(binary.parent.parent/'lib64')})
        row=dict(name=name,argv=argv,exit=result.returncode,stdout=result.stdout,stderr=result.stderr)
        (out/(name+'.json')).write_text(json.dumps(row,indent=2)+'\n')
        row['outcome'] = classify_actual_run(row)
        results.append(row)
    report=dict(status='ACTUAL_P1_VINTF_HOST_CHECK_COMPLETE_NOT_BOOT_TESTED',boot_confirmed=False,
                host_compatible=all(r['exit']==0 for r in results),images=images,actual_xml_files=records,
                source_apex_kernel_bundle_sha256=bundle_sha,tool_sha256=pin['checkvintf_sha256'],
                kernel_input=kernel_input,
                runs=[dict(name=r['name'],exit=r['exit'],outcome=r['outcome'])for r in results],
                limits=['Factory APEX activation model is retained; the exact checked kernel/configuration is recorded in kernel_input.',
                        'Full EROFS logical comparison proves factory APEX bytes did not change; actual APEX activation remains a runtime assumption.',
                        'No vendor versions, target FCM, kernel requirements or HAL declarations were removed or spoofed.'])
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(xml_files=len(records),runs=report['runs'],host_compatible=report['host_compatible']),indent=2))

if __name__=='__main__':main()

