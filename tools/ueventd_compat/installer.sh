#!/sbin/sh
# Reversible import bridge only; never change device nodes in recovery.
set -eu
set -o pipefail
umask 077
[ "$#" -eq 3 ] || exit 1
OUTFD=$2
ZIPFILE=$3
case "$OUTFD" in ''|*[!0-9]*) exit 1;; esac
ui() { printf 'ui_print %s\nui_print\n' "$*" > "/proc/self/fd/$OUTFD"; }
abort() { ui "ERROR: $*"; exit 1; }
MODE=@@MODE@@
LEGACY=/vendor/ueventd.rc
TARGET=/vendor/etc/ueventd.rc
REF=/vendor/etc/init/hw/init.qcom.rc
WORK=
STAGE=
REMOUNTED=0
cleanup() {
    [ -z "$STAGE" ] || rm -f "$STAGE"
    if [ "$REMOUNTED" = 1 ]; then
        mount -o remount,ro /vendor || ui "WARNING: Vendor read-only remount failed; reboot recovery."
    fi
    [ -z "$WORK" ] || { rm -f "$WORK/bridge"; rmdir "$WORK" 2>/dev/null || true; }
}
trap cleanup EXIT
for tool in getprop id awk cat basename readlink sha256sum mktemp mount unzip chmod chown chcon ls mv rm rmdir sync; do
    command -v "$tool" >/dev/null 2>&1 || abort "Missing recovery tool: $tool"
done
[ "$(id -u)" = 0 ] || abort "Recovery root required."
[ "$(getprop ro.product.device)" = r8q ] || abort "Only Snapdragon r8q."
mountrow="$(awk '$2=="/vendor" {print $1,$3,$4;n++} END {if(n!=1)exit 1}' /proc/mounts)" || abort "Mount Vendor in OrangeFox first."
set -- $mountrow
SOURCE=$1
[ "$2" = ext4 ] || abort "Expected ext4 Vendor."
OPTIONS=$3
node="$(basename "$(readlink -f "$SOURCE")")"
[ "$(cat "/sys/class/block/$node/dm/name")" = vendor ] || abort "Mounted device is not logical Vendor."
for path in "$LEGACY" "$REF"; do
    [ -f "$path" ] && [ ! -L "$path" ] || abort "Expected regular file is absent: $path"
done
[ "$(sha256sum "$LEGACY" | awk '{print $1}')" = @@LEGACY_SHA@@ ] || abort "Legacy vendor rules differ. Nothing changed."
[ "$(sha256sum "$REF" | awk '{print $1}')" = @@VENDOR_SHA@@ ] || abort "This is not the reviewed P1 vendor."
[ -d /vendor/etc ] && [ ! -L /vendor/etc ] || abort "Unexpected Vendor configuration directory."
if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    [ -f "$TARGET" ] && [ ! -L "$TARGET" ] || abort "Unexpected existing canonical path."
    [ "$(sha256sum "$TARGET" | awk '{print $1}')" = @@PAYLOAD_SHA@@ ] || abort "Canonical file already exists with different content. Nothing changed."
fi
if [ "$MODE" = enable ]; then
    # Read the actual mounted donor configuration; never infer it from AOSP.
    SYSTEM_CONFIG=
    for mp in /system_root /system; do
        row="$(awk -v p="$mp" '$2==p {print $1,$3;n++} END {if(n!=1)exit 1}' /proc/mounts)" || continue
        set -- $row
        [ "$2" = erofs ] || continue
        node="$(basename "$(readlink -f "$1")")"
        [ "$(cat "/sys/class/block/$node/dm/name")" = system ] || continue
        mountroot="$(readlink -f "$mp")"
        for file in "$mp/system/etc/ueventd.rc" "$mp/etc/ueventd.rc"; do
            [ -f "$file" ] && [ ! -L "$file" ] || continue
            actual="$(readlink -f "$file")"
            case "$actual" in "$mountroot"/*) ;; *) abort "System configuration escapes its mounted filesystem.";; esac
            if [ -n "$SYSTEM_CONFIG" ] && [ "$SYSTEM_CONFIG" != "$actual" ]; then
                abort "Ambiguous System ueventd configuration. Nothing changed."
            fi
            SYSTEM_CONFIG=$actual
        done
    done
    [ -n "$SYSTEM_CONFIG" ] || abort "Mount System (read-only) in OrangeFox, then retry."
    awk '$1=="import" && $2=="/vendor/etc/ueventd.rc" && (NF==2 || substr($3,1,1)=="#") {n++} END {exit(n!=1)}' "$SYSTEM_CONFIG" || abort "Donor does not import the canonical Vendor file. Nothing changed; send recovery.log."
    ui "Donor System import verified; configuration SHA256:"
    ui "$(sha256sum "$SYSTEM_CONFIG" | awk '{print $1}')"
    if [ -f "$TARGET" ]; then ui "R8Q ueventd compatibility bridge already enabled."; exit 0; fi
    WORK="$(mktemp -d /tmp/r8q-ueventd.XXXXXX)" || abort "Cannot create private temporary directory."
    TMPDIR=$WORK; export TMPDIR
    unzip -p "$ZIPFILE" payload/ueventd.rc > "$WORK/bridge" || abort "Cannot read payload."
    [ "$(sha256sum "$WORK/bridge" | awk '{print $1}')" = @@PAYLOAD_SHA@@ ] || abort "Payload hash differs. Nothing changed."
    label="$(ls -dZ "$LEGACY" | awk '{for(i=1;i<=NF;i++)if($i ~ /^u:object_r:[A-Za-z0-9_]+:s0$/){print $i;n++}} END {if(n!=1)exit 1}')" || abort "Cannot determine original file label."
else
    [ -f "$TARGET" ] || { ui "Bridge already absent."; exit 0; }
fi
case ",$OPTIONS," in *,rw,*) ;; *)
    mount -o remount,rw /vendor || abort "Vendor writable remount failed. Nothing changed."
    REMOUNTED=1;;
esac
if [ "$MODE" = enable ]; then
    STAGE="$(mktemp /vendor/etc/.r8q-ueventd.XXXXXX)"
    cat "$WORK/bridge" > "$STAGE"
    chmod 0644 "$STAGE"; chown 0:0 "$STAGE"; chcon "$label" "$STAGE"
    [ "$(sha256sum "$STAGE" | awk '{print $1}')" = @@PAYLOAD_SHA@@ ] || abort "Staged bridge hash differs."
    mv "$STAGE" "$TARGET"; STAGE=
    sync || abort "Sync failed; remain in recovery and run REMOVE."
    ui "R8Q ueventd compatibility bridge enabled. Experimental; boot is not confirmed."
    ui "Original hardware permissions are preserved. Keep BOOTDIAG V3 enabled for the next boot."
else
    rm -f "$TARGET"
    sync || abort "Sync failed."
    ui "R8Q ueventd compatibility bridge removed. Original legacy rules preserved."
fi
ui "Only /vendor/etc/ueventd.rc changed. No formatting, key deletion or block-image flashing."
