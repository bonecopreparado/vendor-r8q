"""Build a complete recovery installer candidate, held for compatibility review."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'output'
OUT.mkdir(exist_ok=True)
subprocess.run([sys.executable, str(ROOT/'tools/prepare_p0r8_template.py')], check=True)
template = (ROOT/'delivery/Ready-P0r8/installer-template-ready.sh').read_bytes()
if hashlib.sha256(template).hexdigest() != '9a0ac40c6fb79b6347ca3ea14b0ff8a7deb4400f54499548ff345f86be7e110d':
    raise ValueError('Reviewed P0r8 template differs')
metadata = json.loads((ROOT/'delivery/Ready-P0r7/payload-identities.json').read_text())
trusted = json.loads((ROOT/'delivery/Revisao-P0r5-Windows/p0r5-assets/chunks.json').read_text())
if metadata['images'] != trusted['images'] or len(metadata['chunks']) != 22:
    raise ValueError('Original P0 identity differs')
for row, pinned in zip(metadata['chunks'], trusted['chunks']):
    if any(row.get(k) != v for k,v in pinned.items()):
        raise ValueError('Original raw chunk identity/order differs')
    if type(row.get('compressed_bytes')) is not int or not 0 < row['compressed_bytes'] <= 1024**3:
        raise ValueError('Compressed payload size is not a bounded integer')
    if not isinstance(row.get('compressed_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',row['compressed_sha256']):
        raise ValueError('Compressed payload SHA256 is not canonical')
keys = ('part','name','bytes','sha256','compressed_bytes','compressed_sha256','offset','readback_sha256')
rows = '\n'.join(' '.join(str(row[k]) for k in keys) for row in metadata['chunks'])
if template.count(b'@@PAYLOAD_ROWS@@') != 1:
    raise ValueError('Payload table placeholder differs')
installer = template.replace(b'@@PAYLOAD_ROWS@@', rows.encode())
status = json.loads((ROOT/'ci-r8q/inputs/release-readiness.json').read_text())
if status.get('boot_ready') is not False or status.get('rom_images_changed') is not False:
    raise ValueError('Unchanged P0 candidate cannot declare boot readiness or new images')
instructions = '''P0r8 INSTALLER CANDIDATE - HOLD / BOOT NOT VALIDATED

Do not start a device test with this candidate yet. The installer has battery
guards and regression coverage, but the P0 ROM images still have unresolved
compatibility work. A successful CI job does not authorize a flash test.

When a reviewed build is explicitly cleared for a device test:
1. Download its recovery ZIP, matching .sha256 file and attestation from the
   same GitHub Release. Do not select an audit/tools archive in OrangeFox.
2. On Android, use a file manager/hash utility that supports SHA256; calculate
   the ZIP hash and compare ALL 64 hexadecimal characters with the release's
   .sha256 file. If they differ, stop. Do not extract the recovery ZIP.
3. Keep backups and a working restoration ROM outside the partitions written.
   An installer cannot establish that an external backup is actually restorable.
4. Put the installer ZIP inside the existing payloads directory alongside all
   22 unchanged .gz files. No PC, Python or installer creation is required.
5. Charge to at least 50%. The guard permits 20..49% only while battery/status
   reports Charging or Full; below 20%, unknown capacity, or unplugging during
   preflight stops before image writes. It rechecks before the first write.
6. In OrangeFox Files select the exact recovery ZIP, then swipe to install.
   Do not use ADB sideload for an installer with adjacent external payloads.
7. On success reboot to Recovery first and save/send recovery.log. On failure
   stop and send the log; if image writing started restore the working ROM
   before booting System. Do not bypass a failed guard or hash check.

The small ZIP contains the complete installer, not the multi-gigabyte ROM.
Compressed SHA256, gzip integrity, raw SHA256 and partition readback checks
remain mandatory. This does not format userdata or write vbmeta, recovery,
modem, bootloader or EFS. Existing P0 images remain unchanged.

For provenance verification with a computer, GitHub CLI supports:
gh attestation verify HyperOS4-R8Q-P0r8-CANDIDATE.zip --repo bonecopreparado/vendor-r8q
'''
(ROOT/'delivery/Ready-P0r8/TESTER-ENGLISH.txt').write_text(instructions)
manifest = dict(metadata, name='HyperOS4-R8Q-P0r8-CANDIDATE',
                installer_sha256=hashlib.sha256(installer).hexdigest(),
                readiness=status, rom_images_changed=False)
members = {
    'META-INF/com/google/android/update-binary':installer,
    'META-INF/com/google/android/updater-script':b'# P0r8 shell installer candidate\n',
    'P0-MANIFEST.json':(json.dumps(manifest,indent=2)+'\n').encode(),
    'README-TESTER.txt':instructions.encode(),
}
destination = OUT/'HyperOS4-R8Q-P0r8-CANDIDATE.zip'
with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=False) as archive:
    for name,data in members.items():
        info = zipfile.ZipInfo(name,date_time=(2026,11,1,0,0,0))
        info.create_system = 3
        info.external_attr = (0o100755 if name.endswith('update-binary') else 0o100644)<<16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info,data,compresslevel=6)
with zipfile.ZipFile(destination) as archive:
    if archive.testzip() or set(archive.namelist()) != set(members):
        raise ValueError('ZIP integrity/member validation failed')
    for name,data in members.items():
        if archive.read(name) != data:
            raise ValueError('ZIP content validation failed')
    if archive.getinfo('META-INF/com/google/android/update-binary').external_attr>>16 != 0o100755:
        raise ValueError('Installer executable mode differs')
sha = hashlib.sha256(destination.read_bytes()).hexdigest()
destination.with_suffix('.zip.sha256').write_text(sha+'  '+destination.name+'\n')
(OUT/'TESTER-ENGLISH.txt').write_text(instructions)
(OUT/'release-readiness.json').write_text(json.dumps(status,indent=2)+'\n')
print(json.dumps(dict(file=destination.name,bytes=destination.stat().st_size,sha256=sha,
                      boot_ready=status['boot_ready']),indent=2))
