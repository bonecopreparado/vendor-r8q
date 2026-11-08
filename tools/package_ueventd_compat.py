"""Package a reversible, pinned canonical import bridge for the current P1 ROM."""
from pathlib import Path
import argparse,hashlib,zipfile
ROOT=Path(__file__).resolve().parents[1]
LEGACY_SHA='8debe752a74eb73382de872638462e6869f50041d75bba9f66aa89e2e2530f12'
VENDOR_SHA='9971fef6dfa6951ec593bd82351203deb71e6185a4eea5354fe2fef3912114ea'
SHA=lambda b:hashlib.sha256(b).hexdigest()
README=r"""R8Q UEVENTD COMPATIBILITY BRIDGE - EXPERIMENTAL

The latest private Android capture shows Keymaster unable to open /dev/qseecom,
EACCES on /dev/spcom and /dev/ion, and vdc waiting in cryptfs encryptFstab.
The reviewed vendor rules already specify the intended node permissions but
reside at /vendor/ueventd.rc, a legacy path. Android's modern canonical path
is /vendor/etc/ueventd.rc. A donor first-API property can affect legacy loading;
the supplied logs do not prove that property's Android value or the node modes.

This candidate adds ONLY /vendor/etc/ueventd.rc containing an import of the
unchanged, SHA256-pinned /vendor/ueventd.rc. It neither invents node permissions
nor changes HAL users/groups, encryption, kernel, keys or data. It is a test
of a configuration-loading failure, not a confirmed boot repair. No ROM image
or partition is reformatted/flashed by these small ZIPs.

Use only with the current EROFS-COMPAT P1r2 ROM. Keep BOOTDIAG V3 enabled.
1. Verify ZIP SHA256 against the release sidecar.
2. In OrangeFox > Mount, select Vendor and System. System stays read-only.
3. Install R8Q-UEVENTD-COMPAT-ENABLE.zip without extracting it.
4. The installer must say R8Q ueventd compatibility bridge enabled.
   It checks that your ACTUAL mounted System imports the canonical Vendor
   configuration before changing any file. If it aborts, save recovery.log;
   do not bypass checks or Format Data.
5. Reboot System once; if stuck, allow 3 minutes and return to OrangeFox.
6. Collect the new BOOTDIAG V3 directory, last_kmsg and recovery.log using the
   same logs-v3 commands. Send privately. Existing captures are preserved;
   choose the newest capture directory when checking the result.
7. To reverse only this experiment, Mount Vendor and install the REMOVE ZIP.
   It deletes only this exact bridge, leaving the original vendor rules and
   diagnostic addon intact. Other pre-existing canonical files are refused.

The package guards device r8q, mounted logical Vendor/ext4, exact original
vendor rule and init hashes, the real mounted logical System/EROFS import,
the payload hash, file labels and pre-existing files. Remounts restore the
original Vendor read-only mode. A full ROM reflash removes this addon.
"""
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'delivery/Ueventd-Compat');args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    payload=(ROOT/'tools/ueventd_compat/ueventd.rc').read_bytes()
    base=(ROOT/'tools/ueventd_compat/installer.sh').read_text()
    for mode in ('enable','remove'):
        script=base.replace('@@MODE@@',mode).replace('@@LEGACY_SHA@@',LEGACY_SHA).replace('@@VENDOR_SHA@@',VENDOR_SHA).replace('@@PAYLOAD_SHA@@',SHA(payload))
        assert '@@' not in script
        path=args.output/('R8Q-UEVENTD-COMPAT-'+mode.upper()+'.zip')
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for name,data,modebits in [('META-INF/com/google/android/update-binary',script.encode(),0o755),('META-INF/com/google/android/updater-script',b'# R8Q ueventd import bridge.\n',0o644),('payload/ueventd.rc',payload,0o644),('README-ENGLISH.txt',README.encode(),0o644),('LICENSE.txt',(ROOT/'LICENSE').read_bytes(),0o644)]:
                info=zipfile.ZipInfo(name,(2026,11,7,0,0,0));info.create_system=3;info.external_attr=(0o100000|modebits)<<16;info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,data)
        path.with_name(path.name+'.sha256').write_text(SHA(path.read_bytes())+'  '+path.name+'\n')
        print(path.name,path.stat().st_size,SHA(path.read_bytes()))
    (args.output/'README-ENGLISH.txt').write_text(README)
if __name__=='__main__':main()
