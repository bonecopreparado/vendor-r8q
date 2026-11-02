"""Prepare hash-pinned filesystem changes for P1; do not alter source images."""
from pathlib import Path
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'patches/0007-policy-integration'
SHA=lambda b:hashlib.sha256(b).hexdigest()


def read(part,path):
    erofs=part in {'system','system_ext','product'}
    image=ROOT/'extracted'/('hyperos' if erofs else 'r8q')/(part+'.img')
    tool=ROOT/'tools/image-tools/bin'/('dump.erofs' if erofs else 'debugfs')
    if not tool.is_file():
        fallback=shutil.which('dump.erofs' if erofs else 'debugfs')
        if not fallback:raise ValueError('Required filesystem reader is unavailable before P1 planning')
        tool=Path(fallback)
    args=[str(tool),'--cat','--path='+path,str(image)] if erofs else [str(tool),'-R','cat '+path,str(image)]
    p=subprocess.run(args,capture_output=True,check=True,timeout=30)
    if not p.stdout:raise ValueError('Missing original file: '+part+path)
    return p.stdout


def main():
    subprocess.run([sys.executable,str(ROOT/'tools/materialize_policy_bundle.py')],check=True)
    OUT.mkdir(parents=True,exist_ok=True)
    composition=json.loads((ROOT/'reports/composition-proposed.json').read_text())
    plans={p['partition']:dict(schema_version=1,source_image_sha256=p['sha256'],operations=[])
           for p in composition['partitions'] if p['partition']!='product'}
    descriptions=[]
    def change(part,path,new,reason,metadata_from=None):
        old=None if metadata_from else read(part,path)
        row=dict(op='add' if metadata_from else 'delete' if new is None else 'replace',path=path)
        if old is not None:row['old_sha256']=SHA(old)
        if new is not None:
            relative='candidate/'+part+path
            target=OUT/relative;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(new)
            row.update(source=relative,sha256=SHA(new))
        if metadata_from:row['metadata_from']=metadata_from
        plans[part]['operations'].append(row)
        descriptions.append(dict(partition=part,path=path,reason=reason,operation=row['op']))
        if old is not None and new is not None:
            delta=''.join(difflib.unified_diff(old.decode().splitlines(True),new.decode().splitlines(True),
                                            fromfile='original/'+part+path,tofile='candidate/'+part+path))
            (OUT/(part+'-'+path.replace('/','_')+'.diff')).write_text(delta)
    bundle=ROOT/'reports/audit-20261031/overnight/selinux/policy-bundle'
    manifest=json.loads((bundle/'manifest.json').read_text())
    for name,path in [('system_ext_system_ext_sepolicy.cil','/etc/selinux/system_ext_sepolicy.cil'),
                      ('system_ext_mapping_30.0.cil','/etc/selinux/mapping/30.0.cil')]:
        old=read('system_ext',path)
        assert SHA(old)==manifest['files']['original/'+name]
        new=(bundle/'candidate'/name).read_bytes()
        assert SHA(new)==manifest['files']['candidate/'+name]
        change('system_ext',path,new,'Resolve duplicate donor types through existing Samsung aliases and declare an already-used mapping attribute; no allow/capability deletion')
    for part in ('system_ext','vendor'):
        new=(ROOT/'patches/0004-seapp-fixes/candidate'/part/'etc/selinux'/(part+'_seapp_contexts')).read_bytes()
        change(part,'/etc/selinux/'+part+'_seapp_contexts',new,'Apply APK/certificate-inventory-guarded seapp cleanup and retain coherent Qualcomm domains')
    hardware=ROOT/'patches/0006-hardware-adaptation/candidate'
    for row in json.loads((hardware/'manifest.json').read_text())['files']:
        part,path=row['path'].split('/',1);path='/'+path
        assert SHA(read(part,path))==row['old_sha256']
        new=(hardware/row['path']).read_bytes() if row['action']=='replace' else None
        if new is not None:assert SHA(new)==row['new_sha256']
        change(part,path,new,'Consolidate the Samsung NFC service with its existing HIDL interface bindings')
    # This obsolete Samsung diagnostic writes directly to a logdump partition.
    # It is disabled, has no valid domain, and its sole trigger is removed too.
    path='/etc/init/hw/init.qcom.rc';old=read('vendor',path).decode()
    block='''# Logcat dump daemon, dumps logs to logdump partition
service logdumpd /system/bin/logcat -b all -v threadtime -D -w /dev/block/bootdevice/by-name/logdump
    class core
    writepid /dev/cpuset/system-background/tasks
    seclabel u:r:logdumpd:s0
    disabled

# Logdumpd is enabled only for userdebug non-perf build
on property:ro.logdumpd.enabled=1
    start logdumpd
'''
    if old.count(block)!=1 or len(re.findall(r'\blogdumpd\b',old))!=4:
        raise ValueError('Obsolete logdump service shape/references changed')
    new=old.replace(block,'# Unsupported Samsung block-partition debug logger omitted in this port.\n')
    if re.search(r'\blogdumpd\b',new):raise ValueError('Dangling logdump service reference')
    change('vendor',path,new.encode(),'Remove unsupported disabled block-partition debug logger and its only trigger; ordinary logcat remains available')
    # The ColorOS precompiled policy does not match this framework. Keep the
    # genuine framework hash files; remove only the obsolete ODM cache so init
    # compiles the corrected CIL rather than trusting incompatible old bytes.
    for name in ('precompiled_sepolicy','precompiled_sepolicy.plat_sepolicy_and_mapping.sha256',
                 'precompiled_sepolicy.system_ext_sepolicy_and_mapping.sha256',
                 'precompiled_sepolicy.product_sepolicy_and_mapping.sha256'):
        change('odm','/etc/selinux/'+name,None,'Remove stale ColorOS compiled-policy cache and its companions; normal init CIL compilation is required')
    vintf=ROOT/'patches/0005-vintf-adaptation/candidate'
    change('system','/system/etc/vintf/compatibility_matrix.device.xml',
           (vintf/'system/etc/vintf/compatibility_matrix.device.xml').read_bytes(),
           'Advertise real 30.0 compatibility mappings only as part of the coherently compiled candidate')
    change('system_ext','/etc/vintf/manifest/r8q-vndk30.xml',
           (vintf/'system_ext/etc/vintf/manifest/r8q-vndk30.xml').read_bytes(),
           'Advertise actual factory VNDK30 APEX providers while preserving VNDK34',metadata_from='/etc/vintf/manifest.xml')
    for part,plan in plans.items():
        if not plan['operations']:raise ValueError('Empty partition change plan')
        (OUT/(part+'-plan.json')).write_text(json.dumps(plan,indent=2)+'\n')
    (OUT/'changes.json').write_text(json.dumps(dict(status='P1_FS_PLANS_NOT_YET_APPLIED',boot_confirmed=False,
        all_original_images_preserved=True,changes=descriptions,
        limits=['Legacy FCM4 deprecation and unused-HAL host checks remain unresolved.','No policy permissions or runtime checks are bypassed.']),indent=2)+'\n')
    print('Prepared',sum(len(p['operations']) for p in plans.values()),'changes in',len(plans),'partition plans')


if __name__=='__main__':main()
