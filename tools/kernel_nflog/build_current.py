"""Compile a pinned current r8q NFLOG experiment for offline review only.

Outputs raw Image/vmlinux and evidence. Nothing produced by this helper is an
Android boot image, recovery installer or approved/boot-tested phone payload.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_current as audit
import compiler_cache
import current_compat

LOCALVERSION = '-r8q-nflog-staging1'
LTO_MAKE_ARGUMENT = 'LD_FLAGS_LTO_CLANG=-mllvm -import-instr-limit=5 --thinlto-jobs=2 --threads=2'
CLANG_SHA256 = '19823dc3473e9fc514d5c37f11afc1e7d76f9d519257448445a929e46086ffd9'
# ARM64 RELOCATABLE selects ARCH_HAS_RELR. RELR is invisible/default-y with
# this linker and selects LTO_CLANG, so use supported ThinLTO explicitly.
REQUESTED = {
    **{key: 'y' for key in audit.NFLOG},
    'CONFIG_RELR': 'y', 'CONFIG_LTO_CLANG': 'y', 'CONFIG_THINLTO': 'y',
    'CONFIG_POLLY_CLANG': 'n', 'CONFIG_LLVM_POLLY': 'n',
    'CONFIG_BBG': 'n', 'CONFIG_NOMOUNT': 'n',
    # This optional debug iterator UMD uses the absent userprogs build framework
    # in the pinned 4.19 tree. It is not Android's network BPF loader.
    'CONFIG_BPF_PRELOAD_UMD': 'n',
    'CONFIG_ZRAM_BACKEND_LZ4': 'y', 'CONFIG_ZRAM_DEF_COMP_LZ4': 'y',
    'CONFIG_ZRAM_BACKEND_LZO': 'n', 'CONFIG_ZRAM_DEF_COMP_LZORLE': 'n',
    'CONFIG_ZRAM_DEF_COMP_LZO': 'n',
    'CONFIG_LOCALVERSION': '""', 'CONFIG_LOCALVERSION_AUTO': 'n',
}
REMOVED_NAME_REVIEW = {
    'CONFIG_KSU_EXTRAS': 'Obsolete old integration selector; current pinned sKernelSU 3.3.0-25 remains built in.',
    'CONFIG_KSU_ALLOWLIST_WORKAROUND': 'Old selector absent in current sKernelSU; no claim of identical old root semantics.',
    'CONFIG_SENSORS_FINGERPRINT_QCOM': 'Current driver builds GW9558X platform implementation directly; actual sensor selectors must remain y.',
    'CONFIG_FINGERPRINT_SECURE': 'Current GW9558X uses secure platform-driver path unconditionally; raw SPI alternative was removed.',
}
EXTRA_PROTECTED = frozenset('''CONFIG_FINGERPRINT_SECURE CONFIG_SENSORS_GW9558X
CONFIG_QSEECOM CONFIG_ION CONFIG_QCOM_KGSL CONFIG_QCOM_KGSL_IOMMU CONFIG_PINCTRL_MSM
CONFIG_MFD_SPMI_PMIC CONFIG_MMC_SDHCI_MSM CONFIG_USB_DWC3 CONFIG_USB_DWC3_MSM
CONFIG_USB_DWC3_QCOM CONFIG_USB_CONFIGFS CONFIG_USB_CONFIGFS_F_FS CONFIG_USB_CONFIGFS_F_MTP
CONFIG_SECURITY_SELINUX_DEVELOP CONFIG_SECURITY_SELINUX_CHECKREQPROT_VALUE
CONFIG_CMDLINE CONFIG_CMDLINE_EXTEND CONFIG_RELOCATABLE CONFIG_RANDOMIZE_BASE
CONFIG_ZRAM CONFIG_ZRAM_WRITEBACK CONFIG_ZRAM_DEF_COMP
CONFIG_BPF CONFIG_BPF_SYSCALL CONFIG_BPF_LSM CONFIG_BPF_JIT CONFIG_BPF_JIT_ALWAYS_ON
CONFIG_BPF_JIT_DEFAULT_ON CONFIG_CGROUP_BPF CONFIG_NET_CLS_BPF CONFIG_NET_ACT_BPF
CONFIG_BPF_PRELOAD CONFIG_USERMODE_DRIVER'''.split())
REQUIRED_SYMBOLS = frozenset(('nf_log_packet', 'nf_log_register', 'netfilter_log_init',
                              'nfnetlink_log_init', 'nfulnl_log_packet', 'nflog_tg', 'nflog_tg_init'))
SOURCE_EVIDENCE = (
    'Makefile', 'arch/arm64/Makefile', 'arch/arm64/kernel/head.S',
    'arch/arm64/kernel/vmlinux.lds.S', 'arch/Kconfig', 'init/Kconfig',
    'drivers/block/zram/Kconfig', 'drivers/fingerprint/Kconfig', 'drivers/fingerprint/Makefile',
    'drivers/fingerprint/gw9558x_common.c', 'drivers/fingerprint/gw9558x_platform.c',
    'net/netfilter/Makefile', 'net/netfilter/xt_NFLOG.c', 'net/netfilter/nfnetlink_log.c',
    'net/netfilter/nf_log.c', 'include/net/netfilter/nf_log.h', '.gitmodules',
    'kernel/bpf/preload/Kconfig', 'kernel/bpf/preload/Makefile',
    'kernel/bpf/inode.c', 'scripts/Makefile.build',
    'block/mq-deadline.c', 'block/blk-mq-sched.h', 'block/blk-mq.h',
    'drivers/block/zram/zram_drv.c', 'include/linux/bio.h', 'include/linux/fs.h',
    'drivers/ccic/max77705_usbc.c', 'include/linux/cpufreq.h', 'kernel/power/main.c',
    'KernelSU/kernel/Kconfig', 'KernelSU/kernel/Makefile',
    'Baseband-guard/Kconfig', 'NoMount/kernel/src/Kconfig',
)


def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def baseline_bytes(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ValueError('Expected bounded regular shipped-config.gz')
    decoder = zlib.decompressobj(31)
    data = decoder.decompress(path.read_bytes(), 2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024 or not decoder.eof or decoder.unused_data:
        raise ValueError('Malformed/truncated/oversized shipped config')
    if audit.sha(data) != audit.BASELINE_SHA:
        raise ValueError('Exact shipped config SHA256 differs')
    audit.parse_config(data)
    return data


def request_config(baseline):
    audit.parse_config(baseline)
    lines, seen = [], set()
    for line in baseline.decode().splitlines():
        key = line.split('=', 1)[0] if line.startswith('CONFIG_') else None
        match = re.fullmatch(r'# (CONFIG_[A-Za-z0-9_]+) is not set', line)
        if match:
            key = match.group(1)
        if key in REQUESTED:
            lines.append(key + '=' + REQUESTED[key])
            seen.add(key)
        else:
            lines.append(line)
    lines.extend(key + '=' + value for key, value in REQUESTED.items() if key not in seen)
    return ('\n'.join(lines) + '\n').encode()


def config_guards(baseline, generated):
    before, after = audit.parse_config(baseline), audit.parse_config(generated)
    comparison = audit.compare_configs(baseline, generated)
    failures = dict(comparison['protected_failures'])
    for key in EXTRA_PROTECTED & before.keys():
        if before[key] != after.get(key):
            failures[key] = {'before': before[key], 'after': after.get(key)}
    reviewed = {}
    for key, reason in REMOVED_NAME_REVIEW.items():
        if key in failures and key not in after:
            reviewed[key] = {**failures.pop(key), 'review': reason}
    # These mappings are permitted only with the actual sensor implementation
    # retained. A deleted/replaced driver cannot pass by deleting old selectors.
    for key in ('CONFIG_SENSORS_FINGERPRINT', 'CONFIG_SENSORS_GW9558X', 'CONFIG_KSU', 'CONFIG_KSU_SUSFS'):
        if before.get(key) != 'y' or after.get(key) != 'y':
            failures[key] = {'before': before.get(key), 'after': after.get(key), 'required': 'y'}
    for key, requested in REQUESTED.items():
        actual = after.get(key, 'n')
        if actual != requested:
            failures[key] = {'requested': requested, 'after': after.get(key)}
    if after.get('CONFIG_ZRAM_DEF_COMP') != '"lz4"':
        failures['CONFIG_ZRAM_DEF_COMP'] = {'required': '"lz4"', 'after': after.get('CONFIG_ZRAM_DEF_COMP')}
    if after.get('CONFIG_HZ') != '250':
        failures['CONFIG_HZ'] = {'required': '250', 'after': after.get('CONFIG_HZ')}
    comparison['reviewed_removed_name_mappings'] = reviewed
    comparison['build_guard_failures'] = failures
    comparison['build_config_guards_passed'] = not failures
    return comparison


def image_header(data, file_bytes):
    if len(data) < 64 or data[56:60] != b'ARM\x64':
        raise ValueError('Expected raw ARM64 Image header')
    text_offset, memory_size, flags = struct.unpack_from('<QQQ', data, 8)
    if memory_size < file_bytes or memory_size > 256 * 1024 * 1024 or file_bytes > 64 * 1024 * 1024:
        raise ValueError('ARM64 Image bounds are inconsistent')
    if flags & 1 or ((flags >> 1) & 3) != 1:
        raise ValueError('Expected little-endian 4 KiB ARM64 Image flags')
    if text_offset != 0:
        raise ValueError('Pinned current head.S specifies zero text/load offset')
    return {'magic': 'ARM64', 'text_offset': text_offset, 'text_offset_hex': hex(text_offset),
            'memory_size': memory_size, 'flags': flags, 'flags_hex': hex(flags),
            'little_endian': True, 'page_size': 4096, 'file_bytes': file_bytes,
            'shipped_old_text_offset': 524288, 'shipped_old_text_offset_hex': '0x80000',
            'old_bootloader_dtb_compatibility_confirmed': False}


def defined_symbols(nm_output):
    symbols = set()
    for line in nm_output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[-2].upper() != 'U':
            symbols.add(fields[-1])
    missing = sorted(REQUIRED_SYMBOLS - symbols)
    if missing:
        raise ValueError('Missing defined NFLOG symbols: ' + ', '.join(missing))
    return sorted(REQUIRED_SYMBOLS)


def verify_toolchain(toolchain, env):
    binary = toolchain / audit.CLANG_DIRECTORY / 'bin/clang-18'
    if not binary.is_file() or binary.stat().st_size != audit.CLANG_BYTES:
        raise ValueError('Pinned clang-18 size differs')
    if audit.output(['git', '-C', toolchain, 'hash-object', binary], env) != audit.CLANG_BLOB:
        raise ValueError('Pinned clang-18 Git blob differs')
    compiler_sha = file_sha(binary)
    if compiler_sha != CLANG_SHA256:
        raise ValueError('Pinned clang-18 SHA256 differs')
    env['PATH'] = str(toolchain / audit.CLANG_DIRECTORY / 'bin') + os.pathsep + env['PATH']
    version = audit.output(['clang', '--version'], env)
    if 'clang version 18.0.1' not in version or '11889484' not in version:
        raise ValueError('Pinned Android clang banner differs')
    linker_help = audit.output(['ld.lld', '--help'], env)
    if not all(option in linker_help for option in ('--thinlto-jobs', '--threads')):
        raise ValueError('Pinned linker cannot enforce the reviewed ThinLTO worker limits')
    return {'repository': audit.CLANG_REPO, 'commit': audit.CLANG_COMMIT,
            'directory': audit.CLANG_DIRECTORY, 'clang_git_blob': audit.CLANG_BLOB,
            'clang_sha256': compiler_sha, 'clang_version': version,
            'ld_lld_version': audit.output(['ld.lld', '--version'], env),
            'lto_make_argument': LTO_MAKE_ARGUMENT}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=audit.ROOT / 'tools/kernel_nflog/shipped-config.gz')
    parser.add_argument('--work', type=Path, default=audit.ROOT / '.deps/current-kernel-build')
    parser.add_argument('--output', type=Path, default=audit.ROOT / 'reports/current-kernel-build')
    parser.add_argument('--clang-cache', type=Path, help='Optional verified compiler-only cache outside fresh work/output')
    parser.add_argument('--jobs', type=int, choices=(1, 2, 3), default=2)
    args = parser.parse_args()
    baseline = baseline_bytes(args.baseline)
    for path in (args.work, args.output):
        if path.exists() or path.is_symlink():
            raise ValueError('Use fresh work/output paths; preserving previous files')
    args.work.mkdir(parents=True)
    args.output.mkdir(parents=True)
    work, evidence = args.work.resolve(), args.output.resolve()
    report = {'status': 'STARTED', 'experiment': 'CURRENT_CANONICAL_KERNEL_NOT_A06_REPRODUCTION',
              'source_repository': audit.SOURCE_REPO, 'source_commit': audit.SOURCE_COMMIT,
              'baseline_sha256': audit.BASELINE_SHA, 'localversion_argument': LOCALVERSION,
              'boot_image_created': False, 'installer_created': False, 'flashable': False,
              'hardware_boot_confirmed': False, 'old_dtb_compatibility_confirmed': False,
              'requested_options': REQUESTED, 'commands': [],
              'reviewed_source_changes': [
                  'HZ600 was removed upstream; current HZ250 retained as an explicit scheduler change.',
                  'Current ARM64 relocation support forces RELR and LTO_CLANG; ThinLTO is explicitly retained instead of full LTO.',
                  'Scheduler, RNG and root integration differ from A06; successful compilation proves no boot compatibility.',
                  'Current ARM64 Image uses text_offset=0; old shipped Image uses 0x80000. No header patch or boot repack is performed.',
                  'Clang18 is pinned to old compiler identity; upstream current build.sh instead downloads moving Neutron.',
                  'Optional new BPF_PRELOAD_UMD debug iterators are disabled: userprogs build support is absent in this tree. Existing Android/network BPF selectors remain protected.',
                  'Exact reviewed API compatibility patches preserve the shipped scheduler and writeback features; only pinned tracked source modifications are accepted.',
                  'MAX77705 CPU frequency votes are compiled only when their actual CPU_FREQ_LIMIT_USERSPACE provider exists; USB/PD, HMP, DDR and timers remain unchanged.'
              ]}
    (evidence / 'NOT-FLASHABLE.txt').write_text(
        'OFFLINE REVIEW ONLY. Raw Image/vmlinux are NOT a flashable ZIP or Android boot.img.\n'
        'No phone has booted this build. Old DTB/ramdisk/bootloader compatibility is unconfirmed.\n'
        'Do not flash these artifacts as a partition image.\n')
    audit.write_json(evidence / 'summary.json', report)
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', LC_ALL='C', ARCH='arm64', PLATFORM_VERSION='11',
               KBUILD_BUILD_USER='r8q-ci', KBUILD_BUILD_HOST='github-actions',
               KBUILD_BUILD_TIMESTAMP='Tue Nov 10 00:00:00 UTC 2026')
    # Avoid caller compiler/make override variables silently changing provenance.
    for key in ('KCONFIG_CONFIG', 'MAKEFLAGS', 'MFLAGS', 'KBUILD_OUTPUT', 'KCFLAGS', 'KCPPFLAGS',
                'KAFLAGS', 'KBUILD_CFLAGS', 'KBUILD_LDFLAGS', 'LLVM', 'LLVM_IAS', 'LOCALVERSION'):
        env.pop(key, None)
    try:
        source, clang, out = work / 'kernel', work / 'clang', work / 'out'
        audit.checkout(audit.SOURCE_REPO, audit.SOURCE_COMMIT, source, evidence, 'kernel', env)
        report['submodules'] = audit.verify_submodules(source, evidence, env)
        report['reviewed_source_overlay'] = current_compat.apply(source, evidence, env)
        compiler = compiler_cache.prepare_compiler(clang, evidence, env, verify_toolchain,
                                                   cache=args.clang_cache, work=work, output=evidence)
        report['toolchain'] = compiler['toolchain']
        report['compiler_cache'] = compiler['cache']
        if compiler['cache']['enabled']:
            # The workflow saves only after the actual cache and private copy
            # have both passed identity verification, even if Image later fails.
            (evidence / 'compiler-cache-verified.txt').write_text(
                json.dumps({'clang_sha256': report['toolchain']['clang_sha256'],
                            'commit': report['toolchain']['commit']}, sort_keys=True) + '\n')
        report['environment'] = {'ARCH': 'arm64', 'PLATFORM_VERSION': '11', 'jobs': args.jobs,
                                 'host_gcc': audit.output(['gcc', '--version'], env).splitlines()[0],
                                 'cross_gcc': audit.output(['aarch64-linux-gnu-gcc', '--version'], env).splitlines()[0]}
        report['source_file_sha256'] = {name: file_sha(source / name) for name in SOURCE_EVIDENCE}
        out.mkdir()
        requested = request_config(baseline)
        (out / '.config').write_bytes(requested)
        (evidence / 'requested.config').write_bytes(requested)
        make = ['make', '-C', source, 'O=' + str(out)] + list(audit.MAKE_FLAGS) + ['LOCALVERSION=' + LOCALVERSION, LTO_MAKE_ARGUMENT]
        report['commands'].append(audit.run(make + ['olddefconfig'], evidence / 'olddefconfig.log', env))
        generated = (out / '.config').read_bytes()
        (evidence / 'generated.config').write_bytes(generated)
        report['config_sha256'] = audit.sha(generated)
        report['comparison_with_shipped'] = config_guards(baseline, generated)
        audit.write_json(evidence / 'summary.json', report)
        if not report['comparison_with_shipped']['build_config_guards_passed']:
            raise ValueError('Generated configuration failed protected/requested guards; Image compilation was not started')
        report['commands'].append(audit.run(make + ['kernelrelease'], evidence / 'kernelrelease.log', env))
        release = audit.output(make + ['-s', 'kernelrelease'], env)
        if LOCALVERSION not in release or 'A.06' in release:
            raise ValueError('Kernel release identity is not the explicit current-source experiment')
        report['kernelrelease'] = release
        report['status'] = 'CONFIG_GUARDS_PASSED_COMPILING_IMAGE'
        audit.write_json(evidence / 'summary.json', report)
        report['commands'].append(audit.run(make + ['-j' + str(args.jobs), 'Image'],
                                            evidence / 'compile.log', env, timeout=75 * 60))
        if (out / '.config').read_bytes() != generated:
            raise ValueError('Compilation changed the reviewed generated config')
        image = out / 'arch/arm64/boot/Image'
        vmlinux = out / 'vmlinux'
        for path in (image, vmlinux):
            if path.is_symlink() or not path.is_file():
                raise ValueError('Missing regular build output: ' + str(path))
        with image.open('rb') as handle:
            report['image_header'] = image_header(handle.read(64), image.stat().st_size)
        report['commands'].append(audit.run(['llvm-nm', '--defined-only', vmlinux],
                                            evidence / 'vmlinux-defined-symbols.log', env))
        report['required_defined_symbols'] = defined_symbols((evidence / 'vmlinux-defined-symbols.log').read_text())
        report['tracked_source_changes'] = current_compat.verify_applied(source, env)
        report['submodule_changes'] = {item['path']: audit.output(
            ['git', '-C', source / item['path'], 'diff', '--name-only', 'HEAD', '--'], env)
            for item in report['submodules']}
        if any(report['submodule_changes'].values()):
            raise ValueError('Build modified pinned submodule source; retaining logs without accepting output')
        report['outputs'] = {}
        for label, path in (('Image', image), ('vmlinux', vmlinux), ('System.map', out / 'System.map')):
            target = evidence / label
            shutil.copyfile(path, target)
            report['outputs'][label] = {'bytes': target.stat().st_size, 'sha256': file_sha(target)}
        report['status'] = 'COMPILED_FOR_OFFLINE_REVIEW_NOT_FLASHABLE_OR_BOOT_TESTED'
        audit.write_json(evidence / 'summary.json', report)
        print(json.dumps({k: report[k] for k in ('status', 'kernelrelease', 'outputs', 'image_header', 'flashable')}, indent=2))
        return 0
    except Exception as error:
        report['status'] = 'INPUT_CONFIG_OR_COMPILE_FAILED'
        report['error'] = str(error)
        audit.write_json(evidence / 'summary.json', report)
        raise


if __name__ == '__main__':
    raise SystemExit(main())
