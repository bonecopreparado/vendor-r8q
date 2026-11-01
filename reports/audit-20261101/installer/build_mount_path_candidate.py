"""Generate an isolated, NON_SHIPPING diff; never mutate the published P0r7."""
from pathlib import Path
import difflib
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'delivery/Revisao-P0r7-Windows/p0r7-assets/installer-template.sh'
DEST = ROOT / 'patches/0002-recovery-mount-paths'
DEST.mkdir(parents=True, exist_ok=True)
original = SOURCE.read_text()
old = '''    printf '%s\\n' "$mount_list" | while read -r length target; do
        umount "$target" || abort "Nao foi possivel desmontar $target; nenhuma imagem foi escrita."
    done
'''
new = r'''    printf '%s\n' "$mount_list" | while read -r length encoded_target; do
        # /proc/mounts escapes spaces, tabs and backslashes. Pass its raw bytes
        # via ENVIRON: awk -v and printf %b would themselves interpret escapes.
        R8Q_MOUNT_ESCAPED="$encoded_target"
        export R8Q_MOUNT_ESCAPED
        target="$(awk '
            BEGIN {
                s=ENVIRON["R8Q_MOUNT_ESCAPED"]; out=""
                for (i=1; i<=length(s); i++) {
                    c=substr(s,i,1)
                    if (c!="\\") { out=out c; continue }
                    code=substr(s,i+1,3)
                    if (code=="040") out=out " "
                    else if (code=="011") out=out "\t"
                    else if (code=="134") out=out "\\"
                    else exit 2
                    i+=3
                }
                printf "%s", out
            }
        ')" || abort "Escape nao suportado no ponto de montagem $encoded_target; nenhuma imagem foi escrita."
        case "$target" in /system|/system/*|/system_root|/system_root/*|/vendor|/vendor/*|/product|/product/*|/system_ext|/system_ext/*|/odm|/odm/*) ;;
            *) abort "Ponto de montagem inesperado; nenhuma imagem foi escrita." ;; esac
        umount "$target" || abort "Nao foi possivel desmontar $target; nenhuma imagem foi escrita."
    done
'''
assert original.count(old) == 1
candidate = original.replace(old, new)
path = DEST / 'installer-template-candidate.sh'
path.write_text(candidate)
subprocess.run(['bash', '-n', str(path)], check=True)
patch = ''.join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     fromfile='a/delivery/Revisao-P0r7-Windows/p0r7-assets/installer-template.sh',
                                     tofile='b/delivery/Revisao-P0r7-Windows/p0r7-assets/installer-template.sh'))
(DEST / 'candidate.diff').write_text(patch)
status = dict(status='NON_SHIPPING', source=str(SOURCE.relative_to(ROOT)),
              source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              candidate_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
              reason='Decode /proc/mounts paths before umount; current code aborts safely on escaped names',
              supported_escapes=['040', '011', '134'],
              refused_escapes=['012', 'all other escapes'],
              device_tested=False, published_installer_modified=False)
(DEST / 'status.json').write_text(json.dumps(status, indent=2) + '\n')
print(path)
