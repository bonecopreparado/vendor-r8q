"""Specialize the full-ROM writer for baked R2 firmware and direct readback."""
from pathlib import Path
from package_vendor_security import profile


def upgrade(script):
    rows='\n'.join(r['name']+' '+r['sha256']for r in profile()['stock'])
    anchor='ui_print "Single ZIP: native 64-bit stored-member reader is ready."\n'
    if script.count(anchor)!=1:raise ValueError('Native bootstrap anchor changed')
    guard='''STOCK_MOUNTED=0
p1r5_cleanup() {
    result=$?
    trap - EXIT HUP INT TERM
    if [ "$STOCK_MOUNTED" = 1 ]; then
        umount "$WORK/stock-fw" || { ui_print "ERROR: temporary read-only firmware mount could not be released."; result=1; }
    fi
    for name in zipread probe flush-check payload.rows stock.rows direct-probe; do rm -f "$WORK/$name" || result=1; done
    if [ -d "$WORK/stock-fw" ]; then rmdir "$WORK/stock-fw" 2>/dev/null || result=1; fi
    rmdir "$WORK" 2>/dev/null || result=1
    exit "$result"
}
trap p1r5_cleanup EXIT
trap 'exit 1' HUP INT TERM
for tool in mount mkdir; do command -v "$tool" >/dev/null 2>&1 || abort "Missing recovery tool: $tool. Nothing was written."; done
[ "$("$ZIPREAD" --block-io-version)" = R8Q_BLOCK_IO_DIRECT_V1 ] || abort "Expected production direct-I/O helper. Nothing was written."
APNHLOS_REAL="$(readlink -f /dev/block/bootdevice/by-name/apnhlos)" || abort "Cannot resolve APNHLOS. Nothing was written."
[ -b "$APNHLOS_REAL" ] || abort "APNHLOS block device unavailable. Nothing was written."
mkdir "$WORK/stock-fw" || abort "Cannot create temporary firmware mount. Nothing was written."
mount -t vfat -o ro "$APNHLOS_REAL" "$WORK/stock-fw" || abort "Cannot read stock firmware. Nothing was written."
STOCK_MOUNTED=1
stock_row="$(awk -v p="$WORK/stock-fw" '$2==p {print $1,$3,$4;n++} END {if(n!=1)exit 1}' /proc/mounts)" || abort "Cannot verify firmware mount. Nothing was written."
set -- $stock_row
[ "$#" -eq 3 ] && [ "$(readlink -f "$1")" = "$APNHLOS_REAL" ] && [ "$2" = vfat ] || abort "Unexpected firmware mount. Nothing was written."
case ",$3," in *,ro,*) ;; *) abort "Stock firmware must remain read-only. Nothing was written.";; esac
printf '%s\n' '@@STOCK@@' > "$WORK/stock.rows"
while read -r file expected; do
    stock_path=$WORK/stock-fw/image/$file
    [ -f "$stock_path" ] && [ ! -L "$stock_path" ] || abort "Missing stock firmware: $file. Nothing was written."
    actual="$(sha256sum "$stock_path" | awk '{print $1}')" || abort "Cannot hash stock firmware. Nothing was written."
    [ "$actual" = "$expected" ] || abort "Stock firmware differs: $file ($actual). Nothing was written; send recovery.log."
done < "$WORK/stock.rows"
umount "$WORK/stock-fw" || abort "Cannot release firmware preflight mount. Nothing was written."
STOCK_MOUNTED=0
ui_print "P1r5: Samsung firmware profile matches; R2 is already baked into Vendor."
'''.replace('@@STOCK@@',rows)
    script=script.replace(anchor,anchor+guard)
    start=script.index('verify_written() (')
    end=script.index('# Resolve target devices through sysfs',start)
    function='''verify_written() (
    wanted="$1"
    device="$(readlink -f "$2")" || abort "Cannot resolve fresh readback target; restore the base."
    "$ZIPREAD" --flush-block "$device" || abort "Write flush/cache invalidation failed; restore the base."
    cursor_blocks=0
    while read -r part name rawbytes rawsha cbytes csha offset readbacksha; do
        [ "$part" = "$wanted" ] || continue
        offset_blocks="$(awk -v value="$offset" 'BEGIN {printf "%.0f",value/4096}')" || abort "Invalid readback offset."
        [ "$offset_blocks" -eq "$cursor_blocks" ] || abort "Readback order differs; restore the base."
        start="$offset"; length="$rawbytes"
        if [ "$part" = super ] && [ "$offset" = 0 ]; then start=4096; length=$((rawbytes-4096)); fi
        ui_print "Fresh storage readback: $name..."
        got="$("$ZIPREAD" --read-block "$device" "$start" "$length" | hash_stream)" || abort "Direct readback failed: $name; restore the base."
        [ "${got%% *}" = "$readbacksha" ] || abort "Stored hash differs: $name; restore the base."
        cursor_blocks=$((cursor_blocks+rawbytes/4096))
    done < "$WORK/payload.rows"
    [ "$cursor_blocks" -gt 0 ] || abort "No readback chunks; restore the base."
)
'''
    script=script[:start]+function+script[end:]
    anchor='# Hashing and storage checks can take minutes; measure the battery again.\n'
    if script.count(anchor)!=1:raise ValueError('Pre-write anchor differs')
    preflight='''# Exercise flush permissions and aligned O_DIRECT on actual unmounted targets
# before writing any image. Unsupported recovery/kernel combinations abort here.
for target in "$SUPER" "$BOOT" "$DTBO"; do
    canonical="$(readlink -f "$target")" || abort "Cannot resolve target. Nothing was written."
    "$ZIPREAD" --flush-block "$canonical" || abort "Target flush is unsupported. Nothing was written."
    "$ZIPREAD" --read-block "$canonical" 0 4096 > "$WORK/direct-probe" || abort "Direct target reads are unsupported. Nothing was written."
    [ "$(wc -c < "$WORK/direct-probe")" -eq 4096 ] || abort "Short direct target probe. Nothing was written."
done
'''
    script=script.replace(anchor,preflight+anchor)
    old='''prefix_after="$(dd if="$SUPER" bs=1 count=4096 2>/dev/null | sha256sum | awk '{print $1}')" || abort "Falha ao reler prefixo super."
[ "$prefix_after" = "$prefix_before" ] || abort "Prefixo super mudou; restaure a base."
verify_written super "$SUPER"'''
    new='''verify_written super "$SUPER"
super_real="$(readlink -f "$SUPER")" || abort "Cannot resolve Super after writing."
prefix_after="$("$ZIPREAD" --read-block "$super_real" 0 4096 | hash_stream)" || abort "Cannot reread preserved Super prefix."
[ "${prefix_after%% *}" = "$prefix_before" ] || abort "Super prefix changed; restore the base."'''
    if script.count(old)!=1:raise ValueError('Super prefix readback anchor differs')
    return script.replace(old,new)
