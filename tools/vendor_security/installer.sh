#!/sbin/sh
# Recovery-only, cumulative firmware and file-label repair for the reviewed P1r4.
set -eu
set -o pipefail
umask 077
[ "$#" -eq 3 ] || exit 1
OUTFD=$2
case "$OUTFD" in ''|*[!0-9]*) exit 1;; esac
ui() { printf 'ui_print %s\nui_print\n' "$*" > "/proc/self/fd/$OUTFD"; }
abort() { ui "ERROR: $*"; exit 1; }
file_sha256() { sha256sum "$1" | awk '{print $1}'; }
DATA='@@DATA@@'
STOCK='@@STOCK@@'
IMMUTABLE='@@IMMUTABLE@@'
LABELS='@@LABELS@@'
FILES="$(printf '%s\n' "$DATA" | awk '{print $1}')"
LABEL_FILES="$(printf '%s\n' "$LABELS" | awk '{print $1}')"
old_digest() { printf '%s\n' "$DATA" | awk -v f="$1" '$1==f {print $2;n++} END {if(n!=1)exit 1}'; }
new_digest() { printf '%s\n' "$DATA" | awk -v f="$1" '$1==f {print $3;n++} END {if(n!=1)exit 1}'; }
expected_label() { printf '%s\n' "$LABELS" | awk -v f="$1" '$1==f {print $3;n++} END {if(n!=1)exit 1}'; }
label_digest() { printf '%s\n' "$LABELS" | awk -v f="$1" '$1==f {print $2;n++} END {if(n!=1)exit 1}'; }
get_label() {
    ls -dZ "$1" | awk '{for(i=1;i<=NF;i++)if($i ~ /^u:object_r:[A-Za-z0-9_]+:s0$/){print $i;n++}} END {if(n!=1)exit 1}'
}
allowed_data() { [ "$2" = "$(old_digest "$1")" ] || [ "$2" = "$(new_digest "$1")" ]; }
allowed_label() {
    [ "$2" = "$(expected_label "$1")" ] && return 0
    if [ "$1" = . ]; then [ "$2" = u:object_r:vendor_apex_file:s0 ]
    else [ "$2" = u:object_r:vendor_configs_file:s0 ] || [ "$2" = u:object_r:vendor_file:s0 ]; fi
}
backup_digest() { awk -v f="$1" 'NF==2 && $2==f {print $1;n++} END {if(n!=1)exit 1}' "$BACKUP/sha256.txt"; }
backup_label() { awk -v f="$1" 'NF==2 && $1==f {print $2;n++} END {if(n!=1)exit 1}' "$BACKUP/labels.txt"; }
WORK=; VMP=; STOCK_MOUNTED=0; VENDOR_OWNED=0; REMOUNTED=0
STAGE=; BACKUP_STAGE=; BACKUP=; CHANGED=; RELABELED=; SUCCESS=0
rollback() {
    # Restore labels before files, retaining the verified original backup.
    for relative in $RELABELED; do
        context="$(backup_label "$relative")" || return 1
        chcon "$context" "$VMP/$relative" || return 1
    done
    for file in $CHANGED; do
        cp -p "$BACKUP/$file" "$STAGE/restore-$file" || return 1
        context="$(get_label "$BACKUP/$file")" || return 1
        chcon "$context" "$STAGE/restore-$file" || return 1
        [ "$(file_sha256 "$STAGE/restore-$file")" = "$(backup_digest "$file")" ] || return 1
        mv -f "$STAGE/restore-$file" "$VMP/firmware/$file" || return 1
    done
    sync || return 1
    for relative in $RELABELED; do
        [ "$(get_label "$VMP/$relative")" = "$(backup_label "$relative")" ] || return 1
    done
    for file in $CHANGED; do
        [ "$(file_sha256 "$VMP/firmware/$file")" = "$(backup_digest "$file")" ] || return 1
    done
}
cleanup() {
    result=$?
    trap - EXIT
    if [ "$SUCCESS" != 1 ] && { [ -n "$CHANGED" ] || [ -n "$RELABELED" ]; }; then
        if rollback; then ui 'Pre-installation firmware and labels restored.'
        else ui 'ERROR: rollback failed. Remain in recovery; send recovery.log. Backup retained.'; result=1; fi
    fi
    if [ "$STOCK_MOUNTED" = 1 ]; then
        umount "$WORK/apnhlos" || { ui 'ERROR: temporary APNHLOS unmount failed.'; result=1; }
    fi
    for directory in "$STAGE" "$BACKUP_STAGE"; do
        [ -n "$directory" ] || continue
        for file in $FILES; do rm -f "$directory/$file" "$directory/restore-$file" || result=1; done
        rm -f "$directory/sha256.txt" "$directory/labels.txt" || result=1
        rmdir "$directory" 2>/dev/null || result=1
    done
    if [ "$REMOUNTED" = 1 ]; then
        mount -o remount,ro "$VMP" || { ui 'ERROR: Vendor read-only remount failed. Reboot recovery.'; result=1; }
    fi
    if [ "$VENDOR_OWNED" = 1 ]; then
        umount "$VMP" || { ui 'ERROR: temporary Vendor unmount failed.'; result=1; }
    fi
    if [ -n "$WORK" ]; then
        for file in $FILES; do rm -f "$WORK/$file" || result=1; done
        rmdir "$WORK/apnhlos" "$WORK/vendor" "$WORK" 2>/dev/null || result=1
    fi
    if [ "$SUCCESS" = 1 ] && [ "$result" = 0 ]; then
        ui 'R8Q security R2 applied: Samsung IPA and Vendor labels verified.'
        ui 'Reboot recovery first, then System once. Hardware boot remains unconfirmed.'
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
for tool in getprop id awk cat basename readlink stat sha256sum mktemp mount umount mkdir cp dd chmod chown chcon ls mv rm rmdir sync df; do
    command -v "$tool" >/dev/null 2>&1 || abort "Missing recovery tool: $tool"
done
[ "$(id -u)" = 0 ] || abort 'Recovery root required.'
[ "$(getprop ro.product.device)" = r8q ] || abort 'Only Snapdragon r8q.'
case "$(getprop ro.bootloader)" in G780G*|G781B*) ;; *) abort 'Unsupported bootloader family.';; esac
if [ "$(getprop ro.bootmode)" != recovery ] && [ "$(getprop ro.orangefox.boot)" != 1 ]; then
    [ "$(getprop ro.twrp.boot)" = 1 ] && [ "$(getprop init.svc.recovery)" = running ] &&
    [ "$(getprop ro.twrp.fastbootd)" != 1 ] || abort 'Return to TWRP or OrangeFox recovery.'
fi
capacity="$(cat /sys/class/power_supply/battery/capacity)" || abort 'Cannot read battery charge.'
case "$capacity" in ''|*[!0-9]*) abort 'Invalid battery reading.';; esac
[ "$capacity" -le 100 ] || abort 'Invalid battery reading.'
if [ "$capacity" -lt 50 ]; then
    status="$(cat /sys/class/power_supply/battery/status)" || abort 'Cannot read charging state.'
    case "$status" in Charging|Full) ;; *) abort 'Charge to 50 percent or connect a charger.';; esac
fi
WORK="$(mktemp -d /tmp/r8q-security.XXXXXX)"
mkdir "$WORK/vendor" "$WORK/apnhlos"
row="$(awk '$2=="/vendor" {print $1,$3,$4;n++} END {if(n!=1)exit 1}' /proc/mounts)" || row=
if [ -n "$row" ]; then
    VMP=/vendor
else
    block=; count=0
    for entry in /sys/class/block/dm-*; do
        [ -r "$entry/dm/name" ] || continue
        [ "$(cat "$entry/dm/name")" = vendor ] || continue
        block="/dev/block/${entry##*/}"; count=$((count+1))
    done
    [ "$count" = 1 ] && [ -b "$block" ] || abort 'Cannot identify logical Vendor. Mount Vendor in recovery first.'
    VMP=$WORK/vendor
    mount -t ext4 -o ro "$block" "$VMP" || abort 'Cannot mount logical Vendor read-only.'
    VENDOR_OWNED=1
    row="$(awk -v p="$VMP" '$2==p {print $1,$3,$4;n++} END {if(n!=1)exit 1}' /proc/mounts)" || abort 'Cannot verify temporary Vendor mount.'
fi
set -- $row
SOURCE=$1; OPTIONS=$3
[ "$2" = ext4 ] || abort 'Expected ext4 Vendor.'
node="$(basename "$(readlink -f "$SOURCE")")"
[ "$(cat "/sys/class/block/$node/dm/name")" = vendor ] || abort 'Mounted device is not logical Vendor.'
vendor_dev="$(stat -c '%d' "$VMP")"
[ -f "$VMP/etc/init/hw/init.qcom.rc" ] && [ ! -L "$VMP/etc/init/hw/init.qcom.rc" ] || abort 'Reviewed init is absent.'
[ "$(file_sha256 "$VMP/etc/init/hw/init.qcom.rc")" = @@INIT_SHA@@ ] || abort 'This is not the reviewed P1 Vendor.'
[ -d "$VMP/firmware" ] && [ ! -L "$VMP/firmware" ] &&
[ "$(stat -c '%d' "$VMP/firmware")" = "$vendor_dev" ] || abort 'Unexpected firmware directory.'
pending=0
while read -r file expected; do
    path=$VMP/firmware/$file
    [ -f "$path" ] && [ ! -L "$path" ] && [ "$(file_sha256 "$path")" = "$expected" ] || abort 'Unchanged IPA code differs.'
done <<EOF_IMMUTABLE
$IMMUTABLE
EOF_IMMUTABLE
for file in $FILES; do
    path=$VMP/firmware/$file
    [ -f "$path" ] && [ ! -L "$path" ] && [ "$(stat -c '%d' "$path")" = "$vendor_dev" ] || abort "Unexpected firmware file: $file"
    [ "$(stat -c '%u:%g:%a' "$path")" = 0:0:644 ] || abort "Unexpected firmware metadata: $file"
    actual="$(file_sha256 "$path")"
    allowed_data "$file" "$actual" || abort "Unknown firmware content: $file"
    [ "$actual" = "$(new_digest "$file")" ] || pending=1
    get_label "$path" >/dev/null || abort 'Cannot read original firmware labels.'
done
for relative in $LABEL_FILES; do
    path=$VMP/$relative
    [ ! -L "$path" ] && [ "$(stat -c '%d' "$path")" = "$vendor_dev" ] || abort 'Label target escapes Vendor.'
    if [ "$relative" = . ]; then
        [ -d "$path" ] && [ "$(stat -c '%u:%a' "$path")" = 0:755 ] || abort 'Unexpected Vendor root metadata.'
    else
        [ -f "$path" ] && [ "$(file_sha256 "$path")" = "$(label_digest "$relative")" ] || abort "Context file differs: $relative"
        [ "$(stat -c '%u:%g:%a' "$path")" = 0:0:644 ] || abort "Unexpected context-file ownership/mode: $relative"
    fi
    actual="$(get_label "$path")" || abort "Cannot read label: $relative"
    allowed_label "$relative" "$actual" || abort "Unreviewed original label: $relative"
    [ "$actual" = "$(expected_label "$relative")" ] || pending=1
done
BACKUP=$VMP/firmware/.r8q-security-r2-backup
if [ -e "$BACKUP" ] || [ -L "$BACKUP" ]; then
    [ -d "$BACKUP" ] && [ ! -L "$BACKUP" ] && [ "$(stat -c '%d' "$BACKUP")" = "$vendor_dev" ] || abort 'Unexpected backup directory.'
    for file in sha256.txt labels.txt; do [ -f "$BACKUP/$file" ] && [ ! -L "$BACKUP/$file" ] || abort 'Missing backup manifest.'; done
    [ "$(awk 'NF!=2 {bad=1} END {if(bad)exit 1;print NR}' "$BACKUP/sha256.txt")" = 8 ] &&
    [ "$(awk 'NF!=2 {bad=1} END {if(bad)exit 1;print NR}' "$BACKUP/labels.txt")" = 11 ] || abort 'Unexpected backup manifest shape.'
    for file in $FILES; do
        actual="$(backup_digest "$file")" || abort 'Invalid backup digest manifest.'
        allowed_data "$file" "$actual" && [ -f "$BACKUP/$file" ] && [ ! -L "$BACKUP/$file" ] &&
        [ "$(file_sha256 "$BACKUP/$file")" = "$actual" ] || abort 'Original firmware backup differs.'
    done
    for relative in $LABEL_FILES; do
        actual="$(backup_label "$relative")" || abort 'Invalid backup label manifest.'
        allowed_label "$relative" "$actual" || abort 'Original label backup differs.'
    done
fi
APNHLOS_REAL="$(readlink -f /dev/block/bootdevice/by-name/apnhlos)"
[ -b "$APNHLOS_REAL" ] || abort 'APNHLOS block device not found.'
mount -t vfat -o ro "$APNHLOS_REAL" "$WORK/apnhlos" || abort 'Cannot mount APNHLOS read-only.'
STOCK_MOUNTED=1
row="$(awk -v p="$WORK/apnhlos" '$2==p {print $1,$3,$4;n++} END {if(n!=1)exit 1}' /proc/mounts)" || abort 'Cannot verify temporary firmware mount.'
set -- $row
[ "$(readlink -f "$1")" = "$APNHLOS_REAL" ] && [ "$2" = vfat ] || abort 'Unexpected firmware mount.'
case ",$3," in *,ro,*) ;; *) abort 'APNHLOS must remain read-only.';; esac
while read -r file expected; do
    path=$WORK/apnhlos/image/$file
    [ -f "$path" ] && [ ! -L "$path" ] && [ "$(file_sha256 "$path")" = "$expected" ] || abort 'Stock firmware version differs. Nothing changed; send its hashes.'
    cat "$path" > "$WORK/$file"
done <<EOF_STOCK
$STOCK
EOF_STOCK
umount "$WORK/apnhlos" || abort 'Cannot release temporary firmware mount.'
STOCK_MOUNTED=0
if [ "$pending" = 0 ]; then ui 'Matching Samsung firmware and Vendor labels already installed.'; SUCCESS=1; exit 0; fi
cat "$VMP/firmware/ipa_fws.elf" > "$WORK/ipa_fws.elf"
dd if="$WORK/ipa_fws.b01" of="$WORK/ipa_fws.elf" bs=1 seek=4096 conv=notrunc 2>/dev/null || abort 'Cannot prepare IPA ELF.'
dd if=/dev/zero of="$WORK/ipa_uc.elf" bs=47500 count=1 2>/dev/null || abort 'Cannot allocate IPA UC ELF.'
dd if="$WORK/ipa_uc.b00" of="$WORK/ipa_uc.elf" bs=1 conv=notrunc 2>/dev/null || abort 'Cannot prepare IPA UC header.'
dd if="$WORK/ipa_uc.b01" of="$WORK/ipa_uc.elf" bs=1 seek=4096 conv=notrunc 2>/dev/null || abort 'Cannot prepare IPA UC authentication.'
dd if="$WORK/ipa_uc.b02" of="$WORK/ipa_uc.elf" bs=1 seek=12288 conv=notrunc 2>/dev/null || abort 'Cannot prepare IPA UC code.'
for file in $FILES; do [ "$(file_sha256 "$WORK/$file")" = "$(new_digest "$file")" ] || abort 'Prepared firmware differs.'; done
available="$(df -Pk "$VMP" | awk 'NR==2 {print $4}')"
case "$available" in ''|*[!0-9]*) abort 'Cannot determine Vendor free space.';; esac
[ "$available" -ge 2048 ] || abort 'Need 2 MiB free in Vendor for staging and backup.'
case ",$OPTIONS," in *,rw,*) ;; *)
    mount -o remount,rw "$VMP" || abort 'Vendor writable remount failed. Nothing changed.'
    REMOUNTED=1;; esac
if [ ! -d "$BACKUP" ]; then
    BACKUP_STAGE="$(mktemp -d "$VMP/firmware/.r8q-security-backup.XXXXXX")"
    for file in $FILES; do
        cp -p "$VMP/firmware/$file" "$BACKUP_STAGE/$file"
        context="$(get_label "$VMP/firmware/$file")"; chcon "$context" "$BACKUP_STAGE/$file"
        actual="$(file_sha256 "$BACKUP_STAGE/$file")"
        [ "$actual" = "$(file_sha256 "$VMP/firmware/$file")" ] || abort 'Backup copy differs.'
        printf '%s %s\n' "$actual" "$file" >> "$BACKUP_STAGE/sha256.txt"
    done
    for relative in $LABEL_FILES; do printf '%s %s\n' "$relative" "$(get_label "$VMP/$relative")" >> "$BACKUP_STAGE/labels.txt"; done
    sync || abort 'Backup sync failed.'
    mv "$BACKUP_STAGE" "$BACKUP"; BACKUP_STAGE=
    sync || abort 'Backup directory sync failed.'
fi
STAGE="$(mktemp -d "$VMP/firmware/.r8q-security-stage.XXXXXX")"
for file in $FILES; do
    cat "$WORK/$file" > "$STAGE/$file"; chmod 0644 "$STAGE/$file"; chown 0:0 "$STAGE/$file"
    context="$(get_label "$VMP/firmware/$file")"; chcon "$context" "$STAGE/$file"
    [ "$(file_sha256 "$STAGE/$file")" = "$(new_digest "$file")" ] || abort 'Staged firmware differs.'
done
for file in $FILES; do CHANGED="$CHANGED $file"; mv -f "$STAGE/$file" "$VMP/firmware/$file" || abort 'Firmware activation failed.'; done
for relative in $LABEL_FILES; do
    actual="$(get_label "$VMP/$relative")"; expected="$(expected_label "$relative")"
    [ "$actual" != "$expected" ] || continue
    RELABELED="$RELABELED $relative"
    chcon "$expected" "$VMP/$relative" || abort "Label update failed: $relative"
done
sync || abort 'Firmware/label sync failed.'
for file in $FILES; do [ "$(file_sha256 "$VMP/firmware/$file")" = "$(new_digest "$file")" ] || abort 'Installed firmware differs.'; done
for relative in $LABEL_FILES; do [ "$(get_label "$VMP/$relative")" = "$(expected_label "$relative")" ] || abort 'Installed label differs.'; done
SUCCESS=1
ui 'Original files and label manifest retained in Vendor firmware/.r8q-security-r2-backup.'
