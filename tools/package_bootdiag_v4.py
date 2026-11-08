"""Package a guarded one-file v3->v4 capture upgrade and exact v3 restoration."""
from pathlib import Path
import argparse,hashlib,zipfile
ROOT=Path(__file__).resolve().parents[1]
SHA=lambda b:hashlib.sha256(b).hexdigest()
V3_RC_SHA='f87c5e2be6ce97d93d2aba1098495f3b2f33479a98878b0adab5be888a3fb447'
V3_SH_SHA='6f4bbbd50c76646d39da99a0c149de8dba260072bc6317ccdcb04d5707f1154d'
VENDOR_SHA='9971fef6dfa6951ec593bd82351203deb71e6185a4eea5354fe2fef3912114ea'
README=r"""R8Q BOOTDIAG v4 - DISPLAY HAL / NFLOG EVIDENCE

This is a diagnostic upgrade, not a ROM or a boot repair. It requires the
exact v3 diagnostic addon already installed on the reviewed P1 vendor.
ENABLE atomically replaces only /vendor/bin/r8q-bootdiag.sh; the existing
on-init rc is verified and unchanged. Kernel, display properties, firewall,
encryption, keys and existing captured logs are unchanged.

v4 records selected Android logcat, two bounded composer HAL probes using
lshal, selected display properties/sysfs, and the ANDROID kernel config,
module list and netfilter target lists. It does not clear logs, restart HALs,
mount/format partitions at runtime, change properties or download programs.
Output is private under /metadata/r8q-bootdiag-v4/capture.XXXXXX; v3 captures
remain intact. The logger requires the already-mounted metadata ext4 device,
at least 12 MiB free, and at most three v4 capture directories. Each capture
is bounded below 2 MiB. Missing tools/timeouts are recorded, not treated as
proof that a HAL or feature is absent. HAL dumps may omit some mode fields.

1. Verify the ZIP SHA256 against its release sidecar.
2. Keep the installed ROM, ueventd bridge and existing v3 diagnostic setup.
3. In OrangeFox, Mount Vendor, then install R8Q-BOOTDIAG-V4-ENABLE.zip directly.
   It must say R8Q diagnostic logging v4 installed. No REMOVE is needed first.
4. Reboot System once. If stuck, allow about 2 minutes, then return directly
   to OrangeFox. Do not Format Data or erase old captures.
5. From Windows platform-tools, collect:

   mkdir logs-display
   adb shell mount /metadata
   adb pull /metadata/r8q-bootdiag-v4 logs-display\r8q-bootdiag-v4
   adb shell "cat /proc/last_kmsg > /tmp/r8q-last-display"
   adb pull /tmp/r8q-last-display logs-display\last_kmsg
   adb pull /tmp/recovery.log logs-display\recovery.log
   dir /s logs-display

   Confirm files exist, then ZIP logs-display and send it privately.
   If a pull fails, send its error text rather than an empty ZIP.
6. RESTORE-V3 reverses only this upgrade, restoring the exact older runtime
   while preserving captured files. It leaves diagnostic v3 enabled. To stop
   all diagnostics afterwards, use the original V3 REMOVE after restoration.

The current known blockers are SurfaceFlinger rejecting its reported display
modes and netd failing NFLOG rule initialization. Changing refresh thresholds
or bypassing libc mutex checks is not justified by the existing evidence.
No patched kernel image is included in these diagnostic ZIPs.
"""
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'delivery/Bootdiag-V4');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    rc=(ROOT/'tools/bootdiag/init.rc').read_bytes();v3=(ROOT/'tools/bootdiag/bootdiag.sh').read_bytes();v4=(ROOT/'tools/bootdiag_v4/runtime.sh').read_bytes()
    if SHA(rc)!=V3_RC_SHA or SHA(v3)!=V3_SH_SHA:raise ValueError('Reviewed v3 source bytes differ')
    base=(ROOT/'tools/bootdiag_v4/upgrade.sh').read_text()
    for mode,label in [('enable','ENABLE'),('restore','RESTORE-V3')]:
        script=base.replace('@@MODE@@',mode).replace('@@VENDOR_SHA@@',VENDOR_SHA).replace('@@V3_RC_SHA@@',V3_RC_SHA).replace('@@V3_SH_SHA@@',V3_SH_SHA).replace('@@V4_SH_SHA@@',SHA(v4))
        assert '@@' not in script
        path=a.output/('R8Q-BOOTDIAG-V4-'+label+'.zip')
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for n,data,bits in [('META-INF/com/google/android/update-binary',script.encode(),0o755),('META-INF/com/google/android/updater-script',b'# Diagnostic runtime upgrade only.\n',0o644),('payload/runtime-v4.sh',v4,0o755),('payload/runtime-v3.sh',v3,0o755),('README-ENGLISH.txt',README.encode(),0o644),('LICENSE.txt',(ROOT/'LICENSE').read_bytes(),0o644)]:
                info=zipfile.ZipInfo(n,(2026,11,7,0,0,0));info.create_system=3;info.external_attr=(0o100000|bits)<<16;info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,data)
        path.with_name(path.name+'.sha256').write_text(SHA(path.read_bytes())+'  '+path.name+'\n');print(path.name,path.stat().st_size,SHA(path.read_bytes()))
    (a.output/'README-ENGLISH.txt').write_text(README)
if __name__=='__main__':main()
