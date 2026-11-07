"""Package a small, reversible diagnostic addon; it is not a ROM or boot fix."""
from pathlib import Path
import hashlib,json,zipfile,argparse
ROOT=Path(__file__).resolve().parents[1]
README="""R8Q ANDROID BOOT DIAGNOSTICS - TEMPORARY ADDON

This is NOT a ROM or a boot fix. ENABLE adds only:
 /vendor/bin/r8q-bootdiag.sh
 /vendor/etc/init/r8q-bootdiag.rc

The addon mirrors selected Android logcat messages into the kernel ring for
120 seconds after logd starts (maximum 1500 lines, 900 bytes each). It excludes
the kernel logcat buffer to avoid feedback. It does not format, change keys,
disable crypto checks, modify USB authentication or write partition images.

1. Keep your existing EROFS-COMPAT ROM installed. Do not Format Data again.
2. In OrangeFox, Mount > Vendor. If not mounted, the ZIP aborts before changes.
3. Install R8Q-BOOTDIAG-ENABLE.zip. It pins the expected P1 vendor config hash.
4. Reboot System and leave this attempt on the logo for about 3 minutes.
5. Return directly to recovery and collect /proc/last_kmsg (or run the existing
   R8Q-BOOTLOG-COLLECTOR.zip). Send that evidence privately.
6. In recovery, Mount > Vendor, then install R8Q-BOOTDIAG-REMOVE.zip to remove
   the two exact addon files. A full ROM reflash also replaces vendor.

The diagnostic ZIPs are small on purpose. Keep each ZIP compressed.
If ENABLE fails, save recovery.log; do not bypass its checks.
Both ZIPs include SHA256 sidecars. Verify the ZIP digest before use.
"""
def digest(b):return hashlib.sha256(b).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'delivery/Bootdiag')
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    rc=(ROOT/'tools/bootdiag/init.rc').read_bytes();sh=(ROOT/'tools/bootdiag/bootdiag.sh').read_bytes()
    reference=json.loads((ROOT/'tools/bootdiag/reference.json').read_text())['vendor_init_qcom_sha256']
    base=(ROOT/'tools/bootdiag/installer.sh').read_text()
    for mode in ('enable','remove'):
        script=base.replace('@@MODE@@',mode).replace('@@REFERENCE_SHA@@',reference).replace('@@RC_SHA@@',digest(rc)).replace('@@SH_SHA@@',digest(sh))
        assert '@@' not in script and script.startswith('#!/sbin/sh\n')
        path=a.output/('R8Q-BOOTDIAG-'+mode.upper()+'.zip')
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
