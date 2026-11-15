"""Bind a successful SUSFS22 compile record to its actual raw ARM64 Image.

This admits a candidate for offline boot repacking only. The build record must
come from the trusted pinned workflow; no hardware boot claim is accepted.
"""
import hashlib
import importlib.util
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import compile_experiment as source
build=source.build


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify(kernel,report):
    if not isinstance(report,dict) or report.get('status')!='COMPILED_FOR_OFFLINE_REVIEW_NOT_FLASHABLE_OR_BOOT_TESTED':
        raise ValueError('A successful complete compile record is required')
    if (report.get('root_profile','PRESERVE_SHIPPED_SUSFS')!='PRESERVE_SHIPPED_SUSFS' or
        report.get('susfs_enabled',True)is not True or report.get('susfs_exclusion_reason')is not None):
        raise ValueError('Contradictory or disabled SUSFS profile is refused')
    pins={'source_repository':build.audit.SOURCE_REPO,'source_commit':build.audit.SOURCE_COMMIT,
          'baseline_sha256':build.audit.BASELINE_SHA,
          'experiment':'CURRENT_CANONICAL_KERNEL_NOT_A06_REPRODUCTION',
          'localversion_argument':build.LOCALVERSION,
          'kernelrelease':'4.19.325'+build.LOCALVERSION,'requested_options':build.REQUESTED}
    for key,value in pins.items():
        if report.get(key)!=value:
            raise ValueError('Kernel build pin differs: '+key)
    for key in ('boot_image_created','installer_created','flashable','hardware_boot_confirmed','old_dtb_compatibility_confirmed'):
        if report.get(key) is not False:
            raise ValueError('Unexpected build/boot claim: '+key)
    if report.get('reviewed_source_overlay')!=source.expected_overlay() or report.get('tracked_source_changes','').splitlines()!=source.TRACKED:
        raise ValueError('Complete source overlay/changes differ')
    submodules=report.get('submodules')
    expected=build.audit.SUBMODULES
    if not isinstance(submodules,list) or len(submodules)!=len(expected):
        raise ValueError('Submodule evidence differs')
    actual={}
    for row in submodules:
        if not isinstance(row,dict) or row.get('path') in actual or not isinstance(row.get('origin'),str):
            raise ValueError('Malformed/duplicate submodule evidence')
        actual[row.get('path')]=(row['origin'].rstrip('/'),row.get('commit'))
    if actual!={p:(url.rstrip('/'),commit)for p,(url,commit)in expected.items()}:
        raise ValueError('Submodule pins differ')
    if report.get('submodule_changes')!={p:'' for p in expected}:
        raise ValueError('Unexpected modified submodule')
    compiler=report.get('toolchain',{})
    tool_pins={'repository':build.audit.CLANG_REPO,'commit':build.audit.CLANG_COMMIT,
        'directory':build.audit.CLANG_DIRECTORY,'clang_git_blob':build.audit.CLANG_BLOB,
        'clang_sha256':build.CLANG_SHA256,'lto_make_argument':build.LTO_MAKE_ARGUMENT}
    if any(compiler.get(key)!=value for key,value in tool_pins.items()):
        raise ValueError('Compiler identity differs')
    symbols=report.get('required_defined_symbols')
    required=build.REQUIRED_SYMBOLS|source.SUSFS_SYMBOLS
    if not isinstance(symbols,list) or len(symbols)!=len(required) or set(symbols)!=required:
        raise ValueError('Real NFLOG/SUSFS link evidence differs')
    outputs=report.get('outputs',{})
    if outputs.get('Image')!={'bytes':len(kernel),'sha256':sha(kernel)}:
        raise ValueError('Actual Image differs from build output')
    for name in ('vmlinux','System.map'):
        row=outputs.get(name,{})
        if type(row.get('bytes'))is not int or row['bytes']<=0 or not re.fullmatch('[0-9a-f]{64}',row.get('sha256','')):
            raise ValueError('Linked output identity missing: '+name)
    header=build.image_header(kernel[:64],len(kernel))
    if header!=report.get('image_header'):
        raise ValueError('Actual ARM64 header differs')
    spec=importlib.util.spec_from_file_location('susfs22_ikconfig',build.audit.ROOT/'tools/audit_boot_kernel_input.py')
    ikconfig=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ikconfig)
    _,_,text=ikconfig.extract_config(kernel)
    config=text.encode('ascii')
    if sha(config)!=report.get('config_sha256'):
        raise ValueError('Embedded configuration differs')
    baseline=build.baseline_bytes(build.audit.ROOT/'tools/kernel_nflog/shipped-config.gz')
    comparison=build.config_guards(baseline,config)
    if comparison['build_config_guards_passed'] is not True:
        raise ValueError('Independent embedded config guards failed')
    before,after=build.audit.parse_config(baseline),build.audit.parse_config(config)
    preserved={key for key,value in before.items()if key.startswith('CONFIG_KSU_SUSFS')and value=='y'}
    if any(after.get(key)!='y' for key in preserved):
        raise ValueError('A requested SUSFS feature was removed')
    recorded=report.get('comparison_with_shipped',{})
    if recorded.get('build_config_guards_passed')is not True or recorded.get('build_guard_failures')!={}:
        raise ValueError('Build did not pass configuration checks')
    return dict(status='LINKED_IMAGE_VERIFIED_FOR_OFFLINE_REPACK_ONLY',kernel_sha256=sha(kernel),
        embedded_config_sha256=sha(config),susfs_enabled=True,preserved_susfs_options=sorted(preserved),
        source_overlay=source.expected_overlay(),hardware_boot_confirmed=False,
        old_dtb_compatibility_confirmed=False,trusted_ci_record_required=True)
