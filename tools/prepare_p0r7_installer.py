"""P0r7: keep byte offsets out of mksh's signed 32-bit arithmetic/tests."""
from pathlib import Path
import argparse
import subprocess


def generate(root):
    source = root / 'delivery/Revisao-P0r6-Windows/p0r6-assets/installer-template.sh'
    dest = root / 'delivery/Revisao-P0r7-Windows/p0r7-assets/installer-template.sh'
    s = source.read_text()
    s = s.replace('P0r6', 'P0r7').replace('p0r6', 'p0r7').replace('P0R6', 'P0R7')
    old = '''    cursor=0
    while read -r part name rawbytes rawsha cbytes csha offset readbacksha; do
        if [ "$part" != "$wanted" ]; then continue; fi
        [ "$offset" -eq "$cursor" ] || abort "Ordem de leitura invalida; restaure a base."
'''
    new = '''    # Counter units are 4KiB blocks: entire super is only 2512896 blocks.
    # Byte offsets may exceed 2/4/8GiB and MUST NOT enter shell integer tests.
    cursor_blocks=0
    while read -r part name rawbytes rawsha cbytes csha offset readbacksha; do
        if [ "$part" != "$wanted" ]; then continue; fi
        offset_blocks="$(awk -v value="$offset" 'BEGIN { printf "%.0f", value/4096 }')" || abort "Falha ao converter offset; restaure a base."
        [ "$offset_blocks" -eq "$cursor_blocks" ] || abort "Ordem de leitura invalida; restaure a base."
'''
    assert old in s
    s = s.replace(old, new)
    s = s.replace('[ "$offset" -eq 0 ]', '[ "$offset" = 0 ]')
    s = s.replace('cursor=$((cursor+rawbytes))', 'cursor_blocks=$((cursor_blocks+rawbytes/4096))')
    s = s.replace('[ "$cursor" -gt 0 ]', '[ "$cursor_blocks" -gt 0 ]')
    # Explain the actual failures: our caller passed a negative skip in P0r5;
    # the numeric offset test in P0r6 re-entered the prefix branch at 4GiB.
    s = s.replace('''# A shared descriptor advances sequentially. Each dd processes <=512MiB and
# never computes skip*bs at/above 2GiB (broken on the observed recovery dd).
''', '''# A shared descriptor advances sequentially; dd processes <=512MiB per call.
# mksh integer arithmetic/tests wrap at 32 bits even on a 64-bit platform.
# Use string equality for offset zero, AWK for byte offsets, small block counters.
''')
    marker = '[ "$row_count" -eq 22 ] || abort "Tabela de partes incompleta."'
    assert marker in s
    validation = r'''
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
'''
    s = s.replace(marker, marker + '\n' + validation)
    # Informational only: P0r7 works with both arithmetic widths.
    probe = '''# This is a diagnostic, not an assumption that the shell is 64-bit.
shell_arith_probe=$((2147483647+1))
ui_print "Aritmetica do shell (diagnostico): 2147483647+1=$shell_arith_probe"
'''
    s = s.replace('ui_print "HyperOS4 -> R8Q P0r7 EXPERIMENTAL / sem teste de boot"',
                  'ui_print "HyperOS4 -> R8Q P0r7 EXPERIMENTAL / sem teste de boot"\n' + probe)
    assert '[ "$offset" -eq' not in s and 'cursor+rawbytes' not in s
    assert 'start/4096' not in s
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(s)
    subprocess.run(['bash', '-n', str(dest)], check=True)
    print(dest)
    return dest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    generate(parser.parse_args().root)
