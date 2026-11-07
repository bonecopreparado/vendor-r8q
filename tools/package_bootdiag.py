"""Package a small, reversible diagnostic addon; it is not a ROM or boot fix."""
from pathlib import Path
import hashlib,json,zipfile,argparse
ROOT=Path(__file__).resolve().parents[1]
README=r"""R8Q ANDROID BOOT DIAGNOSTICS v3 - TEMPORARY ADDON

This is NOT a ROM or a boot fix. ENABLE adds only these two vendor files:
 /vendor/bin/r8q-bootdiag.sh
 /vendor/etc/init/r8q-bootdiag.rc

v3 saves filtered Android logcat and bounded process snapshots in a fresh,
private directory under /metadata/r8q-bootdiag-v3/capture.XXXXXX/boot.log.
The old kernel-ring mirror did not appear in this device's last_kmsg. v3 does
not rely on it. This does not establish why the old messages were missing.
The running logger requires the existing metadata mount to be ext4, writable,
and sourced from the metadata partition named in the P1 fstab. It never mounts,
remounts or formats metadata and never opens existing Android key files.

Limits: 120 seconds of main/system/crash logcat after its socket appears,
1500 lines at 900 bytes each, plus two snapshots at 20 and 60 seconds.
Each capture stays below 2 MiB, at most four capture directories are allowed,
and at least 12 MiB free must be available before capture starts. Files are
0600 in private 0700 directories. Existing evidence is never overwritten or
deleted. Kernel logcat is excluded; vdc password arguments are omitted.

1. Keep your current EROFS-COMPAT ROM. Do not Format Data again.
2. In OrangeFox, Mount > Vendor.
3. Install R8Q-BOOTDIAG-V3-REMOVE.zip to remove v1/v2/partial diagnostics.
4. Install R8Q-BOOTDIAG-V3-ENABLE.zip. Keep it enabled during the boot test.
   The screen must say R8Q diagnostic logging v3 enabled.
5. Reboot System. If it remains stuck, allow 3 minutes, then return directly
   to OrangeFox. The addon diagnoses this attempt; it does not repair boot.
6. In recovery, mount Metadata using its existing filesystem. Do NOT format it.
   With a computer, run these commands from platform-tools:

   mkdir logs-v3
   adb shell mount /metadata
   adb pull /metadata/r8q-bootdiag-v3 logs-v3\r8q-bootdiag-v3
   adb pull /sys/fs/pstore logs-v3\pstore
   adb shell "cat /proc/last_kmsg > /tmp/r8q-last_kmsg"
   adb pull /tmp/r8q-last_kmsg logs-v3\last_kmsg
   adb pull /tmp/recovery.log logs-v3\recovery.log

   An already-mounted message is harmless if the subsequent pull succeeds.
   Send logs-v3 privately; these diagnostic files are not for public releases.
   If metadata logs are absent, save recovery.log and check the two installed
   addon files after mounting Vendor; do not bypass installation checks.
7. After collection, Mount > Vendor and install V3 REMOVE to stop diagnostics.
   REMOVE preserves saved metadata logs. A full ROM reflash replaces vendor.

The ZIPs are intentionally small; keep them compressed. SHA256 sidecars and
build attestations are published with the ready ZIPs. Verify the ZIP digest.
No boot image, USB authentication, encryption check or user data is changed.
"""
def digest(b):return hashlib.sha256(b).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'delivery/Bootdiag')
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    rc=(ROOT/'tools/bootdiag/init.rc').read_bytes();sh=(ROOT/'tools/bootdiag/bootdiag.sh').read_bytes()
    reference=json.loads((ROOT/'tools/bootdiag/reference.json').read_text())['vendor_init_qcom_sha256']
    base=(ROOT/'tools/bootdiag/installer.sh').read_text()
    old=json.loads((ROOT/'tools/bootdiag/reference.json').read_text())['previous_payload_sha256']
    assert digest((ROOT/'tools/bootdiag/legacy-v1/init.rc').read_bytes())==old['rc']
    assert digest((ROOT/'tools/bootdiag/legacy-v1/bootdiag.sh').read_bytes())==old['sh']
    v2=json.loads((ROOT/'tools/bootdiag/reference.json').read_text())['v2_payload_sha256']
    assert digest((ROOT/'tools/bootdiag/legacy-v2/init.rc').read_bytes())==v2['rc']
    assert digest((ROOT/'tools/bootdiag/legacy-v2/bootdiag.sh').read_bytes())==v2['sh']
    for mode in ('enable','remove'):
        script=base.replace('@@MODE@@',mode).replace('@@REFERENCE_SHA@@',reference).replace('@@RC_SHA@@',digest(rc)).replace('@@SH_SHA@@',digest(sh)).replace('@@OLD_RC_SHA@@',old['rc']).replace('@@OLD_SH_SHA@@',old['sh']).replace('@@V2_RC_SHA@@',v2['rc']).replace('@@V2_SH_SHA@@',v2['sh'])
        assert '@@' not in script and script.startswith('#!/sbin/sh\n')
        path=a.output/('R8Q-BOOTDIAG-V3-'+mode.upper()+'.zip')
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for name,data,bits in [('META-INF/com/google/android/update-binary',script.encode(),0o755),
                                  ('META-INF/com/google/android/updater-script',b'# Temporary diagnostic addon.\n',0o644),
                                  ('payload/init.rc',rc,0o644),('payload/bootdiag.sh',sh,0o755),
                                  ('README-ENGLISH.txt',README.encode(),0o644),('LICENSE.txt',(ROOT/'LICENSE').read_bytes(),0o644)]:
                info=zipfile.ZipInfo(name,(2026,11,7,0,0,0));info.create_system=3
                info.external_attr=(0o100000|bits)<<16;info.compress_type=zipfile.ZIP_DEFLATED
                z.writestr(info,data)
        path.with_name(path.name+'.sha256').write_text(digest(path.read_bytes())+'  '+path.name+'\n')
        print(path.name,path.stat().st_size,digest(path.read_bytes()))
    (a.output/'README-ENGLISH.txt').write_text(README)
if __name__=='__main__':main()
