"""Build and inspect a small Android ARM64 HIDL dump client, never install it.

Only compile-time VNDK stubs/headers are used; no platform/vendor library is
copied into the output. The resulting ELF is an offline review artifact, not
a recovery installer and not yet validated against the phone's linker policy.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
VNDK_REPO = 'https://github.com/msft-mirror-aosp/platform.prebuilts.vndk.v30'
VNDK_COMMIT = '3cb31a86382b624e1167c8c08b835873d9970f34'
NDK_URL = 'https://dl.google.com/android/repository/android-ndk-r27c-linux.zip'
NDK_BYTES = 663987688
# Google's published Linux checksum in android/ndk release r27c. Also record
# SHA256 of the fully verified download, rather than inventing an initial pin.
NDK_SHA1 = '090e8083a715fdb1a3e402d0763c388abb03fb4e'
NDK_VERSION = '27.2.12479018'
NDK_DIRECTORY = 'android-ndk-r27c'
BINARY_NAME = 'r8q-composer-dump'
ALLOWED_NEEDED = frozenset((
    'android.hardware.graphics.composer@2.1.so', 'libhidlbase.so', 'libutils.so',
    'libc++.so', 'liblog.so', 'libc.so', 'libm.so', 'libdl.so',
))
REQUIRED_NEEDED = frozenset((
    'android.hardware.graphics.composer@2.1.so', 'libhidlbase.so', 'libutils.so', 'libc++.so', 'libc.so',
))


def digest(path, name='sha256'):
    h = hashlib.new(name)
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run(argv, output, env):
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [str(value) for value in argv]
    print('STEP ' + output.name, flush=True)
    with output.open('w') as stream:
        stream.write('ARGV ' + json.dumps(command) + '\n')
        stream.flush()
        completed = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                   timeout=20 * 60, check=False)
    if completed.returncode:
        raise RuntimeError(f'{output.name}: command exited {completed.returncode}')
    print('DONE ' + output.name, flush=True)


def git_output(path, *args, env):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True, env=env).strip()


def verify_ndk_archive(archive):
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size != NDK_BYTES:
        raise ValueError('NDK r27c archive length/type differs')
    if digest(archive, 'sha1') != NDK_SHA1:
        raise ValueError('NDK r27c archive official SHA1 differs')
    return {'url': NDK_URL, 'bytes': NDK_BYTES, 'official_sha1': NDK_SHA1,
            'sha256': digest(archive), 'version': NDK_VERSION}


def fetch_ndk(archive):
    # A fixed public URL, no shell, no implicit unaudited third-party installer.
    with urllib.request.urlopen(NDK_URL, timeout=90) as source, archive.open('xb') as target:
        total = 0
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > NDK_BYTES:
                raise ValueError('NDK download exceeds pinned length')
            target.write(chunk)


def extract_ndk(archive, destination, evidence, env):
    prefix = NDK_DIRECTORY + '/toolchains/llvm/prebuilt/linux-x86_64/'
    property_name = NDK_DIRECTORY + '/source.properties'
    # Check the selected archive paths before unzip restores executable modes
    # and relative symlinks. The complete archive has already passed its pin.
    with zipfile.ZipFile(archive) as package:
        selected = [item for item in package.infolist()
                    if item.filename.startswith(prefix) or item.filename == property_name]
        if not selected or sum(item.file_size for item in selected) > 3 * 1024 ** 3:
            raise ValueError('Unexpected NDK extraction size')
        names = set()
        for item in selected:
            name = item.filename
            if name in names or '\\' in name or '..' in Path(name).parts or Path(name).is_absolute():
                raise ValueError('Unexpected NDK member path')
            names.add(name)
    destination.mkdir()
    run(['unzip', '-q', archive, prefix + '*', property_name, '-d', destination],
        evidence / 'ndk-extract.log', env)
    ndk = destination / NDK_DIRECTORY
    properties = (ndk / 'source.properties').read_text()
    if not re.search(r'^Pkg\.Revision\s*=\s*' + re.escape(NDK_VERSION) + r'\s*$', properties, re.M):
        raise ValueError('NDK source.properties revision differs')
    return ndk / 'toolchains/llvm/prebuilt/linux-x86_64'


def checkout_vndk(destination, evidence, env):
    destination.mkdir()
    commands = (
        ['git', 'init', destination],
        ['git', '-C', destination, 'remote', 'add', 'origin', VNDK_REPO],
        ['git', '-C', destination, 'sparse-checkout', 'init', '--cone'],
        ['git', '-C', destination, 'sparse-checkout', 'set', 'arm64'],
        ['git', '-C', destination, 'fetch', '--no-tags', '--depth=1', '--filter=blob:none', 'origin', VNDK_COMMIT],
        ['git', '-C', destination, 'checkout', '--detach', VNDK_COMMIT],
    )
    for i, command in enumerate(commands):
        run(command, evidence / f'vndk-{i}.log', env)
    if git_output(destination, 'rev-parse', 'HEAD', env=env) != VNDK_COMMIT:
        raise ValueError('VNDK checkout commit differs')
    if git_output(destination, 'status', '--porcelain', '--untracked-files=all', env=env):
        raise ValueError('VNDK checkout is not clean')


def include_paths(snapshot):
    includes = snapshot / 'arm64/include'
    relative = (
        'external/libcxx/include', 'external/libcxxabi/include',
        'system/libhidl/base/include', 'system/libhidl/transport/include',
        'system/core/libutils/include', 'system/core/libcutils/include',
        'system/core/liblog/include_vndk', 'system/core/base/include',
        'system/libfmq/include', 'system/core/libsystem/include',
    )
    paths = [includes / name for name in relative]
    required = paths[:9]
    if any(not path.is_dir() for path in required):
        raise ValueError('Required platform HIDL/STL include directory absent')
    paths = [path for path in paths if path.is_dir()]
    generated = includes / 'out/soong/.intermediates'
    paths.extend(sorted(path for path in generated.rglob('gen') if path.is_dir()))
    if not any((path / 'android/hardware/graphics/composer/2.1/IComposer.h').is_file() for path in paths):
        raise ValueError('Generated IComposer 2.1 header absent')
    return paths


def inspect_elf(header, program_headers, dynamic, symbols):
    if not all(value in header for value in ('ELF64', "2's complement, little endian", 'AArch64')):
        raise ValueError('Expected little-endian ARM64 ELF64')
    if not re.search(r'Type:\s+DYN\b', header):
        raise ValueError('Expected PIE executable ELF type DYN')
    if 'Requesting program interpreter: /system/bin/linker64' not in program_headers:
        raise ValueError('Unexpected Android program interpreter')
    if not re.search(r'FLAGS_1.*\bPIE\b', dynamic):
        raise ValueError('Missing PIE dynamic flag')
    needed = set(re.findall(r'\(NEEDED\).*?Shared library: \[([^\]]+)\]', dynamic))
    if not REQUIRED_NEEDED <= needed or not needed <= ALLOWED_NEEDED:
        raise ValueError('Unexpected/missing NEEDED libraries: ' + ', '.join(sorted(needed)))
    if re.search(r'\((?:RPATH|RUNPATH|TEXTREL)\)', dynamic):
        raise ValueError('Unexpected runtime path/text relocation in probe')
    if 'std::__ndk1' in symbols or 'std::__1::basic_string' not in symbols or 'IComposer::tryGetService' not in symbols:
        raise ValueError('Expected platform libc++ ABI on HIDL service lookup')
    return {'machine': 'AArch64', 'class': 'ELF64', 'pie': True,
            'interpreter': '/system/bin/linker64', 'needed': sorted(needed),
            'platform_libcxx_namespace': 'std::__1', 'phone_linker_compatibility_confirmed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=ROOT / '.deps/composer-dump-build')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/composer-dump-build')
    parser.add_argument('--ndk-archive', type=Path, help='Optional exact predownloaded r27c Linux ZIP')
    args = parser.parse_args()
    for path in (args.work, args.output):
        if path.exists() or path.is_symlink():
            raise ValueError('Fresh work/output paths required; no previous files removed')
    args.work.mkdir(parents=True)
    args.output.mkdir(parents=True)
    work, evidence = args.work.resolve(), args.output.resolve()
    report = {'status': 'STARTED', 'vndk_repository': VNDK_REPO, 'vndk_commit': VNDK_COMMIT,
              'phone_execution_tested': False, 'libraries_replaced': False, 'installer_created': False,
              'source_sha256': digest(Path(__file__).with_name('composer_dump.cpp'))}
    (evidence / 'NOT-AN-INSTALLER.txt').write_text(
        'Offline ARM64 ELF review only. This is not a recovery ZIP or boot image.\n'
        'No phone execution, HAL mode capture or Android boot is yet confirmed.\n'
        'Platform/vendor libraries are compile-time inputs only and are not distributed here.\n')
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', LC_ALL='C')
    for key in ('CXXFLAGS', 'CPPFLAGS', 'CFLAGS', 'LDFLAGS', 'LIBRARY_PATH', 'CPATH',
                'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'LD_PRELOAD', 'LD_LIBRARY_PATH'):
        env.pop(key, None)
    try:
        archive = args.ndk_archive or work / 'android-ndk-r27c-linux.zip'
        if args.ndk_archive is None:
            print('Downloading exact official NDK r27c Linux archive', flush=True)
            fetch_ndk(archive)
        report['ndk'] = verify_ndk_archive(archive)
        compiler_root = extract_ndk(archive, work / 'ndk', evidence, env)
        snapshot = work / 'vndk30'
        checkout_vndk(snapshot, evidence, env)
        compiler = compiler_root / 'bin/aarch64-linux-android30-clang++'
        readelf = compiler_root / 'bin/llvm-readelf'
        nm = compiler_root / 'bin/llvm-nm'
        source = Path(__file__).with_name('composer_dump.cpp').resolve()
        executable = evidence / BINARY_NAME
        library_root = snapshot / 'arm64/arch-arm64-armv8-a/shared'
        library_paths = [library_root / 'vndk-core', library_root / 'vndk-sp']
        command = [compiler, '-std=c++17', '-O2', '-fno-exceptions', '-fno-rtti',
                   '-fPIE', '-pie', '-fstack-protector-strong', '-D_FORTIFY_SOURCE=2',
                   '-DANDROID', '-D__ANDROID_VENDOR__', '-nostdinc++', '-nostdlib++',
                   '-Wl,-z,relro,-z,now,-z,max-page-size=4096,--no-undefined,--build-id=sha1',
                   '-Wl,--dynamic-linker=/system/bin/linker64']
        for path in include_paths(snapshot):
            command += ['-isystem', path]
        command += [source, '-o', executable]
        for path in library_paths:
            command += ['-L' + str(path), '-Wl,-rpath-link,' + str(path)]
        command += ['-l:android.hardware.graphics.composer@2.1.so', '-lhidlbase', '-lutils', '-lc++', '-llog']
        run(command, evidence / 'compile.log', env)
        run([readelf, '--file-header', executable], evidence / 'elf-header.txt', env)
        run([readelf, '--program-headers', '--wide', executable], evidence / 'elf-segments.txt', env)
        run([readelf, '--dynamic', '--wide', executable], evidence / 'elf-dynamic.txt', env)
        run([nm, '--undefined-only', '--demangle', executable], evidence / 'elf-undefined-demangled.txt', env)
        report['elf'] = inspect_elf(*[(evidence / name).read_text() for name in
            ('elf-header.txt', 'elf-segments.txt', 'elf-dynamic.txt', 'elf-undefined-demangled.txt')])
        if git_output(snapshot, 'status', '--porcelain', '--untracked-files=all', env=env):
            raise ValueError('Compilation modified the pinned VNDK snapshot')
        report['compiler_sha256'] = digest(compiler_root / 'bin/clang-18')
        report['output'] = {'name': BINARY_NAME, 'bytes': executable.stat().st_size, 'sha256': digest(executable)}
        report['status'] = 'COMPILED_AND_ELF_INSPECTED_NOT_PHONE_TESTED'
        (evidence / (BINARY_NAME + '.sha256')).write_text(report['output']['sha256'] + '  ' + BINARY_NAME + '\n')
        print(json.dumps(report, indent=2), flush=True)
    except Exception as error:
        report['status'] = 'INPUT_OR_COMPILE_OR_ELF_CHECK_FAILED'
        report['error'] = str(error)
        raise
    finally:
        (evidence / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
