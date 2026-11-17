"""Recheck new boot/probe inputs and prepare mandatory P1r4 ZIP extras."""
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile


def sha(data):return hashlib.sha256(data).hexdigest()


def input_file(root,name,limit):
    if not isinstance(name,str)or not name or '\\'in name or Path(name).is_absolute()or any(p in ('','.','..')for p in name.split('/')):
        raise ValueError('Revision input must be a canonical relative path')
    path=root/name
    if path.is_symlink()or not path.resolve().is_relative_to(root.resolve())or not path.is_file()or not 0<path.stat().st_size<=limit:
        raise ValueError('Missing, oversized or escaping revision input: '+name)
    return path


def collector_bytes(root,build_label='P1r4'):
    sys.path.insert(0,str(root/'tools/bootdiag_v6'))
    import render
    readme=b'''R8Q BOOTDIAG V6 COLLECT-ONLY - NOT A ROM

The P1r4 ROM already includes V6 diagnostics. After a boot attempt, return
directly to TWRP or OrangeFox and install this collector ZIP. It copies logs to the
Download folder and displays the resulting .tar.gz path. Send that archive
privately; a PARTIAL archive is still useful. Keep the archive compressed.

Mount Data/storage if requested. If collection fails, preserve recovery.log.
This collector does not enable diagnostics, flash partitions or erase captures.
'''
    readme=readme.replace(b'P1r4',build_label.encode())
    members={'META-INF/com/google/android/update-binary':(render.render_collector(),0o755),
             'META-INF/com/google/android/updater-script':(b'# Read-only V6 diagnostic collection.\n',0o644),
             'README-ENGLISH.txt':(readme,0o644),'LICENSE.txt':((root/'LICENSE').read_bytes(),0o644)}
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9)as archive:
        for name,(data,mode)in members.items():
            info=zipfile.ZipInfo(name,(2026,11,14,0,0,0));info.create_system=3
            info.external_attr=(0o100000|mode)<<16;info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,data)
    result=buffer.getvalue()
    with zipfile.ZipFile(io.BytesIO(result))as archive:
        if archive.testzip()is not None:raise ValueError('Collector ZIP CRC differs')
    return result


def collect(manifest,root):
    root=Path(root)
    if manifest.get('build_label')not in ('P1r4','P1r5'):raise ValueError('Expected explicit linked-kernel manifest')
    inputs=manifest.get('kernel_repack_inputs')
    if not isinstance(inputs,dict)or set(inputs)!={'source_boot_file','kernel_file','summary_file'}:
        raise ValueError('Missing real kernel/repack inputs')
    sys.path.insert(0,str(root/'tools/kernel_nflog/susfs22'))
    import repack_verified
    old=input_file(root,inputs['source_boot_file'],67108864).read_bytes()
    kernel=input_file(root,inputs['kernel_file'],67108864).read_bytes()
    summary=json.loads(input_file(root,inputs['summary_file'],1024**2).read_text())
    candidate,proof=repack_verified.repack(old,kernel,summary)
    if proof!=manifest.get('kernel_repack'):
        raise ValueError('Regenerated boot evidence differs from manifest')
    stage=manifest.get('diagnostic_stage')
    diagnostic=stage.get('diagnostics')if isinstance(stage,dict)else None
    if not isinstance(diagnostic,dict)or diagnostic.get('namespace')!='/metadata/r8q-bootdiag-v6':
        raise ValueError('Fresh embedded V6 diagnostic evidence is required')
    probe_dir=manifest.get('diagnostic_probe_dir')
    if not isinstance(probe_dir,str)or Path(probe_dir).is_absolute()or '..'in Path(probe_dir).parts:
        raise ValueError('Expected relative native probe evidence directory')
    directory=(root/probe_dir).resolve()
    if not directory.is_relative_to(root.resolve()):raise ValueError('Native probe directory escapes checkout')
    sys.path.insert(0,str(root/'tools'))
    import package_bootdiag_v5
    helper,build,notices=package_bootdiag_v5.validate_probe(directory)
    if sha(helper)!=diagnostic.get('probe_sha256')or build!=diagnostic.get('probe_build'):
        raise ValueError('Actual native build differs from staged evidence')
    required={name:sha(data)for name,data in notices.items()}
    if diagnostic.get('required_zip_licenses')!=required:
        raise ValueError('Native license evidence differs')
    extras={}
    for name,data in notices.items():
        path=input_file(root,'patches/0008-boot-fixes/zip-extra/'+name,6*1024**2)
        if path.read_bytes()!=data:raise ValueError('Staged native license differs')
        extras['licenses/display-probe/'+Path(name).name]=data
    collector=collector_bytes(root,manifest['build_label'])
    name='extras/R8Q-BOOTDIAG-V6-COLLECT-ONLY.zip'
    extras[name]=collector
    extras[name+'.sha256']=(sha(collector)+'  '+Path(name).name+'\n').encode()
    evidence=dict(kernel_repack=proof,diagnostic_namespace=diagnostic['namespace'],
        native_probe_sha256=sha(helper),susfs_enabled=True,hardware_boot_confirmed=False,
        extra_members={name:dict(bytes=len(data),sha256=sha(data))for name,data in extras.items()})
    return sha(candidate),extras,evidence
