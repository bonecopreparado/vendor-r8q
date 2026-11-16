"""Build the cumulative P1r4 firmware/SELinux metadata repair addon."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'R8Q-P1r4-SECURITY-R2-EXPERIMENTAL.zip'
README = '''R8Q P1r4 SECURITY R2 - CUMULATIVE EXPERIMENTAL ADDON

For the already installed HyperOS4 R8Q P1r4 ROM. Keep this ZIP compressed.
It includes the first IPA correction and does not require installing R1 first.
Kernel and SUSFS stay unchanged. Hardware boot is not confirmed.

WHAT THE NEW DEVICE LOGS ESTABLISH
After the first fix: "IPA FW loaded successfully" on three retained boots.
The earlier IPA assertion is absent from these new attempts. IPA UC then
fails authentication. Keymaster/Gatekeeper abort and Keystore cannot obtain
the mandatory TEE. Android init commands a reboot near 31 seconds.
The logs also contain two lmkd camera-optimization SIGSEGVs without a full
stack; their cause and persistence after this fix remain unconfirmed.

The supplied file metadata shows /vendor incorrectly labeled vendor_apex_file,
and Vendor context databases labeled generic vendor_configs_file. The HAL
context database needs hwservice_contexts_file. Correct entries exist in the
file but runtime lookups return default_android_hwservice with denied access.
This addon corrects the root and ten exact context/policy file labels rather
than adding broad allow rules or disabling SELinux.

It also reads the device's APNHLOS through a temporary read-only mount, checks
the exact reviewed stock hashes, installs the matching Samsung-signed IPA
and IPA UC split files and constructs their matching ELF files. The UC code
differs from Vendor, so all its split files are replaced coherently.
The ZIP contains no redistributed firmware binaries.

PREFLIGHT AND RECOVERY
Only r8q with a G780G/G781B bootloader family, the reviewed P1 Vendor init,
known firmware hashes, exact context file contents and matching device-stock
IPA hashes are accepted. Different stock versions abort before writable
Vendor remount. Unknown labels/content or ambiguous Vendor mappings abort.
At least 2 MiB free in Vendor and >=50% battery or a charging state are required.

The original file bytes, hashes and labels are backed up inside Vendor at
firmware/.r8q-security-r2-backup before changes. Detected activation, label
or sync failures trigger restoration of the pre-installation files/labels.
Power interruption can still require recovery. Re-running preserves the
original backup and accepts an already-correct state without more writes.
Original mount modes are restored, and private mounts are released.

Only the reviewed Vendor firmware files and SELinux file labels change.
No policy allow rules, kernel/SUSFS, Data, Metadata, EFS, Persist, bootloader
or APNHLOS contents are changed. Do not Format Data for this experiment.

INSTALL
1. Compare ZIP SHA256 with its release checksum before using it.
2. Boot TWRP or OrangeFox. Charge to 50% or connect a charger.
3. Install R8Q-P1r4-SECURITY-R2-EXPERIMENTAL.zip without extracting it.
   The installer can mount the identified logical Vendor itself if needed.
4. Require: "R8Q security R2 applied: Samsung IPA and Vendor labels verified."
   On failure send /tmp/recovery.log; do not bypass guards.
5. Reboot Recovery first, then System once.
6. If stuck/restarting, collect fresh last_kmsg, recovery.log and pstore.
   Existing diagnostic captures can be collected too. A file hash check or
   passing CI does not establish successful Android boot.
'''


def profile():
    result = json.loads((ROOT/'tools/vendor_security/profile.json').read_text())
    if result.get('schema_version') != 1:
        raise ValueError('Unknown security profile schema')
    expected = {'ipa_fws.b01', 'ipa_fws.mdt', 'ipa_fws.elf', 'ipa_uc.b00',
                'ipa_uc.b01', 'ipa_uc.b02', 'ipa_uc.mdt', 'ipa_uc.elf'}
    if {r['name'] for r in result['data']} != expected or len(result['data']) != 8:
        raise ValueError('Unexpected firmware targets')
    stock_names = expected-{'ipa_fws.elf', 'ipa_uc.elf'}
    if {r['name'] for r in result['stock']} != stock_names or len(result['stock']) != 6:
        raise ValueError('Unexpected device-stock inputs')
    immutable_names = {'ipa_fws.b00', 'ipa_fws.b02', 'ipa_fws.b03', 'ipa_fws.b04'}
    if {r['name'] for r in result['immutable']} != immutable_names or len(result['immutable']) != 4:
        raise ValueError('Unexpected unchanged firmware targets')
    types = {'.': 'vendor_file', 'vendor_hwservice_contexts': 'hwservice_contexts_file',
             'vendor_file_contexts': 'file_contexts_file', 'vendor_property_contexts': 'property_contexts_file',
             'vendor_seapp_contexts': 'seapp_contexts_file', 'vendor_service_contexts': 'vendor_service_contexts_file',
             'vndservice_contexts': 'vndservice_contexts_file', 'vendor_sepolicy.cil': 'sepolicy_file',
             'plat_pub_versioned.cil': 'sepolicy_file', 'plat_sepolicy_vers.txt': 'sepolicy_file',
             'vendor_mac_permissions.xml': 'mac_perms_file'}
    expected_labels = {(n if n == '.' else 'etc/selinux/'+n): 'u:object_r:'+t+':s0' for n,t in types.items()}
    names = set()
    for row in result['labels']:
        path = row['path']
        if path in names or (path != '.' and not re.fullmatch(r'etc/selinux/[A-Za-z0-9_.]+', path)):
            raise ValueError('Unexpected metadata target')
        names.add(path)
        if not re.fullmatch(r'u:object_r:[a-z0-9_]+:s0', row['label']):
            raise ValueError('Invalid target label')
        if row['label'] != expected_labels.get(path):
            raise ValueError('Unreviewed metadata path or target type')
        if path == '.':
            if row['sha256'] is not None or row['label'] != 'u:object_r:vendor_file:s0':
                raise ValueError('Unexpected Vendor root rule')
    if len(names) != 11 or '.' not in names:
        raise ValueError('Missing metadata targets')
    digests = [result['init_sha256']]
    digests += [r[k] for r in result['data'] for k in ['old_sha256', 'new_sha256']]
    digests += [r['sha256'] for k in ['stock', 'immutable'] for r in result[k]]
    digests += [r['sha256'] for r in result['labels'] if r['path'] != '.']
    if any(not re.fullmatch(r'[0-9a-f]{64}', d) for d in digests):
        raise ValueError('Invalid profile digest')
    return result


def render():
    p = profile()
    s = (ROOT/'tools/vendor_security/installer.sh').read_text()
    parts = {
        'DATA': '\n'.join(f"{r['name']} {r['old_sha256']} {r['new_sha256']}" for r in p['data']),
        'STOCK': '\n'.join(f"{r['name']} {r['sha256']}" for r in p['stock']),
        'IMMUTABLE': '\n'.join(f"{r['name']} {r['sha256']}" for r in p['immutable']),
        'LABELS': '\n'.join(f"{r['path']} {r['sha256'] or '-'} {r['label']}" for r in p['labels']),
        'INIT_SHA': p['init_sha256'],
    }
    for key, value in parts.items():
        marker = '@@'+key+'@@'
        if s.count(marker) != 1:
            raise ValueError('Installer marker differs: '+key)
        s = s.replace(marker, value)
    if '@@' in s:
        raise ValueError('Unexpanded installer marker')
    return s


def package(output):
    output.mkdir(parents=True, exist_ok=True)
    path = output/NAME
    entries = [('META-INF/com/google/android/update-binary', render().encode(), 0o755),
               ('META-INF/com/google/android/updater-script', b'# Cumulative R8Q security metadata repair.\n', 0o644),
               ('README-ENGLISH.txt', README.encode(), 0o644),
               ('REPAIR-PROFILE.json', (ROOT/'tools/vendor_security/profile.json').read_bytes(), 0o644),
               ('LICENSE.txt', (ROOT/'LICENSE').read_bytes(), 0o644)]
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    path, digest = package(args.output)
    print(path.name, path.stat().st_size, digest)
