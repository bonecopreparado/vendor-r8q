"""Build a ready-to-run read-only recovery diagnostic. No image writes."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import zipfile

ROOT = Path(os.environ.get('R8Q_PROJECT_ROOT', '/workspace/hyperos-space'))
DEST = ROOT / 'delivery/Diagnostico-Leitura-R8Q'
DEST.mkdir(parents=True, exist_ok=True)
layout = json.loads((ROOT / 'delivery/Revisao-P0r5-Windows/p0r5-assets/chunks.json').read_text())
rows = '\n'.join(f"{r['name']} {r['offset']} {r['bytes']} {r['readback_sha256']}"
                 for r in layout['chunks'] if r['part'] == 'super')
script = r'''#!/sbin/sh
set -eu
set -o pipefail
OUTFD="$2"
ui_print() { printf 'ui_print %s\nui_print\n' "$*" >"/proc/self/fd/$OUTFD"; }
abort() { ui_print "DIAGNOSTICO INTERROMPIDO: $*"; exit 1; }
ui_print "R8Q - DIAGNOSTICO SOMENTE LEITURA. Nao instala a ROM."
ui_print "Nao grava particoes, nao formata e nao altera userdata."
ui_print "Leitor diagnostico r2: offsets grandes comparados como texto."
shell_div=$((2147483648/4096))
shell_wrap=0
if [ 4294967296 -eq 0 ]; then shell_wrap=1; fi
ui_print "Diagnostico shell: 2GiB/4096=$shell_div; teste numerico 4GiB=0: $shell_wrap"
ui_print "Versao do shell: ${KSH_VERSION:-nao informada}"
for tool in getprop blockdev head dd sha256sum readlink od uname wc mktemp rm rmdir cat tr; do
    command -v "$tool" >/dev/null 2>&1 || abort "Ferramenta ausente: $tool."
done
[ "$(getprop ro.product.device)" = r8q ] || abort "Somente Samsung r8q."
SUPER=/dev/block/bootdevice/by-name/super
[ -b "$SUPER" ] || abort "super nao encontrada."
capacity="$(blockdev --getsize64 "$SUPER")" || abort "Nao foi possivel ler capacidade."
[ "$capacity" = 10292822016 ] || abort "Capacidade nao corresponde ao aparelho medido: $capacity."
ui_print "Capacidade super: $capacity. Kernel: $(uname -m)."
if [ -e /sbin/sh ]; then
    ui_print "Shell recovery: $(readlink -f /sbin/sh)"
fi
for tool in dd head sha256sum; do
    path="$(command -v "$tool")"
    real="$(readlink -f "$path")" || abort "Falha ao resolver $tool."
    ui_print "Ferramenta $tool: $path -> $real"
    elf="$(od -An -v -tu1 -N20 "$real" | tr '\n' ' ')" || abort "Falha ao identificar $tool."
    ui_print "Identificacao de $tool (20 bytes): $elf"
done
WORK="$(mktemp -d /tmp/r8q-readonly.XXXXXX)" || abort "Sem diretorio temporario."
case "$WORK" in /tmp/r8q-readonly.*) ;; *) abort "Diretorio temporario inesperado." ;; esac
trap 'rm -f "$WORK/probe" "$WORK/rows"; rmdir "$WORK" 2>/dev/null || true' EXIT
# All local writes are restricted to our temporary diagnostic directory.
printf '0123456789abcdefghijklmnopqrstuv' > "$WORK/probe"
head_probe() (
    exec 9<"$WORK/probe" || exit 1
    a="$(head -c 16 <&9)" || exit 1
    b="$(head -c 16 <&9)" || exit 1
    [ "$a" = 0123456789abcdef ] && [ "$b" = ghijklmnopqrstuv ]
)
head_probe || abort "head nao passou no teste temporario de leitura sequencial."
prefix="$(head -c 4096 "$SUPER" | sha256sum)" || abort "Falha na leitura do prefixo."
ui_print "Prefixo super SHA256 atual (diagnostico): ${prefix%% *}"
cat > "$WORK/rows" <<'R8Q_READONLY_ROWS'
@@ROWS@@
R8Q_READONLY_ROWS
verify_method() (
    method="$1"
    if [ "$OUTFD" = 9 ]; then exec 8>&9 || exit 1; OUTFD=8; fi
    exec 9<"$SUPER" || exit 1
    if [ "$method" = head ]; then
        skipped="$(head -c 4096 <&9 | wc -c)" || exit 1
    else
        skipped="$(dd bs=1 count=4096 <&9 2>/dev/null | wc -c)" || exit 1
    fi
    [ "$skipped" -eq 4096 ] || exit 1
    while read -r name offset length expected; do
        if [ "$offset" = 0 ]; then length=$((length-4096)); fi
        ui_print "LEITURA metodo=$method parte=$name offset=$offset tamanho=$length"
        if [ "$method" = head ]; then
            if got="$(head -c "$length" <&9 | sha256sum)"; then :; else
                ui_print "FALHA DE PROCESSO: metodo=$method parte=$name codigo=$?"; exit 1
            fi
        else
            if got="$(dd bs=4096 count="$((length/4096))" <&9 | sha256sum)"; then :; else
                ui_print "FALHA DE PROCESSO: metodo=$method parte=$name codigo=$?"; exit 1
            fi
        fi
        actual="${got%% *}"
        if [ "$actual" != "$expected" ]; then
            ui_print "DIVERGENCIA metodo=$method parte=$name"
            ui_print "SHA esperado: $expected"
            ui_print "SHA obtido:   $actual"
            exit 1
        fi
        ui_print "OK metodo=$method parte=$name"
    done < "$WORK/rows"
    ui_print "SUPER INTEIRA CONFERIDA metodo=$method (prefixo local preservado)"
)
head_ok=0
dd_ok=0
if verify_method head; then head_ok=1; fi
if verify_method dd; then dd_ok=1; fi
ui_print "RESULTADO SOMENTE LEITURA: head_ok=$head_ok dd_ok=$dd_ok"
if [ "$head_ok" = 1 ] && [ "$dd_ok" = 0 ]; then
    ui_print "super corresponde a P0 via head; metodo dd divergiu."
elif [ "$head_ok" = 1 ] && [ "$dd_ok" = 1 ]; then
    ui_print "super corresponde a P0 nas duas leituras atuais."
else
    ui_print "Integridade de super ainda nao confirmada. Envie recovery.log."
fi
ui_print "DIAGNOSTICO CONCLUIDO. Nenhuma particao foi gravada."
ui_print "Guarde recovery.log. Isto nao concluiu a instalacao da ROM."
ui_print "Nao reinicie uma instalacao incompleta; restaure a base antes de outro boot."
exit 0
'''.replace('@@ROWS@@', rows)
installer = DEST / 'update-binary'
installer.write_text(script)
subprocess.run(['bash', '-n', str(installer)], check=True)
readme = '''DIAGNOSTICO SOMENTE LEITURA - S20 FE SNAPDRAGON r8q

Copie Diagnostico-Leitura-R8Q.zip para o celular e selecione no OrangeFox.
Pode ficar em qualquer pasta; nao depende de payloads e nao instala a ROM.
Ele le a super atual por dois metodos, confere hashes fixos de todas as partes
e registra onde cada metodo divergiu. Nao grava particoes, nao desmonta,
nao formata nem reinicia. So cria pequenos arquivos temporarios em /tmp.
Ao terminar, envie o recovery.log novo. Pode levar alguns minutos.

O recovery(5).log mostra 4096 bytes a menos na regiao em 4 GiB. Uma reproducao
com mksh real identificou comparacao numerica de 32 bits tratando esse offset
como zero. Este diagnostico r2 corrige essa comparacao e registra os limites
do shell para confirmar no recovery. Ainda verifica os hashes da super atual.
Os hashes nao foram removidos. O verde neste diagnostico significa somente
que a coleta terminou: nao significa que a ROM foi instalada ou iniciou.
Fique no recovery e restaure a base funcional antes de iniciar aquele estado
incompleto. Boot e pendencias de SELinux/hardware seguem nao resolvidos.
'''
(DEST / 'LEIA-ME.txt').write_text(readme)
output = ROOT / 'output/Diagnostico-Leitura-R8Q-r2.zip'
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=False) as archive:
    for name, data in {'META-INF/com/google/android/update-binary': script.encode(),
                       'META-INF/com/google/android/updater-script': b'# Read-only diagnostic\n',
                       'LEIA-ME.txt': readme.encode()}.items():
        info = zipfile.ZipInfo(name, date_time=(2026, 10, 31, 0, 0, 0))
        info.create_system = 3
        info.external_attr = (0o100755 if name.endswith('update-binary') else 0o100644) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, data, compresslevel=6)
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
print(output, output.stat().st_size, hashlib.sha256(output.read_bytes()).hexdigest())
