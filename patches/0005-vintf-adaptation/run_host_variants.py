"""Run the pinned official host tool on unchanged and additive metadata roots.

No image, service declaration, HAL requirement or vendor version is removed.
The optional AOSP FCM4 HAL-only reference is explicitly a separate diagnostic;
it is not the assembled Android10 framework/kernel compatibility contract.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
BINARY_SHA='6f7601b9409ac5db70d8b05bc98d117fe68456464e710eb2e2964c7edf1325db'
FCM_SHA='a407c2e8e947054a8a85f167d679d2af3e0c87096f415de6a153725c957aa130'
OVERLAYS={
    'system_ext/etc/vintf/manifest/r8q-vndk30.xml':'d2b35ccfbc92368a37a770a267188e014e3784bc92c4af5dbbb8e119df4f08d9',
    'system/etc/vintf/compatibility_matrix.device.xml':'0e9a5e24c3e3a06474918e692139d2bee2530f42ef913f82cf4e6742cc87a480',
}


def sha(blob):return hashlib.sha256(blob).hexdigest()


def run(binary,root,manifest,kernel,out):
    args=[str(binary),'--check-compat']
    for part in ('system','system_ext','product','vendor','odm','apex'):
        args+=['--dirmap','/'+part+':'+str(root/part)]
    for key,value in manifest['properties'].items():args+=['--property',key+'='+value]
    args+=['--kernel',manifest['kernel']['release']+':'+str(kernel)]
    result=subprocess.run(args,capture_output=True,text=True,timeout=120,
                          env=os.environ|{'LD_LIBRARY_PATH':str(binary.parent.parent/'lib64')})
    record=dict(argv=args,exit=result.returncode,stdout=result.stdout,stderr=result.stderr)
    out.write_text(json.dumps(record,indent=2)+'\n')
    return record


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--checkvintf',required=True,type=Path)
    ap.add_argument('--out',type=Path,default=HERE/'host-results')
    ap.add_argument('--include-legacy-fcm4-diagnostic',action='store_true');args=ap.parse_args()
    binary=args.checkvintf.resolve()
    if sha(binary.read_bytes())!=BINARY_SHA:raise ValueError('Host checkvintf is not the reviewed Android17/API37 binary')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location('r8q_exact_vintf_inputs',ROOT/'ci-r8q/tools/run_checkvintf.py')
    source=importlib.util.module_from_spec(spec);spec.loader.exec_module(source)
    base,manifest,bundle_sha=source.unpack_inputs(out)
    variants=['original','additive-present-components']
    if args.include_legacy_fcm4_diagnostic:variants.append('diagnostic-with-AOSP10-FCM4-HAL-reference')
    results=[]
    for variant in variants:
        root=out/variant;shutil.copytree(base/'root',root)
        additions=[]
        if variant!='original':
            for relative,expected in OVERLAYS.items():
                data=(HERE/'candidate'/relative).read_bytes()
                if sha(data)!=expected:raise ValueError('Reviewed candidate overlay identity differs: '+relative)
                target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
                additions.append(dict(path=relative,sha256=sha(data)))
        if variant.startswith('diagnostic-'):
            reference=(HERE/'reference/aosp-android10-fcm4-hal.xml').read_bytes()
            if sha(reference)!=FCM_SHA:raise ValueError('AOSP FCM4 HAL reference differs')
            relative='system/etc/vintf/compatibility_matrix.4.xml';(root/relative).write_bytes(reference)
            additions.append(dict(path=relative,sha256=FCM_SHA,scope='HAL_ONLY_REFERENCE_NOT_ASSEMBLED_KERNEL_CONTRACT'))
        result=run(binary,root,manifest,base/'kernel.config',out/(variant+'.json'))
        results.append(dict(variant=variant,exit=result['exit'],changes=additions))
        print(variant,'exit',result['exit'],flush=True)
    summary=dict(status='HOST_METADATA_VARIANT_COMPARISON_NOT_RUNTIME_VALIDATION',
                 source_input_bundle_sha256=bundle_sha,checkvintf_sha256=BINARY_SHA,
                 variants=results,boot_ready=False,rom_images_changed=False,
                 limits=['The sepolicy declaration requires coherent actual policy integration, not unchanged original P0 CIL.',
                         'Factory VNDK30 presence does not prove APEX activation or linker namespace resolution.',
                         'The optional FCM4 reference lacks assembled kernel fragments and remains diagnostic-only.',
                         'Host metadata success does not prove Android boot, SELinux policy load or hardware operation.'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    if any(row['exit'] is None or row['exit']<0 for row in results):raise SystemExit(1)


if __name__=='__main__':main()
