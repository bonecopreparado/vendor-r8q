"""Audit a pinned current r8q source configuration; never build a kernel image.

This is an isolated current-kernel experiment, not a reproduction of Not A.06.
Only Kconfig host tools/configuration targets are executed. No AnyKernel script,
ROM image repack, flash command or remote publication is performed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import zlib

ROOT = Path(__file__).resolve().parents[2]
SOURCE_REPO = 'https://github.com/notkernel-oss/not_samsung.sm8250-4.19'
SOURCE_COMMIT = 'a265508933bbecb682e45e3b956d95bf4426d60b'
CLANG_REPO = 'https://github.com/msft-mirror-aosp/platform.prebuilts.clang.host.linux-x86'
CLANG_COMMIT = '5a1f5d58aa30f70047f18cf5fc077a3dd391589c'
CLANG_DIRECTORY = 'clang-r522817'
CLANG_BLOB = '5f9bb95cd5b0c3c7ff9f7579af87b54ed4395190'
CLANG_BYTES = 135214616
BASELINE_SHA = 'ce4b98d368058f4d5fd2c5c3380d53813a10f57c72544838548c61759bceab4a'
SUBMODULES = {
    'KernelSU': ('https://github.com/doubledashdot/sKernelSU', '7d46da2ae166570c14b5336a5f5fe3336aa99f07'),
    'Baseband-guard': ('https://github.com/vc-teahouse/Baseband-guard', 'a54e0dc6cf0aff4dd87fec49644a02d2eb612905'),
    'NoMount': ('https://github.com/maxsteeel/nomount/', '9122a0bf5705e50d9a0ba12ef662413028f3a877'),
}
NFLOG = ('CONFIG_NETFILTER_NETLINK', 'CONFIG_NETFILTER_NETLINK_LOG', 'CONFIG_NETFILTER_XT_TARGET_NFLOG')
FRAGMENTS = ('vendor/kona-perf_defconfig', 'vendor/samsung/kona-sec-common.config',
             'vendor/samsung/r8q.config', 'vendor/not/ksu.config', 'vendor/not/localversion.config')
MAKE_FLAGS = ('ARCH=arm64', 'CC=clang', 'LD=ld.lld', 'AS=llvm-as', 'AR=llvm-ar',
              'NM=llvm-nm', 'OBJCOPY=llvm-objcopy', 'OBJDUMP=llvm-objdump',
              'STRIP=llvm-strip', 'CROSS_COMPILE=aarch64-linux-gnu-',
              'CROSS_COMPILE_ARM32=arm-linux-gnueabi-', 'LLVM=1', 'LLVM_IAS=1')
CORE_PROTECTED = frozenset('''CONFIG_ARM64 CONFIG_ARM64_4K_PAGES CONFIG_ARM64_VA_BITS_39
CONFIG_COMPAT CONFIG_IKCONFIG CONFIG_IKCONFIG_PROC CONFIG_BLK_DEV_INITRD CONFIG_DEVTMPFS
CONFIG_TMPFS CONFIG_BLK_DEV_DM CONFIG_DM_CRYPT CONFIG_F2FS_FS CONFIG_EXT4_FS CONFIG_EROFS_FS
CONFIG_FS_ENCRYPTION CONFIG_SECURITY CONFIG_SECURITY_SELINUX CONFIG_SECCOMP CONFIG_SECCOMP_FILTER
CONFIG_ANDROID_BINDER_IPC CONFIG_ANDROID_BINDER_DEVICES CONFIG_SCSI_UFSHCD CONFIG_SCSI_UFS_QCOM
CONFIG_DRM_MSM CONFIG_SEC_R8Q_PROJECT CONFIG_MODULES CONFIG_KSU CONFIG_KSU_SUSFS'''.split())
HARDWARE_PREFIXES = ('CONFIG_PANEL_', 'CONFIG_TOUCHSCREEN_', 'CONFIG_SENSORS_',
                     'CONFIG_SEC_R8Q_', 'CONFIG_CNSS_', 'CONFIG_SAMSUNG_NFC',
                     'CONFIG_NFC_', 'CONFIG_QCA_', 'CONFIG_CAMERA_')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def parse_config(data):
    if len(data) > 2 * 1024 * 1024 or b'\0' in data:
        raise ValueError('Invalid Kconfig input size/content')
    values = {}
    for line in data.decode('utf-8').splitlines():
        match = re.fullmatch(r'(CONFIG_[A-Za-z0-9_]+)=(.+)', line)
        off = re.fullmatch(r'# (CONFIG_[A-Za-z0-9_]+) is not set', line)
        if match:
            key, value = match.groups()
        elif off:
            key, value = off.group(1), 'n'
        elif line.startswith('CONFIG_'):
            raise ValueError('Malformed Kconfig assignment')
        else:
            continue
        if key in values:
            raise ValueError('Duplicate Kconfig symbol: ' + key)
        values[key] = value
    return values


def enable_nflog(data):
    """Change only the three explicit NFLOG/dependency settings before olddefconfig."""
    parse_config(data)
    seen = set()
    output = []
    for line in data.decode().splitlines():
        found = next((key for key in NFLOG if line.startswith(key + '=') or line == '# ' + key + ' is not set'), None)
        if found:
            output.append(found + '=y')
            seen.add(found)
        else:
            output.append(line)
    output.extend(key + '=y' for key in NFLOG if key not in seen)
    return ('\n'.join(output) + '\n').encode()


def compare_configs(baseline, generated):
    before, after = parse_config(baseline), parse_config(generated)
    added = {k: after[k] for k in sorted(after.keys() - before.keys())}
    removed = {k: before[k] for k in sorted(before.keys() - after.keys())}
    changed = {k: {'before': before[k], 'after': after[k]}
               for k in sorted(before.keys() & after.keys()) if before[k] != after[k]}
    protected = CORE_PROTECTED | {k for k, v in before.items()
        if v == 'y' and (k.startswith(HARDWARE_PREFIXES) or k.startswith('CONFIG_KSU'))}
    regressions = {k: {'before': before[k], 'after': after.get(k)}
                   for k in sorted(protected & before.keys()) if before[k] != after.get(k)}
    nflog = {k: {'before': before.get(k), 'after': after.get(k), 'built_in': after.get(k) == 'y'} for k in NFLOG}
    ksu_delta = {'added': {k: v for k, v in added.items() if k.startswith('CONFIG_KSU')},
                 'removed': {k: v for k, v in removed.items() if k.startswith('CONFIG_KSU')},
                 'changed': {k: v for k, v in changed.items() if k.startswith('CONFIG_KSU')}}
    return dict(added=added, removed=removed, changed=changed,
                protected_failures=regressions, nflog=nflog, kernel_su_transition=ksu_delta,
                semantic_delta_count=len(added) + len(removed) + len(changed),
                protected_checks_passed=not regressions,
                all_nflog_components_builtin=all(after.get(k) == 'y' for k in NFLOG))


def run(argv, log, env, cwd=None, timeout=1200):
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    print('STEP ' + log.name, flush=True)
    with log.open('w') as out:
        out.write('ARGV ' + json.dumps([str(v) for v in argv]) + '\n')
        out.flush()
        try:
            result = subprocess.run([str(v) for v in argv], stdout=out, stderr=subprocess.STDOUT,
                                    env=env, cwd=cwd, timeout=timeout, check=False)
            status = result.returncode
        except subprocess.TimeoutExpired:
            status = 124
            out.write('\nAUDIT_COMMAND_TIMEOUT\n')
    record = {'argv': [str(v) for v in argv], 'exit_code': status,
              'seconds': round(time.monotonic() - started, 3), 'log': log.name}
    print(('DONE ' if status == 0 else 'FAILED ') + log.name + ' ' + str(record['seconds']) + 's', flush=True)
    if status:
        raise RuntimeError(json.dumps(record))
    return record


def output(argv, env, cwd=None):
    return subprocess.check_output([str(v) for v in argv], text=True, env=env, cwd=cwd).strip()


def checkout(repo, commit, destination, logs, name, env, sparse=None):
    if destination.exists() or destination.is_symlink():
        raise ValueError('Preserving existing checkout: ' + str(destination))
    destination.mkdir(parents=True)
    run(['git', 'init', destination], logs / (name + '-init.log'), env)
    run(['git', '-C', destination, 'remote', 'add', 'origin', repo], logs / (name + '-remote.log'), env)
    if sparse:
        run(['git', '-C', destination, 'sparse-checkout', 'init', '--cone'], logs / (name + '-sparse-init.log'), env)
        run(['git', '-C', destination, 'sparse-checkout', 'set', sparse], logs / (name + '-sparse.log'), env)
    run(['git', '-c', 'core.autocrlf=false', '-C', destination, 'fetch', '--no-tags', '--depth=1',
         '--filter=blob:none', 'origin', commit], logs / (name + '-fetch.log'), env)
    run(['git', '-c', 'core.autocrlf=false', '-C', destination, 'checkout', '--detach', commit],
        logs / (name + '-checkout.log'), env)
    if output(['git', '-C', destination, 'rev-parse', 'HEAD'], env) != commit:
        raise ValueError('Checkout identity differs: ' + name)


def verify_submodules(source, logs, env):
    # Inspect the root gitlinks before allowing recursive initialization.
    raw = subprocess.check_output(['git', '-C', str(source), 'ls-tree', '-z', 'HEAD'], env=env)
    actual = {}
    for row in raw.split(b'\0'):
        if not row:
            continue
        left, path = row.split(b'\t', 1)
        mode, kind, commit = left.decode().split()
        if mode == '160000':
            actual[path.decode()] = commit
    if actual != {path: pin[1] for path, pin in SUBMODULES.items()}:
        raise ValueError('Root submodule gitlink set differs from reviewed pins')
    for path, (url, _) in SUBMODULES.items():
        found = output(['git', '-C', source, 'config', '-f', '.gitmodules', '--get', 'submodule.' + path + '.url'], env)
        if found.rstrip('/') != url.rstrip('/'):
            raise ValueError('Submodule URL differs: ' + path)
    run(['git', '-c', 'protocol.file.allow=never', '-C', source, 'submodule', 'update', '--init', '--recursive', '--depth=1'],
        logs / 'kernel-submodules.log', env)
    status = output(['git', '-C', source, 'submodule', 'status', '--recursive'], env)
    records = []
    for row in status.splitlines():
        # strip() can remove the first successful blank marker, so reject only
        # the explicit uninitialized/mismatched/conflicted markers.
        if row[:1] in '-+U':
            raise ValueError('Unverified recursive submodule: ' + row)
        fields = row.split()
        commit, path = fields[:2]
        selected = source / path
        if not selected.resolve().is_relative_to(source.resolve()):
            raise ValueError('Submodule escapes checkout')
        if output(['git', '-C', selected, 'rev-parse', 'HEAD'], env) != commit:
            raise ValueError('Submodule checkout differs: ' + path)
        records.append({'path': path, 'commit': commit,
                        'origin': output(['git', '-C', selected, 'remote', 'get-url', 'origin'], env)})
    for path, (_, commit) in SUBMODULES.items():
        if not any(r['path'] == path and r['commit'] == commit for r in records):
            raise ValueError('Pinned submodule absent: ' + path)
    return records


def configure_profile(name, initial, targets, source, work, evidence, env, baseline):
    directory = work / ('out-' + name)
    directory.mkdir()
    profile = {'name': name, 'kernel_image_built': False, 'targets': list(targets), 'commands': []}
    try:
        if initial is not None:
            (directory / '.config').write_bytes(initial)
            (evidence / (name + '-requested.config')).write_bytes(initial)
        args = ['make', '-C', source, 'O=' + str(directory)] + list(MAKE_FLAGS)
        if targets:
            profile['commands'].append(run(args + list(targets), evidence / (name + '-defconfig.log'), env))
        profile['commands'].append(run(args + ['olddefconfig'], evidence / (name + '-olddefconfig.log'), env))
        generated = (directory / '.config').read_bytes()
        (evidence / (name + '-generated.config')).write_bytes(generated)
        profile['config_sha256'] = sha(generated)
        profile['comparison_with_shipped'] = compare_configs(baseline, generated)
        profile['commands'].append(run(args + ['kernelrelease'], evidence / (name + '-kernelrelease.log'), env))
        profile['status'] = 'CONFIG_GENERATED_NOT_COMPILED'
    except Exception as error:
        profile['status'] = 'CONFIG_GENERATION_FAILED'
        profile['error'] = str(error)
        existing = directory / '.config'
        if existing.is_file():
            (evidence / (name + '-partial.config')).write_bytes(existing.read_bytes())
    write_json(evidence / (name + '-report.json'), profile)
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'tools/kernel_nflog/shipped-config.gz')
    parser.add_argument('--work', type=Path, default=ROOT / '.deps/current-kernel-audit')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/current-kernel-audit')
    args = parser.parse_args()
    if args.baseline.is_symlink() or not args.baseline.is_file():
        raise ValueError('Expected regular compressed shipped config')
    raw = args.baseline.read_bytes()
    if len(raw) > 256 * 1024:
        raise ValueError('Compressed config exceeds bound')
    decoder = zlib.decompressobj(31)
    baseline = decoder.decompress(raw, 2 * 1024 * 1024 + 1)
    if len(baseline) > 2 * 1024 * 1024 or not decoder.eof or decoder.unused_data:
        raise ValueError('Invalid/truncated/oversized compressed baseline')
    if sha(baseline) != BASELINE_SHA:
        raise ValueError('Exact shipped config hash differs')
    parse_config(baseline)
    if args.work.exists() or args.work.is_symlink() or args.output.exists() or args.output.is_symlink():
        raise ValueError('Use a fresh work/output directory; previous audit is preserved')
    args.work.mkdir(parents=True)
    args.output.mkdir(parents=True)
    work, evidence = args.work.resolve(), args.output.resolve()
    report = {'status': 'AUDIT_STARTED', 'source_repository': SOURCE_REPO, 'source_commit': SOURCE_COMMIT,
              'shipped_config_sha256': BASELINE_SHA, 'experiment': 'CURRENT_CANONICAL_KERNEL_NOT_OLD_A06_REPRODUCTION',
              'kernel_images_built': False, 'phone_access': False, 'build_ready': False,
              'toolchain_caveat': 'Pinned Android Clang 18.0.1 is an explicit audit choice; current upstream build.sh downloads a moving Neutron release instead.',
              'profiles': []}
    write_json(evidence / 'summary.json', report)
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', LC_ALL='C', ARCH='arm64', PLATFORM_VERSION='11')
    try:
        source, toolchain = work / 'kernel', work / 'clang'
        checkout(SOURCE_REPO, SOURCE_COMMIT, source, evidence, 'kernel', env)
        report['submodules'] = verify_submodules(source, evidence, env)
        checkout(CLANG_REPO, CLANG_COMMIT, toolchain, evidence, 'clang', env, sparse=CLANG_DIRECTORY)
        binary = toolchain / CLANG_DIRECTORY / 'bin/clang-18'
        if not binary.is_file() or binary.stat().st_size != CLANG_BYTES:
            raise ValueError('Pinned clang-18 file size differs')
        if output(['git', '-C', toolchain, 'hash-object', binary], env) != CLANG_BLOB:
            raise ValueError('Pinned clang-18 Git blob differs')
        env['PATH'] = str(toolchain / CLANG_DIRECTORY / 'bin') + os.pathsep + env['PATH']
        clang_version = output(['clang', '--version'], env)
        if 'clang version 18.0.1' not in clang_version or '11889484' not in clang_version:
            raise ValueError('Unexpected Android Clang banner')
        report['toolchain'] = {'repository': CLANG_REPO, 'commit': CLANG_COMMIT,
                               'directory': CLANG_DIRECTORY, 'clang_git_blob': CLANG_BLOB,
                               'clang_sha256': sha(binary.read_bytes()), 'clang_version': clang_version,
                               'ld_lld_version': output(['ld.lld', '--version'], env)}
        report['environment'] = {'ARCH': env['ARCH'], 'PLATFORM_VERSION': env['PLATFORM_VERSION'],
                                 'make_flags': list(MAKE_FLAGS),
                                 'host_cc': output(['gcc', '--version'], env).splitlines()[0],
                                 'cross_gcc': output(['aarch64-linux-gnu-gcc', '--version'], env).splitlines()[0]}
        report['source_file_sha256'] = {p: sha((source / p).read_bytes()) for p in
            ['Makefile', 'net/netfilter/Makefile', 'include/net/netfilter/nf_log.h', 'net/netfilter/nf_internals.h',
             'KernelSU/kernel/Kconfig', 'KernelSU/kernel/Makefile', '.gitmodules']}
        initial = enable_nflog(baseline)
        report['profiles'].append(configure_profile('shipped-plus-nflog', initial, (), source, work, evidence, env, baseline))
        report['profiles'].append(configure_profile('upstream-r8q', None, FRAGMENTS, source, work, evidence, env, baseline))
        report['source_tracked_changes'] = output(['git', '-C', source, 'diff', '--name-only', 'HEAD', '--'], env)
        if report['source_tracked_changes']:
            raise ValueError('A config target changed tracked source files')
        report['status'] = 'CONFIG_AUDIT_COMPLETED_NOT_COMPILED_OR_BOOT_TESTED'
        report['protected_failures_present'] = any(p.get('comparison_with_shipped', {}).get('protected_failures')
                                                   for p in report['profiles'])
        report['profile_generation_failures'] = [p['name'] for p in report['profiles'] if p['status'] != 'CONFIG_GENERATED_NOT_COMPILED']
        # This success means the audit completed. It never approves source/ABI
        # changes for a build, masks protected regressions or publishes an image.
        write_json(evidence / 'summary.json', report)
        print(json.dumps(report, indent=2))
        return 1 if report['profile_generation_failures'] else 0
    except Exception as error:
        report['status'] = 'INPUT_OR_CONFIGURATION_AUDIT_FAILED'
        report['error'] = str(error)
        write_json(evidence / 'summary.json', report)
        raise


if __name__ == '__main__':
    raise SystemExit(main())
