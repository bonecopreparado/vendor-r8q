#!/sbin/sh
# Experimental HyperOS4 R8Q P0. Shell installer generated from measured limits.
set -eu
set -o pipefail
OUTFD="$2"
ZIPFILE="$3"
ui_print() { printf 'ui_print %s\nui_print\n' "$*" >"/proc/self/fd/$OUTFD"; }
abort() { ui_print "ERRO: $*"; exit 1; }
for tool in getprop blockdev gzip sha256sum dd awk sort umount cat readlink od wc mktemp rm rmdir sync; do
    command -v "$tool" >/dev/null 2>&1 || abort "Ferramenta ausente no recovery: $tool"
done
[ "$(getprop ro.product.device)" = r8q ] || abort "Somente Samsung r8q."
SUPER=/dev/block/bootdevice/by-name/super
BOOT=/dev/block/bootdevice/by-name/boot
DTBO=/dev/block/bootdevice/by-name/dtbo
VBMETA=/dev/block/bootdevice/by-name/vbmeta
check_size() {
    [ -b "$1" ] || abort "Particao ausente: $1"
    size="$(blockdev --getsize64 "$1")" || abort "Falha ao ler tamanho: $1"
    [ "$size" = "$2" ] || abort "Tamanho diferente do aparelho medido: $1 ($size)"
}
check_size "$SUPER" 10292822016
check_size "$BOOT" 67108864
check_size "$DTBO" 10485760
check_size "$VBMETA" 65536
ui_print "HyperOS4 -> R8Q P0r7 EXPERIMENTAL / sem teste de boot"
# This is a diagnostic, not an assumption that the shell is 64-bit.
shell_arith_probe=$((2147483647+1))
ui_print "Aritmetica do shell (diagnostico): 2147483647+1=$shell_arith_probe"

ui_print "Altera somente super, boot e dtbo. Nao formata userdata."
ui_print "Conferindo o vbmeta atual antes de qualquer escrita..."
# Header/flags validation only. No signature or full AVB chain claim.
current_vbmeta="$(sha256sum "$VBMETA" | awk '{print $1}')" || abort "Falha ao ler vbmeta."
ui_print "vbmeta SHA256 (diagnostico): $current_vbmeta"
avb_check="$(od -An -v -tu1 -N256 "$VBMETA" | awk -v capacity=65536 '
# Read-only, bounded AVB header inspection. Input: od -An -v -tu1 -N256 FILE
# Use -v capacity=65536 (actual partition size already checked by installer).
# No cryptographic signature, descriptor payload, or boot-chain verification.
# Known AVB header versions and algorithms only; unknown formats fail closed.
function fail(message) { print "vbmeta: " message; failed=1; exit 1 }
function be32(offset) { return ((byte[offset]*256+byte[offset+1])*256+byte[offset+2])*256+byte[offset+3] }
function bounded64(offset, label) {
    if (be32(offset) != 0) fail(label " exceeds supported partition bounds")
    return be32(offset+4)
}
function fits(offset, span, limit, label) {
    # Subtract rather than add to avoid wrapping in a future integer awk.
    if (offset > limit || span > limit-offset) fail(label " lies outside its block")
}
function disjoint(a, na, b, nb, label) {
    if (na && nb && a < b+nb && b < a+na) fail(label " overlaps")
}
{
    for (i=1; i<=NF; i++) {
        if ($i !~ /^[0-9]+$/ || $i+0 > 255) fail("input is not a decimal-byte dump")
        if (count >= 256) fail("header is larger than 256 bytes")
        byte[count++]=$i+0
    }
}
END {
    if (failed) exit 1
    if (count != 256) fail("incomplete 256-byte header")
    if (capacity !~ /^[0-9]+$/ || capacity+0 < 256 || capacity+0 > 4294967295) fail("invalid partition capacity")
    if (byte[0]!=65 || byte[1]!=86 || byte[2]!=66 || byte[3]!=48) fail("AVB0 magic not found")
    major=be32(4); minor=be32(8)
    if (major != 1 || minor > 2) fail("unsupported required AVB version")
    flags=be32(120)
    if (flags != 3) fail("verification and hashtree must already be disabled (flags=3)")
    auth=bounded64(12,"authentication block")
    aux=bounded64(20,"auxiliary block")
    if (auth%64 || aux%64) fail("authentication/auxiliary blocks must be 64-byte aligned")
    if (auth > capacity-256 || aux > capacity-256-auth) fail("declared blocks exceed partition")
    algorithm=be32(28)
    if (algorithm > 6) fail("unsupported signature algorithm")
    hash_off=bounded64(32,"hash offset"); hash_size=bounded64(40,"hash size")
    sig_off=bounded64(48,"signature offset"); sig_size=bounded64(56,"signature size")
    key_off=bounded64(64,"public key offset"); key_size=bounded64(72,"public key size")
    meta_off=bounded64(80,"public key metadata offset"); meta_size=bounded64(88,"public key metadata size")
    desc_off=bounded64(96,"descriptors offset"); desc_size=bounded64(104,"descriptors size")
    # Rollback index (112..119) may span the full uint64 range. It is not an
    # offset and is not evaluated by this format check. Likewise location124.
    fits(hash_off,hash_size,auth,"hash")
    fits(sig_off,sig_size,auth,"signature")
    fits(key_off,key_size,aux,"public key")
    fits(meta_off,meta_size,aux,"public key metadata")
    fits(desc_off,desc_size,aux,"descriptors")
    disjoint(hash_off,hash_size,sig_off,sig_size,"hash/signature")
    disjoint(key_off,key_size,meta_off,meta_size,"public key/key metadata")
    disjoint(key_off,key_size,desc_off,desc_size,"public key/descriptors")
    disjoint(meta_off,meta_size,desc_off,desc_size,"key metadata/descriptors")
    if (desc_off%8 || desc_size%8) fail("descriptor region must be 8-byte aligned")
    if (algorithm == 0) {
        if (auth || hash_size || sig_size || key_size) fail("NONE algorithm has authentication/key data")
    } else {
        expected_hash=(algorithm<=3 ? 32 : 64)
        rsa=((algorithm-1)%3)
        expected_signature=(rsa==0 ? 256 : (rsa==1 ? 512 : 1024))
        expected_key=8+expected_signature*2
        if (hash_size!=expected_hash || sig_size!=expected_signature || key_size!=expected_key) fail("sizes do not match signature algorithm")
    }
    # Header reserved bytes are zero in supported AVB versions.
    for (i=176;i<256;i++) if (byte[i]) fail("nonzero reserved header bytes")
    print "AVB0 version=" major "." minor " flags=3 algorithm=" algorithm " auth=" auth " aux=" aux
}

')" || abort "vbmeta incompativel: $avb_check. Nada foi gravado."
ui_print "$avb_check"
# Skip exact bytes using bs=1, never a block-sized skip on a pipe.
# These functions isolate FD9 in subshells, including if OUTFD itself is 9.
write_stream() {
    if [ "$DD_FSYNC" = 1 ]; then
        dd bs=1048576 conv=fsync || return 1
    else
        dd bs=1048576 || return 1
        sync || return 1
    fi
}
write_tail() (
    exec 9<>"$1" || exit 1
    skipped_target="$(dd bs=1 count=4096 <&9 2>/dev/null | wc -c)" || exit 1
    [ "$skipped_target" -eq 4096 ] || exit 1
    skipped_input="$(dd bs=1 count=4096 2>/dev/null | wc -c)" || exit 1
    [ "$skipped_input" -eq 4096 ] || exit 1
    write_stream >&9 || exit 1
)
# Check the real dd options and shared-file-offset method on a tiny /tmp file.
# No partition is opened for writing during this probe.
WORK="$(mktemp -d /tmp/r8q-p0r7.XXXXXX)" || abort "Sem espaco temporario no recovery. Nada foi gravado."
case "$WORK" in /tmp/r8q-p0r7.*) ;; *) abort "Diretorio temporario inesperado." ;; esac
trap 'rm -f "$WORK/probe" "$WORK/flush-check" "$WORK/payload.rows"; rmdir "$WORK" 2>/dev/null || true' EXIT
DD_FSYNC=0
if printf 'flush-test' | dd of="$WORK/flush-check" bs=4096 conv=fsync 2>/dev/null; then
    DD_FSYNC=1
else
    sync || abort "Falha na sincronizacao; nenhuma particao foi gravada."
fi
dd if=/dev/zero of="$WORK/probe" bs=4096 count=2 2>/dev/null || abort "Falha no teste temporario de dd."
probe_prefix="$(dd if="$WORK/probe" bs=1 count=4096 2>/dev/null | sha256sum | awk '{print $1}')" || abort "Falha ao ler teste temporario."
probe_expected="$(printf 'R8Q-portable-stream' | sha256sum | awk '{print $1}')"
{ dd if=/dev/zero bs=1 count=4096 2>/dev/null && printf 'R8Q-portable-stream'; } | write_tail "$WORK/probe" || abort "dd do recovery falhou no teste de gravacao; nenhuma particao foi gravada."
probe_actual="$(dd if="$WORK/probe" bs=1 skip=4096 count=19 2>/dev/null | sha256sum | awk '{print $1}')" || abort "Falha ao conferir teste temporario."
probe_after="$(dd if="$WORK/probe" bs=1 count=4096 2>/dev/null | sha256sum | awk '{print $1}')"
[ "$probe_actual" = "$probe_expected" ] && [ "$probe_after" = "$probe_prefix" ] && [ "$(wc -c < "$WORK/probe")" -eq 8192 ] || abort "Teste temporario alterou bytes inesperados; nenhuma particao foi gravada."
ui_print "Teste de gravacao portavel aprovado (fsync=$DD_FSYNC)."
# Probe descriptor advancement across separate dd subprocesses.
readback_probe() (
    exec 9<"$WORK/probe" || exit 1
    first="$(dd bs=4096 count=1 <&9 2>/dev/null | sha256sum | awk '{print $1}')" || exit 1
    second="$(dd bs=1 count=19 <&9 2>/dev/null | sha256sum | awk '{print $1}')" || exit 1
    [ "$first" = "$probe_prefix" ] && [ "$second" = "$probe_expected" ]
)
readback_probe || abort "Teste de leitura sequencial falhou. Nada foi gravado."
ui_print "Teste de leitura sequencial aprovado; sem saltos grandes de dd."

prefix_before="$(dd if="$SUPER" bs=1 count=4096 2>/dev/null | sha256sum | awk '{print $1}')" || abort "Falha ao ler prefixo super."
# Compare only the two 52-byte LP geometry structures, not padding bytes.
for geometry_offset in 4096 8192; do
    geometry_hash="$(dd if="$SUPER" bs=1 skip="$geometry_offset" count=52 2>/dev/null | sha256sum | awk '{print $1}')" || abort "Falha ao ler geometria super."
    [ "$geometry_hash" = '266f8d746eebf5fd860ebe60debde12b4a21767a4a5862410320b86d03cb00f8' ] || abort "Geometria super diferente da suportada; envie metadados. Nada foi gravado."
done

# Payloads stay outside the tiny installer ZIP: no recovery unzip of ZIP64 data.
zip_real="$(readlink -f "$ZIPFILE")" || abort "Falha ao resolver ZIP instalador."
PAYLOAD_DIR="${zip_real%/*}/payloads"
[ -d "$PAYLOAD_DIR" ] && [ ! -L "$PAYLOAD_DIR" ] || abort "Pasta payloads ausente ou link; copie a pasta P0r7 inteira. Nada foi gravado."
cat > "$WORK/payload.rows" <<'P0R7_PAYLOAD_ROWS'
@@PAYLOAD_ROWS@@
P0R7_PAYLOAD_ROWS
row_count=0
while read -r part name rawbytes rawsha cbytes csha offset readbacksha extra; do
    [ -z "${extra:-}" ] || abort "Tabela de partes invalida."
    case "$part/$name" in super/super-[0-9][0-9][0-9].gz|boot/boot-[0-9][0-9][0-9].gz|dtbo/dtbo-[0-9][0-9][0-9].gz) ;;
        *) abort "Nome de parte invalido." ;; esac
    file="$PAYLOAD_DIR/$name"
    [ -f "$file" ] && [ ! -L "$file" ] && [ -r "$file" ] || abort "Parte ausente ou invalida: $name. Copie a pasta inteira. Nada foi gravado."
    [ "$(readlink -f "$file")" = "$file" ] || abort "Caminho indireto de parte nao permitido: $name."
    row_count=$((row_count+1))
done < "$WORK/payload.rows"
[ "$row_count" -eq 22 ] || abort "Tabela de partes incompleta."

# Validate all byte-sized fields in AWK before any target write. IEEE double
# represents these bounded (<=10GiB) integers exactly; shell arithmetic may not.
super_limit="$(blockdev --getsize64 "$SUPER")" || abort "Falha ao reler capacidade super. Nada foi gravado."
boot_limit="$(blockdev --getsize64 "$BOOT")" || abort "Falha ao reler capacidade boot. Nada foi gravado."
dtbo_limit="$(blockdev --getsize64 "$DTBO")" || abort "Falha ao reler capacidade dtbo. Nada foi gravado."
table_check="$(awk -v super_limit="$super_limit" -v boot_limit="$boot_limit" -v dtbo_limit="$dtbo_limit" '
function fail(s) { print s; failed=1; exit 1 }
function decimal(s) { return s ~ /^(0|[1-9][0-9]*)$/ }
function hash(s) { return length(s)==64 && s ~ /^[0-9a-f]+$/ }
BEGIN { limit["super"]=super_limit; limit["boot"]=boot_limit; limit["dtbo"]=dtbo_limit }
{
    if (NF!=8 || !($1 in limit)) fail("campos/particao invalidos")
    part=$1
    if ($2 != part "-" sprintf("%03d", count[part]+0) ".gz") fail("ordem/nome invalidos")
    if (!decimal($3) || !decimal($5) || !decimal($7)) fail("inteiro nao canonico")
    if (!hash($4) || !hash($6) || !hash($8)) fail("SHA256 invalido")
    size=$3+0; offset=$7+0
    if (size<=0 || size>536870912 || size%4096 || offset%4096) fail("tamanho/alinhamento invalido")
    if ($5+0<=0 || $5+0>1073741824) fail("tamanho gzip invalido")
    if (offset != position[part]+0 || size>limit[part]-offset) fail("offset/limite invalido")
    if (part=="super" && offset==0 && size<=4096) fail("primeira parte super incompleta")
    position[part]=offset+size
    count[part]++
}
END {
    if (failed) exit 1
    for (part in limit) if (position[part]!=limit[part] || !count[part]) fail("imagem nao coberta integralmente")
    print "Tabela de offsets/tamanhos aprovada por AWK."
}
' "$WORK/payload.rows")" || abort "Tabela de partes invalida: $table_check. Nada foi gravado."
ui_print "$table_check"

hash_stream() {
    if sha256sum; then return 0; else
        hash_rc=$?
        printf '[P0r7] sha256sum falhou: codigo %s\n' "$hash_rc" >&2
        return "$hash_rc"
    fi
}
inflate_part() {
    if gzip -dc "$PAYLOAD_DIR/$1"; then return 0; else
        gzip_rc=$?
        printf '[P0r7] gzip falhou em %s: codigo %s\n' "$1" "$gzip_rc" >&2
        return "$gzip_rc"
    fi
}
ui_print "Conferindo 22 partes pequenas antes de qualquer escrita em particao..."
while read -r part name rawbytes rawsha cbytes csha offset readbacksha; do
    ui_print "Conferindo $name: arquivo comprimido e conteudo..."
    file="$PAYLOAD_DIR/$name"
    actual_size="$(wc -c < "$file")" || abort "Falha ao ler tamanho de $name. Nada foi gravado."
    [ "$actual_size" -eq "$cbytes" ] || abort "Parte incompleta: $name. Copie novamente. Nada foi gravado."
    compressed="$(hash_stream < "$file")" || abort "Falha de SHA256 do arquivo $name. Nada foi gravado."
    [ "${compressed%% *}" = "$csha" ] || abort "Arquivo comprimido corrompido: $name. Nada foi gravado."
    raw="$(inflate_part "$name" | hash_stream)" || abort "Falha gzip/SHA256 de $name; veja codigo no log. Nada foi gravado."
    [ "${raw%% *}" = "$rawsha" ] || abort "Conteudo incorreto em $name. Nada foi gravado."
done < "$WORK/payload.rows"
stream_image() {
    wanted="$1"
    while read -r part name rawbytes rawsha cbytes csha offset readbacksha; do
        if [ "$part" = "$wanted" ]; then
            inflate_part "$name" || return 1
        fi
    done < "$WORK/payload.rows"
}
# A shared descriptor advances sequentially; dd processes <=512MiB per call.
# mksh integer arithmetic/tests wrap at 32 bits even on a 64-bit platform.
# Use string equality for offset zero, AWK for byte offsets, small block counters.
# Subshell isolates FD9, even when the recovery UI uses output descriptor 9.
verify_written() (
    wanted="$1"
    device="$2"
    if [ "$OUTFD" = 9 ]; then
        exec 8>&9 || exit 1
        OUTFD=8
    fi
    exec 9<"$device" || abort "Falha ao abrir leitura de retorno; restaure a base."
    # Counter units are 4KiB blocks: entire super is only 2512896 blocks.
    # Byte offsets may exceed 2/4/8GiB and MUST NOT enter shell integer tests.
    cursor_blocks=0
    while read -r part name rawbytes rawsha cbytes csha offset readbacksha; do
        if [ "$part" != "$wanted" ]; then continue; fi
        offset_blocks="$(awk -v value="$offset" 'BEGIN { printf "%.0f", value/4096 }')" || abort "Falha ao converter offset; restaure a base."
        [ "$offset_blocks" -eq "$cursor_blocks" ] || abort "Ordem de leitura invalida; restaure a base."
        length="$rawbytes"
        if [ "$part" = super ] && [ "$offset" = 0 ]; then
            skipped="$(dd bs=1 count=4096 <&9 2>/dev/null | wc -c)" || abort "Falha ao ler prefixo super; restaure a base."
            [ "$skipped" -eq 4096 ] || abort "Prefixo super incompleto; restaure a base."
            length=$((rawbytes-4096))
        fi
        [ "$length" -gt 0 ] && [ "$length" -le 536870912 ] && [ "$((length%4096))" -eq 0 ] || abort "Regiao de leitura invalida; restaure a base."
        ui_print "Conferindo leitura sequencial: $name..."
        got="$(dd bs=4096 count="$((length/4096))" <&9 | hash_stream)" || abort "Falha na leitura de retorno $name; restaure a base."
        [ "${got%% *}" = "$readbacksha" ] || abort "Hash gravado incorreto em $name; restaure a base pelo recovery."
        cursor_blocks=$((cursor_blocks+rawbytes/4096))
    done < "$WORK/payload.rows"
    [ "$cursor_blocks" -gt 0 ] || abort "Particao sem partes; restaure a base."
)
# Resolve target devices through sysfs so alternate/bind mountpoints cannot be
# missed. Follow dm dependency chains; userdata on its own block stays allowed.
protected_devs=' '
add_sysdev() {
    devno="$(cat "$1/dev")" || abort "Nao foi possivel ler dispositivo sysfs: $1"
    case "$devno" in *[!0-9:]*|''|:*) abort "Identificador sysfs invalido: $1" ;; esac
    case "$protected_devs" in *" $devno "*) ;; *) protected_devs="$protected_devs$devno "; mapping_changed=1 ;; esac
}
add_block() {
    resolved="$(readlink -f "$1")" || abort "Falha ao resolver bloco: $1"
    node="/sys/class/block/${resolved##*/}"
    [ -r "$node/dev" ] || abort "Sysfs indisponivel para $1; nada foi gravado."
    add_sysdev "$node"
}
add_block "$SUPER"
add_block "$BOOT"
add_block "$DTBO"
for logical in system vendor product odm system_ext; do
    for alias in "/dev/block/bootdevice/by-name/$logical" "/dev/block/by-name/$logical" "/dev/block/mapper/$logical"; do
        if [ -b "$alias" ]; then add_block "$alias"; fi
    done
done
mapping_changed=1
mapping_round=0
while [ "$mapping_changed" = 1 ]; do
    mapping_changed=0
    mapping_round=$((mapping_round+1))
    [ "$mapping_round" -le 32 ] || abort "Dependencias dm excessivas; nada foi gravado."
    for dmnode in /sys/class/block/dm-*; do
        [ -e "$dmnode" ] || continue
        [ -r "$dmnode/dev" ] && [ -d "$dmnode/slaves" ] || abort "Sysfs dm incompleto; nada foi gravado."
        for slave in "$dmnode"/slaves/*; do
            [ -e "$slave" ] || continue
            slave_dev="$(cat "$slave/dev")" || abort "Falha ao ler dependencia dm."
            case "$protected_devs" in *" $slave_dev "*) add_sysdev "$dmnode" ;; esac
        done
    done
done
[ -r /proc/self/mountinfo ] || abort "mountinfo indisponivel; nada foi gravado."
zip_real="$(readlink -f "$ZIPFILE")" || abort "Falha ao resolver caminho do ZIP."
[ -f "$zip_real" ] && [ -r "$zip_real" ] || abort "ZIP nao e um arquivo local legivel."
# Select the deepest mount containing the ZIP (including bind mounts).
R8Q_ZIP_REAL="$zip_real"
export R8Q_ZIP_REAL
zip_mount="$(awk '
    BEGIN { z=ENVIRON["R8Q_ZIP_REAL"] }
    { p=$5; gsub(/\\040/, " ", p); gsub(/\\011/, "\t", p); gsub(/\\134/, "\\", p);
      if ((p == "/" || z == p || index(z,p "/") == 1) && length(p) > best) {
          best=length(p); dev=$3; named=($5 ~ /^\/(system|system_root|vendor|product|system_ext|odm)(\/|$)/)
      }
    } END { if (!best) exit 2; print dev, named }
' /proc/self/mountinfo)" || abort "Nao foi possivel identificar origem do ZIP."
zip_dev="${zip_mount%% *}"
case "$protected_devs" in *" $zip_dev "*) abort "ZIP esta numa particao que sera sobrescrita. Copie para /data ou armazenamento externo." ;; esac
case "$zip_mount" in *' 1') abort "ZIP esta num caminho que sera desmontado. Copie para /data ou armazenamento externo." ;; esac

while read -r part name rawbytes rawsha cbytes csha offset readbacksha; do
    R8Q_ZIP_REAL="$PAYLOAD_DIR/$name"
    export R8Q_ZIP_REAL
    source_dev="$(awk '
        BEGIN { z=ENVIRON["R8Q_ZIP_REAL"] }
        { p=$5; gsub(/\\040/, " ", p); gsub(/\\011/, "\t", p); gsub(/\\134/, "\\", p);
          if ((p == "/" || z == p || index(z,p "/") == 1) && length(p) > best) { best=length(p); dev=$3 } }
        END { if (!best) exit 2; print dev }
    ' /proc/self/mountinfo)" || abort "Nao foi possivel identificar armazenamento de $name."
    case "$protected_devs" in *" $source_dev "*) abort "Parte $name esta em particao alvo. Mova a pasta inteira para armazenamento externo ou /data. Nada foi gravado." ;; esac
done < "$WORK/payload.rows"
# Named mounts are unmounted below. An alias mount is reported rather than
# silently unmounting an arbitrary user-selected path.
alias_mounts="$(awk -v protected="$protected_devs" '
    index(protected," " $3 " ") && $5 !~ /^\/(system|system_root|vendor|product|system_ext|odm)(\/|$)/ {print $5}
' /proc/self/mountinfo)" || abort "Falha ao verificar montagens por dispositivo."
[ -z "$alias_mounts" ] || abort "Particao alvo montada em outro caminho: $alias_mounts. Nada foi gravado."

ui_print "Todos os arquivos conferidos. Desmontando somente particoes do sistema..."
# Child mounts first. Userdata and external storage stay mounted for the ZIP.
mount_list="$(awk '$2 ~ /^\/(system|system_root|vendor|product|system_ext|odm)(\/|$)/ {print length($2), $2}' /proc/mounts | sort -rn)"
if [ -n "$mount_list" ]; then
    printf '%s\n' "$mount_list" | while read -r length target; do
        umount "$target" || abort "Nao foi possivel desmontar $target; nenhuma imagem foi escrita."
    done
fi
remaining="$(awk '$2 ~ /^\/(system|system_root|vendor|product|system_ext|odm)(\/|$)/ {print $2}' /proc/mounts)"
[ -z "$remaining" ] || abort "Ainda existem particoes do sistema montadas."
remaining_devices="$(awk -v protected="$protected_devs" 'index(protected," " $3 " ") {print $5}' /proc/self/mountinfo)" || abort "Falha ao conferir montagens finais."
[ -z "$remaining_devices" ] || abort "Particoes alvo ainda montadas: $remaining_devices. Nada foi gravado."


ui_print "Gravando super por partes; preservando os primeiros 4 KiB. Nao interrompa."
stream_image super | write_tail "$SUPER" || abort "Falha ao gravar super; restaure a base pelo recovery."
prefix_after="$(dd if="$SUPER" bs=1 count=4096 2>/dev/null | sha256sum | awk '{print $1}')" || abort "Falha ao reler prefixo super."
[ "$prefix_after" = "$prefix_before" ] || abort "Prefixo super mudou; restaure a base."
verify_written super "$SUPER"
ui_print "Gravando dtbo. Nao interrompa."
stream_image dtbo | (exec 9<>"$DTBO" && write_stream >&9) || abort "Falha ao gravar dtbo; restaure a base."
verify_written dtbo "$DTBO"
ui_print "Gravando boot. Nao interrompa."
stream_image boot | (exec 9<>"$BOOT" && write_stream >&9) || abort "Falha ao gravar boot; restaure a base."
verify_written boot "$BOOT"
ui_print "P0 gravada e hashes de retorno conferidos."
ui_print "Reinicie primeiro para RECOVERY para atualizar os mapeamentos de super."
ui_print "Sem garantia de boot ou recursos. O primeiro teste precisa de dados limpos e plano de restauracao."
ui_print "Nao foram gravados modem, bootloader, vbmeta, recovery, EFS ou userdata."
exit 0
