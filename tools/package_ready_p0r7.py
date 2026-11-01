"""Create the actual ready-to-flash small ZIP, not a Windows preparation kit."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import zipfile

ROOT = Path(os.environ.get('R8Q_PROJECT_ROOT', Path(__file__).resolve().parents[1]))
READY = ROOT/'delivery/Ready-P0r7';READY.mkdir(exist_ok=True)
base = ROOT/'delivery/Revisao-P0r7-Windows/p0r7-assets/installer-template.sh'
if hashlib.sha256(base.read_bytes()).hexdigest()!='690280161dfa294add407fcb6fa1e853c531b24dc52a38081ba6bcb022aa0ea6':
    raise ValueError('The reviewed P0r7 template changed')
template=base.read_text()
old='''PAYLOAD_DIR="${zip_real%/*}/payloads"
[ -d "$PAYLOAD_DIR" ] && [ ! -L "$PAYLOAD_DIR" ] || abort "Pasta payloads ausente ou link; copie a pasta P0r7 inteira. Nada foi gravado."
'''
new='''zip_dir="${zip_real%/*}"
if [ -d "$zip_dir/payloads" ] && [ ! -L "$zip_dir/payloads" ]; then
    PAYLOAD_DIR="$zip_dir/payloads"
elif [ -f "$zip_dir/super-000.gz" ]; then
    PAYLOAD_DIR="$zip_dir"
else
    abort "Payloads not found. Put this ZIP next to the payloads folder or inside it. Nothing was written."
fi
ui_print "READY installer: using payload files in $PAYLOAD_DIR"
'''
if template.count(old)!=1:raise ValueError('Payload-location section changed')
template=template.replace(old,new)
template=template.replace('HyperOS4 -> R8Q P0r7 EXPERIMENTAL / sem teste de boot',
                          'HyperOS4 -> R8Q P0r7-ready1 EXPERIMENTAL / boot not confirmed')
(READY/'installer-template-ready.sh').write_text(template)
subprocess.run(['bash','-n',str(READY/'installer-template-ready.sh')],check=True)

metadata=json.loads((READY/'payload-identities.json').read_text())
trusted=json.loads((ROOT/'delivery/Revisao-P0r5-Windows/p0r5-assets/chunks.json').read_text())
if metadata['images']!=trusted['images'] or len(metadata['chunks'])!=22:
    raise ValueError('Ready metadata does not match original P0')
for row,pinned in zip(metadata['chunks'],trusted['chunks']):
    if any(row.get(key)!=value for key,value in pinned.items()):raise ValueError('Chunk raw identity/order changed')
keys=('part','name','bytes','sha256','compressed_bytes','compressed_sha256','offset','readback_sha256')
rows='\n'.join(' '.join(str(row[k]) for k in keys) for row in metadata['chunks'])
installer=template.replace('@@PAYLOAD_ROWS@@',rows).encode()
manifest=dict(metadata,installer_sha256=hashlib.sha256(installer).hexdigest(),
              delivery='Already-generated recovery installer; reuse original 22 gzip files; no Windows preparation')
instructions='''HyperOS4 R8Q P0r7-ready1 - PHONE-ONLY INSTALLATION

This ZIP is the READY recovery installer. No Windows, Python, CMD or installer
creation is needed. Keep the 22 .gz files already copied for P0r5/P0r6.

1. Download HyperOS4-R8Q-P0r7-READY.zip.
2. Move this ZIP next to the existing payloads folder OR directly inside it.
3. In OrangeFox Files, select HyperOS4-R8Q-P0r7-READY.zip and swipe to install.
   Select the local file in that folder; ADB sideload cannot find adjacent data.
4. Wait for all checks and writes to complete. If it succeeds, reboot back to
   Recovery first and save/send recovery.log before attempting the system boot.
5. If it fails, save/send recovery.log. If writing started, restore your working
   ROM or backup before booting the system.

The ZIP is small because the ROM images are in the 22 external .gz files.
Leave those .gz files compressed and keep their original names. The installer
checks every compressed SHA, gzip CRC and raw SHA before any partition write.
This reuses the original P0r5/P0r6 gzip encoding from the shipped Windows kit.
It includes the mksh arithmetic fixes already reviewed in P0r7.

This is still an experimental installation test. The ROM images are unchanged;
SELinux and VINTF work remains and boot has not been confirmed. This ZIP does
not format userdata, write vbmeta, recovery, modem, bootloader or EFS.
'''
(READY/'TESTER-ENGLISH.txt').write_text(instructions)
out=ROOT/'output/HyperOS4-R8Q-P0r7-READY.zip';out.parent.mkdir(exist_ok=True)
members={'META-INF/com/google/android/update-binary':installer,
         'META-INF/com/google/android/updater-script':b'# Ready P0r7 shell installer\n',
         'P0-MANIFEST.json':(json.dumps(manifest,indent=2)+'\n').encode(),
         'README-TESTER.txt':instructions.encode()}
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=False) as archive:
    for name,data in members.items():
        info=zipfile.ZipInfo(name,date_time=(2026,11,1,0,0,0));info.create_system=3
        info.external_attr=(0o100755 if name.endswith('update-binary') else 0o100644)<<16
        info.compress_type=zipfile.ZIP_DEFLATED
        archive.writestr(info,data,compresslevel=6)
with zipfile.ZipFile(out) as archive:
    if archive.testzip() is not None or set(archive.namelist())!=set(members):raise ValueError('Ready ZIP CRC/members failed')
    if archive.getinfo('META-INF/com/google/android/update-binary').external_attr>>16!=0o100755:
        raise ValueError('Installer executable mode incorrect')
    for name,data in members.items():
        if archive.read(name)!=data:raise ValueError('Ready ZIP content changed')
sha=hashlib.sha256(out.read_bytes()).hexdigest()
(ROOT/'output/HyperOS4-R8Q-P0r7-READY.zip.sha256').write_text(sha+'  '+out.name+'\n')
print(json.dumps(dict(file=str(out),bytes=out.stat().st_size,sha256=sha,installer_sha256=manifest['installer_sha256']),indent=2))
