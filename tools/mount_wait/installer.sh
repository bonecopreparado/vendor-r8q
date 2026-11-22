#!/sbin/sh
# Exact P1r5 LATEFS boot-only diagnostic transaction.
set -eu
set -o pipefail
umask 077
[ "$#" -eq 3 ] || exit 1
OUTFD=$2
case "$OUTFD" in ''|*[!0-9]*) exit 1;; esac
ZIP=$3
ui() { printf 'ui_print %s\nui_print\n' "$*" > "/proc/self/fd/$OUTFD"; }
abort() { ui "ERROR: $*"; exit 1; }
file_sha() { sha256sum "$1" | awk '{print $1}'; }
FROM=@@FROM@@
TO=@@TO@@
COMPRESSED=@@COMPRESSED@@
HELPER_SHA=@@HELPER@@
ACTION=@@ACTION@@
WORK=
WRITE_STARTED=0
SUCCESS=0
read_boot_sha() { "$WORK/bootio" --read "$BOOT" | sha256sum | awk '{print $1}'; }

cleanup() {
    result=$?
    trap - EXIT HUP INT TERM
    if [ "$WRITE_STARTED" = 1 ] && [ "$SUCCESS" != 1 ]; then
        ui 'Restoring the exact verified previous boot...'
        if [ "$(file_sha "$WORK/before.img")" = "$FROM" ] &&
           "$WORK/bootio" --write "$WORK/before.img" "$BOOT" &&
           [ "$(read_boot_sha)" = "$FROM" ]; then
            ui 'Previous boot restored and verified.'
        else
            ui 'ERROR: boot restoration failed. Remain in recovery and preserve recovery.log.'
        fi
        result=1
    fi
    if [ -n "$WORK" ]; then
        for name in bootio payload.gz candidate.img before.img; do
            rm -f "$WORK/$name" || result=1
        done
        rmdir "$WORK" || result=1
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

for tool in getprop id cat awk readlink stat sha256sum mktemp unzip gzip chmod rm rmdir df; do
    command -v "$tool" >/dev/null 2>&1 || abort "Missing recovery tool: $tool"
done
[ "$(id -u)" = 0 ] || abort 'Recovery root required.'
[ "$(getprop ro.product.device)" = r8q ] || abort 'Only Snapdragon r8q.'
case "$(getprop ro.bootloader)" in
    G780G*|G781B*) ;;
    *) abort 'Unsupported bootloader family.';;
esac
if [ "$(getprop ro.bootmode)" != recovery ] && [ "$(getprop ro.orangefox.boot)" != 1 ]; then
    [ "$(getprop ro.twrp.boot)" = 1 ] && [ "$(getprop init.svc.recovery)" = running ] &&
    [ "$(getprop ro.twrp.fastbootd)" != 1 ] || abort 'Return to TWRP or OrangeFox recovery.'
fi
battery_guard() {
    capacity="$(cat /sys/class/power_supply/battery/capacity)" || abort 'Cannot read battery.'
    case "$capacity" in ''|*[!0-9]*) abort 'Invalid battery reading.';; esac
    [ "$capacity" -le 100 ] || abort 'Invalid battery reading.'
    if [ "$capacity" -lt 50 ]; then
        [ "$capacity" -ge 20 ] || abort 'Charge the battery above 20 percent.'
        case "$(cat /sys/class/power_supply/battery/status)" in
            Charging|Full) ;;
            *) abort 'Charge to 50 percent or connect a charger.';;
        esac
    fi
}
battery_guard
BOOT="$(readlink -f /dev/block/bootdevice/by-name/boot)" || abort 'Boot partition unavailable.'
[ -b "$BOOT" ] || abort 'Boot target must be a block device.'
mount_devices="$(awk '$1 ~ /^\/dev\// {print $1}' /proc/mounts)" || abort 'Cannot read recovery mounts.'
for device in $mount_devices; do
    mounted="$(readlink -f "$device")" || abort 'Cannot identify mounted device.'
    [ "$mounted" != "$BOOT" ] || abort 'Boot partition is mounted.'
done
free="$(df -Pk /tmp | awk 'NR>1 {n++;v=$4} END {if(n!=1)exit 1;print v}')" || abort 'Cannot read recovery RAM.'
case "$free" in ''|*[!0-9]*) abort 'Invalid recovery RAM reading.';; esac
[ "$free" -ge 196608 ] || abort 'At least 192 MiB free recovery RAM is required.'
WORK="$(mktemp -d /tmp/r8q-mount-wait.XXXXXX)"

unzip -p "$ZIP" tools/bootio > "$WORK/bootio" || abort 'Cannot extract boot I/O helper.'
[ "$(file_sha "$WORK/bootio")" = "$HELPER_SHA" ] || abort 'Boot helper hash mismatch.'
chmod 0700 "$WORK/bootio"
[ "$("$WORK/bootio" --version)" = R8Q_BOOTIO_PRODUCTION_BLOCK_ONLY_V1 ] || abort 'Wrong helper build mode.'
"$WORK/bootio" --check "$BOOT" || abort 'Boot must have exactly 64 MiB.'
"$WORK/bootio" --read "$BOOT" > "$WORK/before.img" || abort 'Direct source boot read failed.'
before="$(file_sha "$WORK/before.img")" || abort 'Cannot hash source boot.'
case "$before" in
    "$TO") ui "Requested boot is already installed ($ACTION)."; exit 0;;
    "$FROM") ;;
    *) abort 'Installed boot does not match the exact P1r5 LATEFS profile for this ZIP.';;
esac
unzip -p "$ZIP" images/boot.img.gz > "$WORK/payload.gz" || abort 'Cannot extract boot payload.'
[ "$(file_sha "$WORK/payload.gz")" = "$COMPRESSED" ] || abort 'Compressed payload hash mismatch.'
gzip -dc "$WORK/payload.gz" > "$WORK/candidate.img" || abort 'Boot payload decompression failed.'
[ "$(stat -c %s "$WORK/candidate.img")" = 67108864 ] &&
[ "$(file_sha "$WORK/candidate.img")" = "$TO" ] || abort 'Boot payload size or SHA-256 mismatch.'

battery_guard
[ "$(read_boot_sha)" = "$FROM" ] || abort 'Boot changed during preflight.'
ui "Writing and verifying the exact boot image ($ACTION)..."
WRITE_STARTED=1
"$WORK/bootio" --write "$WORK/candidate.img" "$BOOT" || abort 'Boot write failed.'
[ "$(read_boot_sha)" = "$TO" ] || abort 'Fresh direct boot readback differed.'
SUCCESS=1
ui "R8Q boot image verified ($ACTION). Reboot recovery, then System."
