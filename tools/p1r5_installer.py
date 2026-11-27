"""Specialize the full-ROM writer for baked R2 firmware, G780G/G781B APNHLOS sync and direct readback."""
from pathlib import Path
from package_vendor_security import profile

# Verified SM-G780G (G780GXXSHEYJ1) APNHLOS IPA hashes from TheMuppets r8q/sm8250-common.
# Immutable code segments ipa_fws.b00/b02/b03/b04 are byte-identical to G781BXXSIHYJ2.
G780G_EYJ1_STOCK = (
    ('ipa_fws.b01', '927354814bdad5f3e2a5f4bdfcea90cebb501af4c8c6a91563cd3d4d645d8a90'),
    ('ipa_fws.mdt', 'ad259724b647ab1c3eb5c45bcd282206bfb552a8f0274adb586cbea9e560becf'),
    ('ipa_uc.b00', 'e5e337f396e3d27e4ecf6306c1edd5268a9f58f4c89476f5c39d15b39bb52214'),
    ('ipa_uc.b01', '304cf15fbecf6f97530b78961bf8cf203aa81fdef9b3cd0637a6f34fe0998cf7'),
    ('ipa_uc.b02', '546ba47b9407b94a866d12c526d5343d88a6e8cb6b8039664b7b88f2ff5a9668'),
    ('ipa_uc.mdt', '44334668c52393d6050942876fde275bc623db195ce84365ab50177f36ec7951'),
)


def upgrade(script):
    rows='\n'.join(r['name']+' '+r['sha256']for r in profile()['stock'])
    rows_g780g='\n'.join(name+' '+digest for name,digest in G780G_EYJ1_STOCK)
    anchor='ui_print "Single ZIP: native 64-bit stored-member reader is ready."\n'
    if script.count(anchor)!=1:raise ValueError('Native bootstrap anchor changed')
    guard='''STOCK_MOUNTED=0
VENDOR_SYNC_MOUNTED=0
IPA_SYNC_NEEDED=0
p1r5_cleanup() {
    result=$?
    trap - EXIT HUP INT TERM
    if [ "$VENDOR_SYNC_MOUNTED" = 1 ]; then
        umount "$WORK/vendor-sync" || { ui_print "ERROR: temporary vendor sync mount could not be released."; result=1; }
    fi
    if [ "$STOCK_MOUNTED" = 1 ]; then
        umount "$WORK/stock-fw" || { ui_print "ERROR: temporary read-only firmware mount could not be released."; result=1; }
    fi
    for name in zipread probe flush-check payload.rows stock.rows stock-g780g.rows direct-probe; do rm -f "$WORK/$name" || result=1; done
    if [ -d "$WORK/apnhlos-sync" ]; then rm -rf "$WORK/apnhlos-sync" || result=1; fi
    if [ -d "$WORK/vendor-sync" ]; then rmdir "$WORK/vendor-sync" 2>/dev/null || result=1; fi
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
printf '%s\n' '@@STOCK_G780G@@' > "$WORK/stock-g780g.rows"
check_stock_profile() {
    rows_file="$1"
    MISMATCH_FILE=""
    MISMATCH_ACTUAL=""
    while read -r file expected; do
        stock_path=$WORK/stock-fw/image/$file
        [ -f "$stock_path" ] && [ ! -L "$stock_path" ] || abort "Missing stock firmware: $file. Nothing was written."
        actual="$(sha256sum "$stock_path" | awk '{print $1}')" || abort "Cannot hash stock firmware. Nothing was written."
        if [ "$actual" != "$expected" ]; then
            MISMATCH_FILE="$file"
            MISMATCH_ACTUAL="$actual"
            return 1
        fi
    done < "$rows_file"
    return 0
}
if check_stock_profile "$WORK/stock.rows"; then
    IPA_SYNC_NEEDED=0
    IPA_PROFILE_NOTE="R2 is already baked into Vendor."
elif check_stock_profile "$WORK/stock-g780g.rows"; then
    IPA_SYNC_NEEDED=1
    IPA_PROFILE_NOTE="G780G Vendor IPA will sync from read-only APNHLOS."
    mkdir "$WORK/apnhlos-sync" || abort "Cannot stage G780G stock firmware. Nothing was written."
    while read -r file expected; do
        cp "$WORK/stock-fw/image/$file" "$WORK/apnhlos-sync/$file" || abort "Cannot stage stock firmware: $file. Nothing was written."
        staged_sha="$(sha256sum "$WORK/apnhlos-sync/$file" | awk '{print $1}')" || abort "Cannot verify staged firmware: $file. Nothing was written."
        [ "$staged_sha" = "$expected" ] || abort "Staged stock firmware differs: $file. Nothing was written."
    done < "$WORK/stock-g780g.rows"
else
    abort "Stock firmware differs: $MISMATCH_FILE ($MISMATCH_ACTUAL). Nothing was written; send recovery.log."
fi
umount "$WORK/stock-fw" || abort "Cannot release firmware preflight mount. Nothing was written."
STOCK_MOUNTED=0
ui_print "P1r5: Samsung firmware profile matches; $IPA_PROFILE_NOTE"
'''.replace('@@STOCK@@',rows).replace('@@STOCK_G780G@@',rows_g780g)
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
[ "${prefix_after%% *}" = "$prefix_before" ] || abort "Super prefix changed; restore the base."
if [ "$IPA_SYNC_NEEDED" = 1 ]; then
    ui_print "P1r5: Syncing verified G780G stock IPA firmware into logical Vendor..."
    VENDOR_DM=""
    for dm_name in /sys/block/dm-*/dm/name; do
        [ -r "$dm_name" ] || continue
        if [ "$(cat "$dm_name")" = vendor ]; then
            dm_dev="/dev/block/$(basename "$(dirname "$(dirname "$dm_name")")")"
            [ -b "$dm_dev" ] && VENDOR_DM="$dm_dev" && break
        fi
    done
    [ -n "$VENDOR_DM" ] || [ ! -e /dev/block/mapper/vendor ] || VENDOR_DM="$(readlink -f /dev/block/mapper/vendor)"
    [ -n "$VENDOR_DM" ] && [ -b "$VENDOR_DM" ] || abort "Cannot locate logical Vendor block device for G780G IPA sync."
    mkdir "$WORK/vendor-sync" || abort "Cannot create temporary Vendor mount for G780G IPA sync."
    mount -t ext4 -o rw "$VENDOR_DM" "$WORK/vendor-sync" || abort "Cannot mount logical Vendor for G780G IPA sync."
    VENDOR_SYNC_MOUNTED=1
    while read -r file expected; do
        dest="$WORK/vendor-sync/firmware/$file"
        cp "$WORK/apnhlos-sync/$file" "$dest" || abort "Cannot write G780G IPA firmware: $file."
        chmod 0644 "$dest" || abort "Cannot chmod G780G IPA firmware: $file."
        chown 0:0 "$dest" 2>/dev/null || true
        chcon u:object_r:vendor_firmware_file:s0 "$dest" 2>/dev/null || true
        actual="$(sha256sum "$dest" | awk '{print $1}')" || abort "Cannot verify written G780G IPA firmware: $file."
        [ "$actual" = "$expected" ] || abort "Written G780G IPA firmware hash differs: $file."
    done < "$WORK/stock-g780g.rows"
    sync
    umount "$WORK/vendor-sync" || abort "Cannot unmount logical Vendor after G780G IPA sync."
    VENDOR_SYNC_MOUNTED=0
    ui_print "P1r5: Verified G780G IPA firmware synced to Vendor."
fi'''
    if script.count(old)!=1:raise ValueError('Super prefix readback anchor differs')
    return script.replace(old,new)

