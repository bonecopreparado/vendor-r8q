"""Prepare hash-pinned filesystem changes for P1; do not alter source images."""
from pathlib import Path
import argparse
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
MAPPING_BASE='/etc/selinux/mapping'
MAPPING_PARTITIONS=('system_ext','product')


def parse_mapping_listing(data,part):
    if len(data)>65536:raise ValueError('Mapping directory listing exceeds bound')
    names=[];table=False
    for line in data.decode().splitlines():
        if line.split()==['NID','TYPE','FILENAME']:
            if table:raise ValueError('Duplicate mapping directory table')
            table=True;continue
        if not table or not line.strip():continue
        found=re.fullmatch(r'\s*(\d+)\s+(\d+)\s+(.+)',line)
        if not found:raise ValueError('Malformed mapping directory row')
        _,kind,name=found.groups()
        if name in ('.','..'):
            if kind!='2':raise ValueError('Unexpected mapping directory self entry')
            continue
        if kind!='1' or not re.fullmatch(r'(?:\d{2}\.\d|\d{6})(?:\.compat)?\.cil',name):
            raise ValueError('Unexpected mapping child type or name: '+part+':'+name)
        if name in names:raise ValueError('Duplicate mapping entry')
        names.append(name)
        if len(names)>64:raise ValueError('Too many optional mapping files')
    if not table or not names:raise ValueError('No optional mapping files in '+part)
    return sorted(names)


def mapping_deletions(part):
    """Enumerate a bounded flat mapping directory from a verified donor image.

    Only optional partition mappings are accepted. Inode inspection independently
    rejects links/directories; deleting complete directories is deliberately not
    supported by this plan. The directory itself retains its original metadata.
    """
    if part not in MAPPING_PARTITIONS:
        raise ValueError('Only system_ext/product optional mappings can be omitted')
    from rebuild_erofs_candidate import Image
    image=ROOT/'extracted/hyperos'/(part+'.img')
    tools=ROOT/'tools/image-tools/root/usr/bin'
    fs=Image(image,tools)
    import stat
    directory=fs.entry(MAPPING_BASE)
    if not stat.S_ISDIR(directory['mode']):
        raise ValueError('Mapping base is not a directory: '+part)
    result=subprocess.run([str(tools/'dump.erofs'),'--ls','--path='+MAPPING_BASE,str(image)],
                          capture_output=True,check=True,timeout=30)
    names=parse_mapping_listing(result.stdout,part)
    rows=[]
    for name in sorted(names):
        path=MAPPING_BASE+'/'+name
        meta=fs.entry(path)
        if not stat.S_ISREG(meta['mode']) or meta['nlink']!=1 or not 0<=meta['size']<=1024**2:
            raise ValueError('Mapping deletion requires bounded single-link regular file: '+part+path)
        data=fs.read(path)
        if len(data)!=meta['size']:raise ValueError('Mapping content size differs: '+part+path)
        rows.append(dict(op='delete',path=path,old_sha256=SHA(data),bytes=len(data)))
    return rows


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


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--omit-optional-mappings',action='store_true',
                        help='Experimental donor-guided variant: omit only system_ext/product mapping files')
    args=parser.parse_args(argv)
    subprocess.run([sys.executable,str(ROOT/'tools/materialize_policy_bundle.py')],check=True)
    OUT.mkdir(parents=True,exist_ok=True)
    composition=json.loads((ROOT/'reports/composition-proposed.json').read_text())
    plans={p['partition']:dict(schema_version=1,source_image_sha256=p['sha256'],operations=[])
           for p in composition['partitions'] if args.omit_optional_mappings or p['partition']!='product'}
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
        if args.omit_optional_mappings and path.startswith(MAPPING_BASE+'/'):continue
        old=read('system_ext',path)
        assert SHA(old)==manifest['files']['original/'+name]
        new=(bundle/'candidate'/name).read_bytes()
        assert SHA(new)==manifest['files']['candidate/'+name]
        change('system_ext',path,new,'Resolve duplicate donor types through existing Samsung aliases and declare an already-used mapping attribute; no allow/capability deletion')
    mapping_report=[]
    if args.omit_optional_mappings:
        for part in MAPPING_PARTITIONS:
            for row in mapping_deletions(part):
                plans[part]['operations'].append({key:row[key] for key in ('op','path','old_sha256')})
                descriptions.append(dict(partition=part,path=row['path'],operation='delete',
                    reason='Donor-guided experimental removal of optional partition compatibility mappings; platform mapping and policy CIL remain'))
                mapping_report.append(dict(partition=part,**row))
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
        optional_mapping_variant=args.omit_optional_mappings,
        optional_mapping_deletions=mapping_report,
        platform_mapping_preserved=True,policy_cil_files_preserved=True,
        limits=['Legacy FCM4 deprecation and unused-HAL host checks remain unresolved.',
                'Omitting compatibility mappings changes the resulting policy; it is not proof of boot or equivalent permissions.'
                if args.omit_optional_mappings else 'No policy permissions or runtime checks are bypassed.']),indent=2)+'\n')
    print('Prepared',sum(len(p['operations']) for p in plans.values()),'changes in',len(plans),'partition plans')


if __name__=='__main__':main()
