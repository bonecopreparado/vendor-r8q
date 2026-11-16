#!/sbin/sh
# Exact P1r4 only. Cumulative R2 repair plus independently verified kernel.
set -eu
set -o pipefail
umask 077
[ "$#" -eq 3 ] || exit 1
OUTFD=$2
case "$OUTFD" in ''|*[!0-9]*) exit 1;; esac
ZIP=$3
ui() { printf 'ui_print %s\nui_print\n' "$*" > "/proc/self/fd/$OUTFD"; }
abort() { ui "ERROR: $*"; exit 1; }
file_sha256() { sha256sum "$1" | awk '{print $1}'; }
ORIGINAL=cb9c55af64889209eafe2c078b349b533b6728146fb859c731ba23067fdf18a6
CANDIDATE=@@BOOT_SHA@@
GZIP_SHA=@@GZIP_SHA@@
HELPER_SHA=@@HELPER_SHA@@
SECURITY_SHA=@@SECURITY_SHA@@
WORK=; BACKUP_STAGE=; WRITE_STARTED=0; SUCCESS=0
BACKUP=/data/r8q-boot-backups
BACKUP_FILE=$BACKUP/P1r4-$ORIGINAL.img
cleanup() {
    result=$?
    trap - EXIT HUP INT TERM
    if [ "$WRITE_STARTED" = 1 ] && [ "$SUCCESS" != 1 ]; then
        ui 'Restoring the verified original boot backup...'
        if "$WORK/bootio" --write "$BACKUP_FILE" "$BOOT" &&
           "$WORK/bootio" --read "$BOOT" > "$WORK/current.img" &&
           [ "$(file_sha256 "$WORK/current.img")" = "$ORIGINAL" ]; then
            ui 'Original boot restored and read back. Vendor R2 may remain applied.'
        else
            ui "ERROR: boot restoration failed. Remain in recovery. Backup: $BACKUP_FILE"
        fi
        result=1
    fi
    if [ -n "$BACKUP_STAGE" ]; then rm -f "$BACKUP_STAGE" || result=1; fi
    if [ -n "$WORK" ]; then
        for name in bootio boot.gz candidate.img current.img security.sh; do rm -f "$WORK/$name" || result=1; done
        rmdir "$WORK" || result=1
    fi
    if [ "$SUCCESS" = 1 ] && [ "$result" = 0 ]; then
        ui 'R8Q memory R3 applied: R2 and kernel verified.'
        ui 'Reboot recovery first, then System once. Do not Format Data.'
        ui "Original boot backup: $BACKUP_FILE"
        ui 'This is experimental. Successful Android boot is unconfirmed.'
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
for tool in getprop id cat awk readlink stat sha256sum mktemp mkdir unzip gzip chmod cp mv rm rmdir df sh; do
    command -v "$tool" >/dev/null 2>&1 || abort "Missing recovery tool: $tool"
done
[ "$(id -u)" = 0 ] || abort 'Recovery root required.'
[ "$(getprop ro.product.device)" = r8q ] || abort 'Only Snapdragon r8q.'
case "$(getprop ro.bootloader)" in G780G*|G781B*) ;; *) abort 'Unsupported bootloader family.';; esac
if [ "$(getprop ro.bootmode)" != recovery ] && [ "$(getprop ro.orangefox.boot)" != 1 ]; then
    [ "$(getprop ro.twrp.boot)" = 1 ] && [ "$(getprop init.svc.recovery)" = running ] &&
    [ "$(getprop ro.twrp.fastbootd)" != 1 ] || abort 'Return to TWRP or OrangeFox recovery.'
fi
battery_guard() {
    capacity="$(cat /sys/class/power_supply/battery/capacity)" || abort 'Cannot read battery.'
    case "$capacity" in ''|*[!0-9]*) abort 'Invalid battery reading.';; esac
    [ "$capacity" -le 100 ] || abort 'Invalid battery reading.'
    if [ "$capacity" -lt 50 ]; then
        status="$(cat /sys/class/power_supply/battery/status)" || abort 'Cannot read charging state.'
        case "$status" in Charging|Full) ;; *) abort 'Charge to 50 percent or connect a charger.';; esac
    fi
}
battery_guard
BOOT="$(readlink -f /dev/block/bootdevice/by-name/boot)" || abort 'Boot partition unavailable.'
[ -b "$BOOT" ] || abort 'Boot target must be a block device.'
for mount_device in $(awk '{print $1}' /proc/mounts); do
    case "$mount_device" in /dev/*)
        mounted="$(readlink -f "$mount_device")" || abort 'Cannot identify mounted device.'
        [ "$mounted" != "$BOOT" ] || abort 'Boot partition is mounted.';;
    esac
done
row="$(awk '$2=="/data" {print $1,$3,$4;n++} END {if(n!=1)exit 1}' /proc/mounts)" || abort 'Mount Data in recovery for the required boot backup. Do not format.'
set -- $row
[ "$#" -eq 3 ] || abort 'Ambiguous Data mount.'
case "$2" in ext4|f2fs) ;; *) abort 'Data must be a real ext4/f2fs filesystem.';; esac
case ",$3," in *,rw,*) ;; *) abort 'Data must be mounted read-write for the backup.';; esac
DATA_DEVICE="$(readlink -f "$1")" || abort 'Cannot identify Data.'
[ -b "$DATA_DEVICE" ] && [ "$DATA_DEVICE" != "$BOOT" ] || abort 'Invalid Data block device.'
[ -d /data ] && [ ! -L /data ] && [ "$(stat -c %d /data)" != "$(stat -c %d /tmp)" ] || abort 'Data is not persistent storage.'
free_kib() {
    free="$(df -Pk "$1" | awk 'NR>1 {n++;v=$4} END {if(n!=1)exit 1;print v}')" || return 1
    case "$free" in ''|*[!0-9]*) return 1;; esac
    printf '%s\n' "$free"
}
[ "$(free_kib /tmp)" -ge 196608 ] || abort 'At least 192 MiB free recovery RAM is required.'
WORK="$(mktemp -d /tmp/r8q-memory-r3.XXXXXX)"
unzip -p "$ZIP" tools/bootio > "$WORK/bootio" || abort 'Cannot extract boot I/O helper.'
[ "$(file_sha256 "$WORK/bootio")" = "$HELPER_SHA" ] || abort 'Boot helper hash mismatch.'
chmod 0700 "$WORK/bootio"
[ "$("$WORK/bootio" --version)" = R8Q_BOOTIO_PRODUCTION_BLOCK_ONLY_V1 ] || abort 'Wrong native helper build mode.'
"$WORK/bootio" --check "$BOOT" || abort 'Boot partition capacity is not exactly 64 MiB.'
unzip -p "$ZIP" images/boot.img.gz > "$WORK/boot.gz" || abort 'Cannot extract candidate.'
[ "$(file_sha256 "$WORK/boot.gz")" = "$GZIP_SHA" ] || abort 'Compressed boot hash mismatch.'
gzip -t "$WORK/boot.gz" || abort 'Invalid compressed boot image.'
gzip -dc "$WORK/boot.gz" > "$WORK/candidate.img" || abort 'Boot decompression failed.'
[ "$(stat -c %s "$WORK/candidate.img")" = 67108864 ] &&
[ "$(file_sha256 "$WORK/candidate.img")" = "$CANDIDATE" ] || abort 'Candidate size/hash mismatch.'
unzip -p "$ZIP" scripts/security-r2.sh > "$WORK/security.sh" || abort 'Cannot extract cumulative R2.'
[ "$(file_sha256 "$WORK/security.sh")" = "$SECURITY_SHA" ] || abort 'Cumulative R2 hash mismatch.'
"$WORK/bootio" --read "$BOOT" > "$WORK/current.img" || abort 'Fresh direct boot read failed.'
BEFORE="$(file_sha256 "$WORK/current.img")"
case "$BEFORE" in "$ORIGINAL"|"$CANDIDATE") ;; *) abort 'Installed boot is not the reviewed P1r4 or this exact candidate. Nothing written.';; esac
if [ -e "$BACKUP" ] || [ -L "$BACKUP" ]; then
    [ -d "$BACKUP" ] && [ ! -L "$BACKUP" ] && [ "$(stat -c '%u:%a' "$BACKUP")" = 0:700 ] || abort 'Unsafe backup directory.'
else
    mkdir -m 0700 "$BACKUP" || abort 'Cannot create persistent backup directory.'
    "$WORK/bootio" --sync-directory /data || abort 'Cannot persist backup directory.'
fi
if [ -e "$BACKUP_FILE" ] || [ -L "$BACKUP_FILE" ]; then
    [ -f "$BACKUP_FILE" ] && [ ! -L "$BACKUP_FILE" ] &&
    [ "$(stat -c '%u:%a:%h' "$BACKUP_FILE")" = 0:600:1 ] &&
    [ "$(stat -c %s "$BACKUP_FILE")" = 67108864 ] &&
    [ "$(file_sha256 "$BACKUP_FILE")" = "$ORIGINAL" ] || abort 'Existing original boot backup is invalid; it was not overwritten.'
else
    [ "$BEFORE" = "$ORIGINAL" ] || abort 'Candidate is installed but the original persistent backup is missing.'
    [ "$(free_kib /data)" -ge 98304 ] || abort 'At least 96 MiB free Data is required for the verified boot backup.'
    BACKUP_STAGE="$(mktemp "$BACKUP/.boot.XXXXXX")"
    cp "$WORK/current.img" "$BACKUP_STAGE" || abort 'Backup copy failed.'
    chmod 0600 "$BACKUP_STAGE"
    [ "$(file_sha256 "$BACKUP_STAGE")" = "$ORIGINAL" ] || abort 'Backup copy hash mismatch.'
    "$WORK/bootio" --sync-file "$BACKUP_STAGE" || abort 'Backup data flush failed.'
    mv "$BACKUP_STAGE" "$BACKUP_FILE" || abort 'Cannot publish boot backup.'
    BACKUP_STAGE=
    "$WORK/bootio" --sync-directory "$BACKUP" || abort 'Backup directory flush failed.'
fi
ui 'Original boot backup verified. Applying the cumulative R2 component...'
sh "$WORK/security.sh" 3 "$OUTFD" "$ZIP" || abort 'R2 component failed. Boot was not changed.'
battery_guard
"$WORK/bootio" --read "$BOOT" > "$WORK/current.img" || abort 'Fresh pre-write boot read failed.'
[ "$(file_sha256 "$WORK/current.img")" = "$BEFORE" ] || abort 'Boot changed during preflight. No kernel write attempted.'
if [ "$BEFORE" != "$CANDIDATE" ]; then
    ui 'Writing the reviewed boot image...'
    WRITE_STARTED=1
    "$WORK/bootio" --write "$WORK/candidate.img" "$BOOT" || abort 'Boot write/flush failed.'
fi
"$WORK/bootio" --read "$BOOT" > "$WORK/current.img" || abort 'Fresh direct readback failed.'
[ "$(file_sha256 "$WORK/current.img")" = "$CANDIDATE" ] || abort 'Fresh boot readback hash mismatch.'
SUCCESS=1
