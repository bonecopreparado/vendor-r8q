"""Prepare an ordered V3/V4->V5 diagnostic upgrade, never a ROM or kernel."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/display_probe'))
import build_probe as native

V3_RC_SHA = 'f87c5e2be6ce97d93d2aba1098495f3b2f33479a98878b0adab5be888a3fb447'
V3_SH_SHA = '6f4bbbd50c76646d39da99a0c149de8dba260072bc6317ccdcb04d5707f1154d'
V4_SH_SHA = '82805c4960d077fbe7f46e83b335aefc10dc3472ba598a972a4e1b5599bc6106'
VENDOR_SHA = '9971fef6dfa6951ec593bd82351203deb71e6185a4eea5354fe2fef3912114ea'
NOTICE_NAMES = frozenset((
    'NDK-NOTICE.txt', 'NDK-NOTICE.toolchain.txt', 'VNDK30-libc++.so.txt',
    'VNDK30-libhidlbase.so.txt', 'VNDK30-libutils.so.txt', 'VNDK30-HEADER-NOTICES.txt',
))
README = """R8Q BOOTDIAG V5 - EXPERIMENTAL DISPLAY EVIDENCE, NOT A ROM

Requires the reviewed P1 vendor and exact diagnostic V3 or V4 already enabled.
This addon keeps the existing init rc and ROM/kernel unchanged. It adds one
small ARM64 dump helper under a content-addressed vendor filename and replaces
only the diagnostic runtime. No existing system/vendor library is replaced.

The helper calls the existing HIDL composer's dumpDebugInfo() without creating
a composer client or setting display modes/properties. The library namespace
and SELinux execution access still require a phone test. If native execution
fails, stderr/status are saved and the other diagnostic probes continue.
The already-registered-service check reduces unintended lazy-service starts,
but a service disappearing between list and lookup remains a documented race.

PHONE-ONLY TEST: NO COMPUTER OR INSTALLER CREATION IS NEEDED

1. Download ENABLE.zip and COLLECT-ONLY.zip below. Check each ZIP SHA256 against
   its sidecar using a phone file manager/hash utility. In OrangeFox, Mount
   Vendor, then install R8Q-BOOTDIAG-V5-ENABLE.zip. Keep the installed ROM,
   ueventd bridge and existing diagnostic setup.
2. Reboot System once. If stuck at Samsung, allow about 2 minutes, then return
   directly to OrangeFox. No Format Data or repeated ROM installation.
3. Install R8Q-BOOTDIAG-V5-COLLECT-ONLY.zip in OrangeFox. Read its saved output
   path. Send the new R8Q-BOOTDIAG-V5-logs-*.tar.gz from Download privately.
   Do not flash or extract that .tar.gz. If its name contains PARTIAL, send
   it together with the collector's error text/photo; it is incomplete.

COLLECT-ONLY copies diagnostic logs into a real bounded .tar.gz. It does not
flash a ROM/kernel, change Vendor/System or erase the original captures. If
metadata is not mounted it may mount only that log partition read-only with
journal replay disabled, then unmount only its own mount. This is separate
from the installer's required writable Vendor update.

To undo this upgrade, use RESTORE-V4 if you were on V4, or RESTORE-V3 if
   you were on V3. Restoration changes the runtime first, then removes only
   the exact known helper. Captured V3/V4/V5 evidence is preserved.

Installation is ordered and resumable, not a two-file atomic transaction.
An interruption before runtime activation can leave an unused verified helper;
repeating ENABLE or the correct RESTORE resolves that known partial state.
Unknown files/hashes are never overwritten or deleted. Remain in recovery if
an installation step fails and keep its recovery.log.

The native helper's output cap is 128 KiB; it and its wrapper use short timeouts.
Each V5 capture remains below 2 MiB, at most three new captures, requiring
12 MiB free on mounted metadata. Old V3/V4 namespaces remain untouched.
An OEM dump may still omit per-mode/group/VRR details. This diagnostic does
not repair the SurfaceFlinger or NFLOG boot blockers or prove Android boots.
Third-party NDK/VNDK notices accompany the native executable in licenses/.
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def old_sources():
    v3 = (ROOT / 'tools/bootdiag/bootdiag.sh').read_bytes()
    v4 = (ROOT / 'tools/bootdiag_v4/runtime.sh').read_bytes()
    rc = (ROOT / 'tools/bootdiag/init.rc').read_bytes()
    if sha(v3) != V3_SH_SHA or sha(v4) != V4_SH_SHA or sha(rc) != V3_RC_SHA:
        raise ValueError('Exact reviewed diagnostic V3/V4 bytes differ')
    return v3, v4


def render_runtime(probe_sha):
    if not re.fullmatch(r'[0-9a-f]{64}', probe_sha):
        raise ValueError('Expected SHA256 for versioned native helper')
    template = (ROOT / 'tools/bootdiag_v5/runtime-template.sh').read_text()
    runtime = template.replace('@@PROBE_SUFFIX@@', probe_sha[:12]).replace('@@PROBE_SHA@@', probe_sha)
    if '@@' in runtime:
        raise ValueError('Unresolved runtime substitution')
    return runtime.encode()


def render_upgrade(mode, probe_sha):
    old_sources()
    if mode not in ('enable', 'restore-v3', 'restore-v4'):
        raise ValueError('Unexpected mode')
    runtime = render_runtime(probe_sha)
    text = (ROOT / 'tools/bootdiag_v5/upgrade-template.sh').read_text()
    replacements = {'MODE': mode, 'PROBE_SHA': probe_sha, 'PROBE_SUFFIX': probe_sha[:12],
                    'V3_SH_SHA': V3_SH_SHA, 'V4_SH_SHA': V4_SH_SHA,
                    'V5_SH_SHA': sha(runtime), 'V3_RC_SHA': V3_RC_SHA, 'VENDOR_SHA': VENDOR_SHA}
    for key, value in replacements.items():
        text = text.replace('@@' + key + '@@', value)
    if '@@' in text:
        raise ValueError('Unresolved installer substitution')
    return text.encode()


def validate_probe(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Expected regular probe build-evidence directory')
    report_path = directory / 'summary.json'
    binary_path = directory / native.BINARY_NAME
    for path, limit in ((report_path, 1024 * 1024), (binary_path, 1024 * 1024)):
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
            raise ValueError('Missing/oversized probe evidence input: ' + path.name)
    report = json.loads(report_path.read_bytes())
    if report.get('status') != 'COMPILED_AND_ELF_INSPECTED_NOT_PHONE_TESTED':
        raise ValueError('Native client did not pass actual compile/ELF checks')
    if report.get('vndk_commit') != native.VNDK_COMMIT or report.get('vndk_repository') != native.VNDK_REPO:
        raise ValueError('Native VNDK input identity differs')
    if report.get('ndk', {}).get('sha256') != native.NDK_SHA256:
        raise ValueError('Native NDK input identity differs')
    if report.get('source_sha256') != sha((ROOT / 'tools/display_probe/composer_dump.cpp').read_bytes()):
        raise ValueError('Native client source differs from actual build evidence')
    if report.get('locale_compat_sha256') != sha((ROOT / 'tools/display_probe/platform_locale_compat.h').read_bytes()):
        raise ValueError('Native locale compatibility source differs')
    binary = binary_path.read_bytes()
    if report.get('output', {}).get('sha256') != sha(binary) or report['output'].get('bytes') != len(binary):
        raise ValueError('Native output hash/size differs from build evidence')
    if len(binary) < 64 or binary[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<HH', binary, 16) != (3, 183):
        raise ValueError('Native output is not expected ARM64 ELF64 PIE')
    elf = report.get('elf', {})
    if set(elf.get('needed', [])) != native.ALLOWED_NEEDED or elf.get('interpreter') != '/system/bin/linker64' or elf.get('platform_libcxx_namespace') != 'std::__1' or elf.get('pie') is not True:
        raise ValueError('Reviewed probe ELF ABI/dependency metadata differs')
    entries = report.get('notices', {})
    if set(entries) != {'licenses/' + name for name in NOTICE_NAMES}:
        raise ValueError('Actual native third-party notice set absent/differs')
    if (directory / 'licenses').is_symlink():
        raise ValueError('Symlinked notice directory')
    notices = {}
    for name, record in entries.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 6 * 1024 * 1024:
            raise ValueError('Native notice missing/oversized: ' + name)
        data = path.read_bytes()
        data.decode('utf-8')
        if record.get('sha256') != sha(data) or record.get('bytes') != len(data):
            raise ValueError('Native notice hash/size differs: ' + name)
        notices[name] = data
    return binary, report, notices


def write_archive(path, members):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, (data, mode_bits) in members.items():
            info = zipfile.ZipInfo(name, (2026, 11, 11, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100000 | mode_bits) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError('Diagnostic archive CRC differs')
    path.with_name(path.name + '.sha256').write_text(sha(path.read_bytes()) + '  ' + path.name + '\n')
    print(path.name, path.stat().st_size, sha(path.read_bytes()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-build', type=Path, required=True,
                        help='Actual successful build_probe.py evidence, including licenses/')
    parser.add_argument('--output', type=Path, default=ROOT / 'delivery/Bootdiag-V5')
    args = parser.parse_args()
    binary, report, notices = validate_probe(args.probe_build)
    collector = (ROOT / 'tools/bootdiag_v5/collect-template.sh').read_bytes()
    if b'@@' in collector:
        raise ValueError('Collector has unresolved template variables')
    v3, v4 = old_sources()
    probe_sha = sha(binary)
    v5 = render_runtime(probe_sha)
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {'purpose': 'EXPERIMENTAL_DIAGNOSTIC_NOT_ROM_OR_BOOT_REPAIR',
                'native_probe_sha256': probe_sha, 'native_probe_bytes': len(binary),
                'native_probe_vendor_path': '/vendor/bin/r8q-composer-dump-' + probe_sha[:12],
                'runtime_v5_sha256': sha(v5), 'init_rc_unchanged_sha256': V3_RC_SHA,
                'new_capture_namespace': '/metadata/r8q-bootdiag-v5',
                'phone_execution_confirmed': False, 'native_build': report}
    for mode in ('enable', 'restore-v4', 'restore-v3'):
        path = args.output / ('R8Q-BOOTDIAG-V5-' + mode.upper() + '.zip')
        members = {
            'META-INF/com/google/android/update-binary': (render_upgrade(mode, probe_sha), 0o755),
            'META-INF/com/google/android/updater-script': (b'# Diagnostic addon only.\n', 0o644),
            'payload/runtime-v3.sh': (v3, 0o755), 'payload/runtime-v4.sh': (v4, 0o755),
            'payload/runtime-v5.sh': (v5, 0o755), 'payload/composer-dump': (binary, 0o755),
            'README-ENGLISH.txt': (README.encode(), 0o644),
            'MANIFEST.json': ((json.dumps(manifest, indent=2) + '\n').encode(), 0o644),
            'LICENSE.txt': ((ROOT / 'LICENSE').read_bytes(), 0o644),
            **{name: (data, 0o644) for name, data in notices.items()},
        }
        write_archive(path, members)
    write_archive(args.output / 'R8Q-BOOTDIAG-V5-COLLECT-ONLY.zip', {
        'META-INF/com/google/android/update-binary': (collector, 0o755),
        'META-INF/com/google/android/updater-script': (b'# Read-only diagnostic log collection.\n', 0o644),
        'README-ENGLISH.txt': (README.encode(), 0o644),
        'LICENSE.txt': ((ROOT / 'LICENSE').read_bytes(), 0o644),
    })
    (args.output / 'README-ENGLISH.txt').write_text(README)


if __name__ == '__main__':
    main()
