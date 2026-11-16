"""Package a pinned, device-stock IPA authentication fix for the installed P1r4."""
from pathlib import Path
import argparse
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'R8Q-P1r4-IPA-STOCK-FIX-EXPERIMENTAL.zip'
README = '''R8Q P1r4 SAMSUNG IPA STOCK FIX - EXPERIMENTAL

This small addon requires the already installed HyperOS4 R8Q P1r4 ROM.
It is not a complete ROM. Do not extract the ZIP before installing it.

Four retained P1r4 boots fail at IPA PAS_INIT_IMAGE and ipa_assert.
The reviewed Vendor IPA uses a generic SecTools certificate chain, while
the same device's APNHLOS image uses Samsung Attestation CA / Samsung Root CA.
The executable IPA code segments match. Authentication metadata and the
signatures differ. Offline verification of the stock MBN signature and all
three Samsung certificate signatures passed. Boot success is NOT confirmed.

The installer reads APNHLOS through a private read-only mount, verifies its
exact reviewed IPA hashes, and copies its signed b01 and mdt files into Vendor.
It updates the corresponding authentication segment in Vendor's existing ELF.
It preserves original SELinux labels, ownership and modes, creates a verified
original-file backup in /vendor/firmware/.r8q-ipa-p1r4-backup, and verifies
the three installed files. Detected failures during replacement trigger
restoration from that backup. A power interruption can require recovery.

Only the three Vendor IPA files change. Kernel/SUSFS and all other firmware,
Data, Metadata, EFS, Persist, bootloader and APNHLOS contents stay unchanged.
The ZIP contains scripts and documentation, no redistributed firmware blobs.
Different stock IPA versions are refused; never bypass the hash guard.
The latest capture reports G781BXXSIHYJ2, despite older G780G references.
Acceptance requires r8q, a G780G/G781B bootloader family, the reviewed Vendor,
matching code, and the exact signed IPA already present on the device.

INSTALL (TWRP or OrangeFox)
1. Download this ZIP and compare its SHA256 with the supplied checksum.
2. In recovery, mount Vendor. Charge to 50% or connect a charger.
3. Install R8Q-P1r4-IPA-STOCK-FIX-EXPERIMENTAL.zip directly.
4. Require: "R8Q Samsung IPA stock fix applied and SHA256 verified."
   If it aborts, save /tmp/recovery.log and send the exact message.
5. Reboot RECOVERY first to discard old partition mounts, then reboot SYSTEM.
6. If stuck/restarting after about 2 minutes, return to recovery and collect
   last_kmsg, recovery.log, and any bootdiag-v6 captures with the existing
   ADB commands. No Format Data is needed for this experiment.

Re-running the fix accepts an already corrected, verified state.
The full P1r4 ROM reflash restores its original generic Vendor files.
File hash readback does not establish successful hardware boot.
'''


def package(output):
    output.mkdir(parents=True, exist_ok=True)
    path = output / NAME
    script = (ROOT/'tools/ipa_stock_fix/installer.sh').read_bytes()
    entries = [
        ('META-INF/com/google/android/update-binary', script, 0o755),
        ('META-INF/com/google/android/updater-script', b'# R8Q device-stock IPA fix.\n', 0o644),
        ('README-ENGLISH.txt', README.encode(), 0o644),
        ('LICENSE.txt', (ROOT/'LICENSE').read_bytes(), 0o644),
    ]
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name, (2026, 11, 16, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(path.name+'.sha256').write_text(digest+'  '+path.name+'\n')
    (output/'README-ENGLISH.txt').write_text(README)
    return path, digest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    path, digest = package(a.output)
    print(path.name, path.stat().st_size, digest)
