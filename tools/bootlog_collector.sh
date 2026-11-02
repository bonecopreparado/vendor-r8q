#!/sbin/sh
# R8Q read-only previous-boot evidence collector; Android recovery API 3.
# It writes only its output directory/archive. It never mounts or flashes devices.
set -u
umask 077

OUTFD=${2:-}
case "$OUTFD" in ''|*[!0-9]*) OUTFD=;; esac
ui_print() {
    if [ -n "$OUTFD" ] && [ -e "/proc/self/fd/$OUTFD" ]; then
        printf 'ui_print %s\nui_print\n' "$*" > "/proc/self/fd/$OUTFD"
    else
        printf '%s\n' "$*"
    fi
}
is_mounted() {
    awk -v p="$1" '$2 == p { yes = 1 } END { exit !yes }' /proc/mounts
}
ROOT=
for candidate in /external_sd /usb_otg /storage/sdcard1 /storage/usb; do
    if is_mounted "$candidate" && [ -d "$candidate" ] && [ -w "$candidate" ]; then
        ROOT=$candidate
        break
    fi
done
VOLATILE=0
if [ -z "$ROOT" ] && is_mounted /data && [ -d /sdcard ] && [ -w /sdcard ]; then
    ROOT=/sdcard
fi
if [ -z "$ROOT" ]; then
    ROOT=/tmp
    VOLATILE=1
fi
STAMP=$(date -u +%Y%m%d-%H%M%S 2>/dev/null || printf undated)
NAME=R8Q-BOOTLOGS-$STAMP-$$
DIR=$ROOT/$NAME
if ! mkdir "$DIR"; then
    ui_print "ERROR: cannot create collection directory: $DIR"
    exit 1
fi
mkdir "$DIR/previous-boot" "$DIR/current-recovery"
INDEX=$DIR/INDEX.txt
cat > "$INDEX" <<'EOF'
R8Q BOOT EVIDENCE - READ-ONLY COLLECTION

previous-boot/ contains persistent crash records if this kernel exposes them.
current-recovery/ contains the CURRENT OrangeFox session, not the failed ROM
boot. Errors in current-recovery logs alone do not establish a ROM boot cause.
Missing/empty persistent records do NOT prove that the previous boot was OK.
Some kernels preserve no record after a reboot. Collection reads existing
files only: it never clears pstore or logcat, mounts partitions, modifies ROM,
formats data or writes block devices. No userdata/persist/EFS content is copied.

Run immediately after a failed boot, returning directly to recovery, before
restoring another ROM, formatting, or performing another unnecessary reboot.
Send the completed .tar.gz (or the whole folder if compression is unavailable).
Each input is bounded; truncated records are explicitly noted below. The output
contains device/build/boot-reason properties, not the complete property list.

EOF
printf 'Collection directory: %s\nVolatile output: %s\n\n' "$DIR" "$VOLATILE" >> "$INDEX"
copy_bounded() {
    source=$1
    destination=$2
    limit=$3
    printf 'INPUT %s -> %s (maximum %s bytes): ' "$source" "$destination" "$limit" >> "$INDEX"
    if [ ! -r "$source" ]; then
        printf 'missing or unreadable\n' >> "$INDEX"
        return
    fi
    if head -c "$limit" "$source" > "$DIR/$destination" 2> "$DIR/read-error.tmp"; then
        count=$(wc -c < "$DIR/$destination")
        printf 'read %s bytes' "$count" >> "$INDEX"
        if [ "$count" -ge "$limit" ]; then
            printf ' (limit reached; may be truncated)' >> "$INDEX"
        fi
        printf '\n' >> "$INDEX"
    else
        printf 'read failed or partial\n' >> "$INDEX"
        head -c 2048 "$DIR/read-error.tmp" >> "$INDEX"
    fi
}
ui_print "R8Q read-only boot evidence collector"
ui_print "Reading persistent records; ROM partitions are not changed."
n=0
for record in /sys/fs/pstore/*; do
    [ -f "$record" ] || continue
    if [ "$n" -ge 8 ]; then
        printf 'PSTORE: more than 8 records; remaining files were not read.\n' >> "$INDEX"
        break
    fi
    n=$((n + 1))
    copy_bounded "$record" "previous-boot/pstore-$n.log" 2097152
done
printf 'PSTORE regular files selected: %s\n' "$n" >> "$INDEX"
copy_bounded /proc/last_kmsg previous-boot/last_kmsg.log 4194304
for name in reset_reason reset_reason_extra_info reset_reason_extra_info_B reset_reason_extra_info_C reset_reason_extra_info_M reset_reason_extra_info_P; do
    copy_bounded "/proc/$name" "previous-boot/$name.txt" 65536
done
for name in cmdline version uptime mounts; do
    copy_bounded "/proc/$name" "current-recovery/proc-$name.txt" 65536
done
for prop in ro.product.device ro.product.model ro.build.fingerprint ro.vendor.build.fingerprint ro.bootmode ro.boot.bootreason ro.boot.boot_reason sys.boot.reason persist.sys.boot.reason ro.boot.slot_suffix; do
    value=$(getprop "$prop" 2>/dev/null || true)
    printf '%s=%s\n' "$prop" "$value" >> "$DIR/current-recovery/selected-properties.txt"
done
if [ -r /tmp/recovery.log ]; then
    tail -c 1048576 /tmp/recovery.log > "$DIR/current-recovery/recovery-tail.log" 2>/dev/null || true
    printf 'CURRENT recovery.log: last 1048576 bytes at most (older content omitted).\n' >> "$INDEX"
fi
capture() {
    destination=$1
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout 10 "$@" 2>&1 | head -c 1048576 > "$DIR/current-recovery/$destination"
        printf 'CURRENT command: %s; bounded to 10 seconds / 1048576 bytes.\n' "$*" >> "$INDEX"
    else
        printf 'SKIPPED current command (timeout unavailable): %s\n' "$*" >> "$INDEX"
    fi
}
capture dmesg.log dmesg
capture logcat-tail.log logcat -d -b main -b system -b crash -v threadtime -t 2000
rm -f "$DIR/read-error.tmp"
ARCHIVE=$ROOT/$NAME.tar.gz
if command -v tar >/dev/null 2>&1 && command -v gzip >/dev/null 2>&1; then
    # Write the tar first and check its status so a failed tar cannot become a
    # seemingly successful compressed archive through a shell pipeline.
    TAR=$ROOT/$NAME.tar
    if tar -cf "$TAR" -C "$ROOT" "$NAME" && gzip -c "$TAR" > "$ARCHIVE"; then
        rm -f "$TAR"
        if command -v sha256sum >/dev/null 2>&1; then
            sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"
        fi
        ui_print "Collection complete. Send this file:"
        ui_print "$ARCHIVE"
    else
        rm -f "$ARCHIVE"
        ui_print "Archive creation failed. Send the collection folder instead:"
        ui_print "$DIR"
    fi
else
    ui_print "Compression tools unavailable. Send the collection folder:"
    ui_print "$DIR"
fi
if [ "$VOLATILE" -eq 1 ]; then
    ui_print "WARNING: output is in /tmp and WILL DISAPPEAR on reboot."
    ui_print "Copy the output to mounted phone storage or USB before leaving recovery."
else
    ui_print "Do not format this storage before sending the evidence."
fi
ui_print "Missing persistent logs do not rule out a boot failure."
exit 0
