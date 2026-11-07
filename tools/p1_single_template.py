"""Derive a one-ZIP installer while retaining the reviewed P0r8 write guards."""
from pathlib import Path
import hashlib

ROOT=Path(__file__).resolve().parents[1]
PARENT_SHA='9a0ac40c6fb79b6347ca3ea14b0ff8a7deb4400f54499548ff345f86be7e110d'

def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError('Reviewed installer section changed: '+old[:90])
    return text.replace(old,new)

def template(root=ROOT,build_label='P1'):
    if build_label not in ('P1','P1r1','P1r2'):raise ValueError('Unknown experimental build label')
    parent=(root/'delivery/Ready-P0r8/installer-template-ready.sh').read_bytes()
    if hashlib.sha256(parent).hexdigest()!=PARENT_SHA:raise ValueError('P0r8 template identity changed')
    s=parent.decode()
    # mksh may use a missing inherited TMPDIR for here-document backing files.
    # WORK was created and validated under /tmp; pin the shell's temporary
    # directory before it encounters the payload-table here-document.
    s=replace_once(s,'DD_FSYNC=0\n','TMPDIR="$WORK"\nexport TMPDIR\nDD_FSYNC=0\n')
    s=s.replace('mktemp rm rmdir sync;','mktemp rm rmdir sync chmod;')
    s=s.replace('HyperOS4 -> R8Q P0r8 EXPERIMENTAL / boot not confirmed',
                'HyperOS4 -> R8Q '+build_label+' SINGLE ZIP EXPERIMENTAL / boot not confirmed')
    s=s.replace('ui_print "Altera somente super, boot e dtbo. Nao formata userdata."',
                'ui_print "Altera somente super, boot e dtbo. Nao formata userdata."\n'
                'ui_print "P1: kernel/FCM/HAL compatibility work remains. This is an experimental boot test."')
    if build_label in ('P1r1','P1r2'):
        s=s.replace('ui_print "P1: kernel/FCM/HAL compatibility work remains. This is an experimental boot test."',
                    'ui_print "'+build_label+': system_ext/product SELinux mappings omitted; system mappings retained."\n'
                    'ui_print "Experimental test only. Kernel/FCM/HAL compatibility work remains."')
    s=s.replace('trap \'rm -f "$WORK/probe"', 'trap \'rm -f "$WORK/zipread" "$WORK/probe"')
    start=s.index('# Payloads stay outside the tiny installer ZIP:')
    end=s.index('cat > "$WORK/payload.rows"',start)
    bootstrap='''# Native ZIP64 reader is the first stored ZIP entry, aligned to 4 KiB.
# Bootstrap reads only a bounded <=2 MiB member at offset 4096; no giant unzip.
zip_real="$(readlink -f "$ZIPFILE")" || abort "Cannot resolve local ZIP."
[ -f "$zip_real" ] && [ -r "$zip_real" ] || abort "ZIP must be a readable local file."
dd if="$zip_real" of="$WORK/zipread" bs=4096 skip=1 count=@@HELPER_BLOCKS@@ 2>/dev/null || abort "Native helper extraction failed. Nothing was written."
[ "$(wc -c < "$WORK/zipread")" -eq @@HELPER_BYTES@@ ] || abort "Native helper is truncated. Nothing was written."
helper_hash="$(sha256sum "$WORK/zipread")" || abort "Native helper hash failed."
[ "${helper_hash%% *}" = "@@HELPER_SHA@@" ] || abort "Native helper hash differs. Nothing was written."
chmod 0755 "$WORK/zipread" || abort "Cannot make native helper executable."
ZIPREAD="$WORK/zipread"
"$ZIPREAD" --version || abort "Native ZIP64 helper cannot run in this recovery. Nothing was written."
zip_part() { "$ZIPREAD" "$zip_real" "payloads/$1"; }
zip_part_size() { "$ZIPREAD" --size "$zip_real" "payloads/$1"; }
ui_print "Single ZIP: native 64-bit stored-member reader is ready."
'''
    s=s[:start]+bootstrap+s[end:]
    old='''    file="$PAYLOAD_DIR/$name"
    [ -f "$file" ] && [ ! -L "$file" ] && [ -r "$file" ] || abort "Parte ausente ou invalida: $name. Copie a pasta inteira. Nada foi gravado."
    [ "$(readlink -f "$file")" = "$file" ] || abort "Caminho indireto de parte nao permitido: $name."
'''
    s=replace_once(s,old,'')
    s=replace_once(s,'if gzip -dc "$PAYLOAD_DIR/$1"; then return 0; else',
                   'if zip_part "$1" | gzip -dc; then return 0; else')
    old='''    file="$PAYLOAD_DIR/$name"
    actual_size="$(wc -c < "$file")" || abort "Falha ao ler tamanho de $name. Nada foi gravado."
'''
    s=replace_once(s,old,'''    actual_size="$(zip_part_size "$name")" || abort "Missing or invalid ZIP member: $name. Nothing was written."
''')
    s=replace_once(s,'compressed="$(hash_stream < "$file")"',
                   'compressed="$(zip_part "$name" | hash_stream)"')
    s=replace_once(s,'Falha de SHA256 do arquivo $name. Nada foi gravado.',
                   'Falha ao ler/verificar $name no ZIP (CRC/SHA256). Confira o SHA256 do ZIP completo e copie novamente se diferente. Nada foi gravado.')
    start=s.index('while read -r part name rawbytes rawsha cbytes csha offset readbacksha; do\n    R8Q_ZIP_REAL="$PAYLOAD_DIR/$name"')
    end=s.index('# Named mounts are unmounted below.',start)
    s=s[:start]+'# All member data resides in the local ZIP protected by the mount guard above.\n'+s[end:]
    s=s.replace('ui_print "P0 gravada e hashes de retorno conferidos."',
                'ui_print "'+build_label+' written; every readback hash matched. Boot remains unconfirmed."')
    # Avoid mksh's here-document backing-file creation in recovery entirely.
    # Payload rows are generated from validated canonical names/numbers/hashes.
    s=replace_once(s,'''cat > "$WORK/payload.rows" <<'P0R7_PAYLOAD_ROWS'
@@PAYLOAD_ROWS@@
P0R7_PAYLOAD_ROWS
''',"""printf '%s\\n' '@@PAYLOAD_ROWS@@' > "$WORK/payload.rows"
""")
    if 'PAYLOAD_DIR' in s:raise ValueError('External payload dependency remains')
    return s

if __name__=='__main__':print(template(),end='')
