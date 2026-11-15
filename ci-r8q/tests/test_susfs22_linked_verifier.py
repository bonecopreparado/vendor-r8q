"""Independent embedded-kernel guards using synthetic Image/IKCONFIG data."""
from pathlib import Path
import copy
import gzip
import hashlib
import struct
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/kernel_nflog/susfs22'))
import verify_linked as verifier


def fixture(changes=None):
    b=verifier.build
    baseline=b.baseline_bytes(ROOT/'tools/kernel_nflog/shipped-config.gz')
    values=b.audit.parse_config(baseline)
    values.update(b.REQUESTED)
    values.update(CONFIG_ZRAM_DEF_COMP='"lz4"',CONFIG_HZ='250')
    for key in b.REMOVED_NAME_REVIEW:values.pop(key,None)
    values.update(changes or {})
    config=('# Linux/arm64 synthetic linked-kernel regression fixture\n'+
            ''.join(key+'='+value+'\n'for key,value in values.items())).encode()
    kernel=bytearray(128*1024)
    struct.pack_into('<QQQ',kernel,8,0,256*1024,10)
    kernel[56:60]=b'ARM\x64'
    blob=b'IKCFG_ST'+gzip.compress(config,mtime=0)+b'IKCFG_ED'
    kernel[100:100+len(blob)]=blob
    kernel=bytes(kernel)
    report=dict(status='COMPILED_FOR_OFFLINE_REVIEW_NOT_FLASHABLE_OR_BOOT_TESTED',
        source_repository=b.audit.SOURCE_REPO,source_commit=b.audit.SOURCE_COMMIT,
        baseline_sha256=b.audit.BASELINE_SHA,experiment='CURRENT_CANONICAL_KERNEL_NOT_A06_REPRODUCTION',
        localversion_argument=b.LOCALVERSION,kernelrelease='4.19.325'+b.LOCALVERSION,
        requested_options=b.REQUESTED,boot_image_created=False,installer_created=False,
        flashable=False,hardware_boot_confirmed=False,old_dtb_compatibility_confirmed=False,
        reviewed_source_overlay=verifier.source.expected_overlay(),
        tracked_source_changes='\n'.join(verifier.source.TRACKED),
        submodules=[dict(path=p,origin=url,commit=commit)for p,(url,commit)in b.audit.SUBMODULES.items()],
        submodule_changes={p:''for p in b.audit.SUBMODULES},
        toolchain=dict(repository=b.audit.CLANG_REPO,commit=b.audit.CLANG_COMMIT,
            directory=b.audit.CLANG_DIRECTORY,clang_git_blob=b.audit.CLANG_BLOB,
            clang_sha256=b.CLANG_SHA256,lto_make_argument=b.LTO_MAKE_ARGUMENT),
        required_defined_symbols=sorted(b.REQUIRED_SYMBOLS|verifier.source.SUSFS_SYMBOLS),
        outputs=dict(Image=dict(bytes=len(kernel),sha256=verifier.sha(kernel)),
                     vmlinux=dict(bytes=1000,sha256='a'*64),**{'System.map':dict(bytes=100,sha256='b'*64)}),
        config_sha256=verifier.sha(config),image_header=b.image_header(kernel[:64],len(kernel)),
        comparison_with_shipped=dict(build_config_guards_passed=True,build_guard_failures={}))
    return kernel,report


class Tests(unittest.TestCase):
    def test_exact_record_is_bound_to_image_and_all_preserved_susfs_features(self):
        kernel,report=fixture()
        result=verifier.verify(kernel,report)
        self.assertIs(result['susfs_enabled'],True)
        self.assertIn('CONFIG_KSU_SUSFS_SUS_PATH',result['preserved_susfs_options'])
        self.assertIs(result['hardware_boot_confirmed'],False)

    def test_claimed_success_cannot_hide_actual_missing_nflog_or_susfs(self):
        for key in ('CONFIG_NETFILTER_NETLINK_LOG','CONFIG_KSU_SUSFS','CONFIG_KSU_SUSFS_SUS_PATH'):
            kernel,report=fixture({key:'n'})
            with self.subTest(key=key),self.assertRaises(ValueError):
                verifier.verify(kernel,report)

    def test_modified_source_compiler_submodule_symbols_or_claims_are_rejected(self):
        kernel,valid=fixture()
        mutations=(
            lambda r:r.update(status='INPUT_CONFIG_OR_COMPILE_FAILED'),
            lambda r:r.update(source_commit='0'*40),
            lambda r:r['reviewed_source_overlay']['susfs22'].update(patch_sha256='0'*64),
            lambda r:r.update(tracked_source_changes=''),
            lambda r:r['toolchain'].update(clang_sha256='0'*64),
            lambda r:r['submodules'][0].update(commit='0'*40),
            lambda r:r['submodules'].append(r['submodules'][0]),
            lambda r:r['required_defined_symbols'].pop(),
            lambda r:r['outputs']['Image'].update(sha256='0'*64),
            lambda r:r.update(config_sha256='0'*64),
            lambda r:r.update(hardware_boot_confirmed=True),
        )
        for mutation in mutations:
            report=copy.deepcopy(valid);mutation(report)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                verifier.verify(kernel,report)


if __name__=='__main__':unittest.main()
