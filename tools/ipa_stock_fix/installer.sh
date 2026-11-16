#!/sbin/sh
# Targeted recovery fix: use the authenticated IPA from this device's APNHLOS.
set -eu
set -o pipefail
umask 077
[ "$#" -eq 3 ] || exit 1
OUTFD=$2
case "$OUTFD" in ''|*[!0-9]*) exit 1;; esac
ui() { printf 'ui_print %s\nui_print\n' "$*" > "/proc/self/fd/$OUTFD"; }
abort() { ui "ERROR: $*"; exit 1; }
file_sha256() { sha256sum "$1" | awk '{print $1}'; }
old_hash() { case "$1" in
    ipa_fws.b01) echo f3185a8a9c39e3b7d6edc0c2bd1a1c7a58c0081150aa4c462c561ba89aa64e53;;
    ipa_fws.mdt) echo 49bd59c7d0189e06e0883fddaca5723ebe7d18906eaef2d6bd98e200355c6dbd;;
    ipa_fws.elf) echo bf08513983e01d9a331eba795e53a96adf0010fd41b65152ff1ec2e29843ebe8;;
    *) return 1;; esac; }
new_hash() { case "$1" in
    ipa_fws.b01) echo 8bc6bf3243e4a76cd18e5128cccf1cf1b7c6653ee228116d16b3b8e086cf8231;;
    ipa_fws.mdt) echo 0b2e4533de1cd1cbf81cdf4406926ea12139dbca83f07b6c3fce1bfc9a59ab05;;
    ipa_fws.elf) echo 94587aaebc7b9edc1935d929c7a0253ca3e35317337cc1359df0efcfa082e209;;
    *) return 1;; esac; }
label() {
    ls -dZ "$1" | awk '{for(i=1;i<=NF;i++)if($i ~ /^u:object_r:[A-Za-z0-9_]+:s0$/){print $i;n++}} END {if(n!=1)exit 1}'
}
FILES='ipa_fws.b01 ipa_fws.mdt ipa_fws.elf'
FW=/vendor/firmware
BACKUP=$FW/.r8q-ipa-p1r4-backup
WORK=; STAGE=; BACKUP_STAGE=; STOCK_MOUNTED=0; REMOUNTED=0; CHANGED=; SUCCESS=0
rollback() {
    for file in $CHANGED; do
        cp -p "$BACKUP/$file" "$STAGE/restore-$file" || return 1
        context="$(label "$BACKUP/$file")" || return 1
        chcon "$context" "$STAGE/restore-$file" || return 1
        [ "$(file_sha256 "$STAGE/restore-$file")" = "$(old_hash "$file")" ] || return 1
        mv -f "$STAGE/restore-$file" "$FW/$file" || return 1
    done
    sync || return 1
    for file in $CHANGED; do
        [ "$(file_sha256 "$FW/$file")" = "$(old_hash "$file")" ] || return 1
    done
}
cleanup() {
    result=$?
    trap - EXIT
    if [ "$SUCCESS" != 1 ] && [ -n "$CHANGED" ]; then
        if rollback; then ui 'Original IPA files restored after installation failure.'
        else ui 'ERROR: rollback failed. Remain in recovery; send recovery.log. Original backup retained.'; result=1; fi
    fi
    if [ "$STOCK_MOUNTED" = 1 ]; then
        if umount "$WORK/apnhlos"; then STOCK_MOUNTED=0
        else ui 'ERROR: temporary read-only firmware mount could not be released.'; result=1; fi
    fi
    for directory in "$STAGE" "$BACKUP_STAGE"; do
        [ -n "$directory" ] || continue
        for file in $FILES; do rm -f "$directory/$file" "$directory/restore-$file" || result=1; done
        rmdir "$directory" 2>/dev/null || result=1
    done
    if [ "$REMOUNTED" = 1 ]; then
        mount -o remount,ro /vendor || { ui 'ERROR: Vendor read-only remount failed; reboot recovery.'; result=1; }
    fi
    if [ -n "$WORK" ]; then
        for file in $FILES; do rm -f "$WORK/$file" || result=1; done
        if [ "$STOCK_MOUNTED" = 0 ]; then rmdir "$WORK/apnhlos" "$WORK" 2>/dev/null || result=1; fi
    fi
    if [ "$SUCCESS" = 1 ] && [ "$result" = 0 ]; then
        ui 'R8Q Samsung IPA stock fix applied and SHA256 verified.'
        ui 'Reboot recovery first, then System once. Boot success still needs testing.'
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
    status="$(cat /sys/class/power_supply/battery/status)" || abort 'Cannot read charging status.'
    case "$status" in Charging|Full) ;; *) abort 'Charge to 50 percent or connect a charger.';; esac
fi
row="$(awk '$2=="/vendor" {print $1,$3,$4;n++} END {if(n!=1)exit 1}' /proc/mounts)" || abort 'Mount Vendor in recovery first.'
set -- $row
SOURCE=$1; OPTIONS=$3
[ "$2" = ext4 ] || abort 'Expected ext4 Vendor.'
node="$(basename "$(readlink -f "$SOURCE")")"
[ "$(cat "/sys/class/block/$node/dm/name")" = vendor ] || abort 'Mounted partition is not logical Vendor.'
[ -f /vendor/etc/init/hw/init.qcom.rc ] && [ ! -L /vendor/etc/init/hw/init.qcom.rc ] || abort 'Missing reviewed Vendor init.'
[ "$(file_sha256 /vendor/etc/init/hw/init.qcom.rc)" = 9971fef6dfa6951ec593bd82351203deb71e6185a4eea5354fe2fef3912114ea ] || abort 'This is not the reviewed P1 Vendor.'
[ -d "$FW" ] && [ ! -L "$FW" ] || abort 'Unexpected firmware directory.'
vendor_dev="$(stat -c '%d' /vendor)"
[ "$(stat -c '%d' "$FW")" = "$vendor_dev" ] || abort 'Firmware directory is outside Vendor.'
for pair in 'ipa_fws.b00:6140bd155996ed6134a8d2403ae1f911554a2dfee71b82568bff5bbf90d84c22' 'ipa_fws.b02:75042a4ebd0835080c016bb9e22be738db863005bfbd57e230f654122e9ec1e1' 'ipa_fws.b03:14024088f436ebd24b097cb113b2177e12c939efdac0211d560c7cc498611507' 'ipa_fws.b04:08a996d4efe3ac0d4e4d8948d2a6bcc24fda5138c2e196f9568245fbafee62a3'; do
    file=${pair%%:*}; expected=${pair#*:}
    [ -f "$FW/$file" ] && [ ! -L "$FW/$file" ] || abort "Expected regular firmware: $file"
    [ "$(file_sha256 "$FW/$file")" = "$expected" ] || abort "IPA code differs: $file"
done
old_count=0
for file in $FILES; do
    [ -f "$FW/$file" ] && [ ! -L "$FW/$file" ] || abort "Unexpected IPA file: $file"
    [ "$(stat -c '%d' "$FW/$file")" = "$vendor_dev" ] || abort 'IPA file is outside Vendor.'
    [ "$(stat -c '%u:%g:%a' "$FW/$file")" = 0:0:644 ] || abort "Unexpected IPA ownership/mode: $file"
    context="$(label "$FW/$file")" || abort "Cannot read SELinux label: $file"
    actual="$(file_sha256 "$FW/$file")"
    if [ "$actual" = "$(old_hash "$file")" ]; then old_count=$((old_count+1))
    elif [ "$actual" != "$(new_hash "$file")" ]; then abort "Unknown IPA content: $file"; fi
done
if [ -e "$BACKUP" ] || [ -L "$BACKUP" ]; then
    [ -d "$BACKUP" ] && [ ! -L "$BACKUP" ] && [ "$(stat -c '%d' "$BACKUP")" = "$vendor_dev" ] || abort 'Unexpected backup directory.'
    for file in $FILES; do
        [ -f "$BACKUP/$file" ] && [ ! -L "$BACKUP/$file" ] &&
        [ "$(file_sha256 "$BACKUP/$file")" = "$(old_hash "$file")" ] || abort 'Existing original IPA backup differs.'
    done
elif [ "$old_count" != 3 ] && [ "$old_count" != 0 ]; then
    abort 'Partial IPA replacement without the original backup. Nothing changed.'
fi
WORK="$(mktemp -d /tmp/r8q-ipa.XXXXXX)" || abort 'Cannot create temporary directory.'
mkdir "$WORK/apnhlos"
APNHLOS_REAL="$(readlink -f /dev/block/bootdevice/by-name/apnhlos)"
[ -b "$APNHLOS_REAL" ] || abort 'APNHLOS block device not found.'
mount -t vfat -o ro "$APNHLOS_REAL" "$WORK/apnhlos" || abort 'Cannot mount APNHLOS read-only.'
STOCK_MOUNTED=1
row="$(awk -v p="$WORK/apnhlos" '$2==p {print $1,$3,$4;n++} END {if(n!=1)exit 1}' /proc/mounts)" || abort 'Cannot verify temporary firmware mount.'
set -- $row
[ "$(readlink -f "$1")" = "$APNHLOS_REAL" ] && [ "$2" = vfat ] || abort 'Unexpected temporary firmware mount.'
case ",$3," in *,ro,*) ;; *) abort 'Firmware partition must remain read-only.';; esac
for file in ipa_fws.b01 ipa_fws.mdt; do
    [ -f "$WORK/apnhlos/image/$file" ] && [ ! -L "$WORK/apnhlos/image/$file" ] || abort "Stock IPA absent: $file"
    [ "$(file_sha256 "$WORK/apnhlos/image/$file")" = "$(new_hash "$file")" ] || abort 'Stock IPA version differs from this reviewed fix. Send its hashes; nothing changed.'
    cat "$WORK/apnhlos/image/$file" > "$WORK/$file"
done
umount "$WORK/apnhlos" || abort 'Cannot release temporary firmware mount.'
STOCK_MOUNTED=0
if [ "$old_count" = 0 ]; then ui 'Matching Samsung IPA already installed.'; exit 0; fi
cat "$FW/ipa_fws.elf" > "$WORK/ipa_fws.elf"
dd if="$WORK/ipa_fws.b01" of="$WORK/ipa_fws.elf" bs=1 seek=4096 conv=notrunc 2>/dev/null || abort 'Cannot prepare the matching ELF.'
for file in $FILES; do [ "$(file_sha256 "$WORK/$file")" = "$(new_hash "$file")" ] || abort 'Prepared stock IPA hash differs.'; done
available="$(df -Pk /vendor | awk 'NR==2 {print $4}')"
case "$available" in ''|*[!0-9]*) abort 'Cannot determine Vendor free space.';; esac
[ "$available" -ge 1024 ] || abort 'Need at least 1 MiB free in Vendor for staging and backup.'
case ",$OPTIONS," in *,rw,*) ;; *)
    mount -o remount,rw /vendor || abort 'Vendor writable remount failed. Nothing changed.'
    REMOUNTED=1;; esac
if [ ! -d "$BACKUP" ]; then
    BACKUP_STAGE="$(mktemp -d "$FW/.r8q-ipa-backup.XXXXXX")"
    for file in $FILES; do
        cp -p "$FW/$file" "$BACKUP_STAGE/$file"
        context="$(label "$FW/$file")"; chcon "$context" "$BACKUP_STAGE/$file"
        [ "$(file_sha256 "$BACKUP_STAGE/$file")" = "$(old_hash "$file")" ] || abort 'Original backup hash differs.'
    done
    sync || abort 'Backup sync failed.'
    mv "$BACKUP_STAGE" "$BACKUP"; BACKUP_STAGE=
    sync || abort 'Backup directory sync failed.'
fi
STAGE="$(mktemp -d "$FW/.r8q-ipa-stage.XXXXXX")"
for file in $FILES; do
    cat "$WORK/$file" > "$STAGE/$file"
    chmod 0644 "$STAGE/$file"; chown 0:0 "$STAGE/$file"
    context="$(label "$FW/$file")"; chcon "$context" "$STAGE/$file"
    [ "$(file_sha256 "$STAGE/$file")" = "$(new_hash "$file")" ] || abort 'Staged IPA hash differs.'
done
for file in $FILES; do
    CHANGED="$CHANGED $file"
    mv -f "$STAGE/$file" "$FW/$file" || abort 'IPA replacement failed.'
done
sync || abort 'IPA sync failed.'
for file in $FILES; do [ "$(file_sha256 "$FW/$file")" = "$(new_hash "$file")" ] || abort 'Installed IPA hash differs.'; done
SUCCESS=1
ui 'Original IPA backup retained in /vendor/firmware/.r8q-ipa-p1r4-backup.'
