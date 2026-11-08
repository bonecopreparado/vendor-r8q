#!/sbin/sh
# Atomic upgrade of the reviewed v3 script; its init rc remains byte-identical.
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
SH=/vendor/bin/r8q-bootdiag.sh
RC=/vendor/etc/init/r8q-bootdiag.rc
REF=/vendor/etc/init/hw/init.qcom.rc
WORK=
STAGE=
REMOUNTED=0
cleanup() {
    [ -z "$STAGE" ] || rm -f "$STAGE"
    if [ "$REMOUNTED" = 1 ]; then mount -o remount,ro /vendor || ui "WARNING: Vendor read-only remount failed; reboot recovery."; fi
    [ -z "$WORK" ] || { rm -f "$WORK/runtime"; rmdir "$WORK" 2>/dev/null || true; }
}
trap cleanup EXIT
for tool in getprop id awk cat basename readlink sha256sum mktemp mount unzip chmod chown chcon ls mv rm rmdir sync; do
    command -v "$tool" >/dev/null 2>&1 || abort "Missing recovery tool: $tool"
done
[ "$(id -u)" = 0 ] || abort "Recovery root required."
[ "$(getprop ro.product.device)" = r8q ] || abort "Only Snapdragon r8q."
row="$(awk '$2=="/vendor" {print $1,$3,$4;n++} END {if(n!=1)exit 1}' /proc/mounts)" || abort "Mount Vendor in OrangeFox first."
set -- $row
[ "$2" = ext4 ] || abort "Expected ext4 Vendor."
OPTIONS=$3
node="$(basename "$(readlink -f "$1")")"
[ "$(cat "/sys/class/block/$node/dm/name")" = vendor ] || abort "Mounted device is not logical Vendor."
for path in "$SH" "$RC" "$REF"; do [ -f "$path" ] && [ ! -L "$path" ] || abort "Expected regular file absent: $path"; done
for dir in /vendor/bin /vendor/etc/init /vendor/etc/init/hw; do [ -d "$dir" ] && [ ! -L "$dir" ] || abort "Unexpected vendor directory: $dir"; done
[ "$(sha256sum "$REF" | awk '{print $1}')" = @@VENDOR_SHA@@ ] || abort "Not the reviewed P1 vendor."
[ "$(sha256sum "$RC" | awk '{print $1}')" = @@V3_RC_SHA@@ ] || abort "Install the reviewed diagnostic v3 first; its init rc differs."
current="$(sha256sum "$SH" | awk '{print $1}')"
[ "$current" = @@V3_SH_SHA@@ ] || [ "$current" = @@V4_SH_SHA@@ ] || abort "Unknown existing diagnostic script. Nothing changed."
if [ "$MODE" = enable ]; then expected=@@V4_SH_SHA@@;payload=payload/runtime-v4.sh;name=v4;else expected=@@V3_SH_SHA@@;payload=payload/runtime-v3.sh;name=v3;fi
if [ "$current" = "$expected" ]; then ui "R8Q diagnostic logging $name already installed.";exit 0;fi
WORK="$(mktemp -d /tmp/r8q-bootdiag-v4.XXXXXX)" || abort "Cannot create private temporary directory."
TMPDIR=$WORK;export TMPDIR
unzip -p "$ZIPFILE" "$payload" > "$WORK/runtime" || abort "Cannot read runtime payload."
[ "$(sha256sum "$WORK/runtime" | awk '{print $1}')" = "$expected" ] || abort "Payload hash differs. Nothing changed."
label="$(ls -dZ "$SH" | awk '{for(i=1;i<=NF;i++)if($i ~ /^u:object_r:[A-Za-z0-9_]+:s0$/){print $i;n++}} END{if(n!=1)exit 1}')" || abort "Cannot identify original runtime label."
case ",$OPTIONS," in *,rw,*) ;; *)mount -o remount,rw /vendor || abort "Vendor writable remount failed.";REMOUNTED=1;;esac
STAGE="$(mktemp /vendor/bin/.r8q-bootdiag-v4.XXXXXX)"
cat "$WORK/runtime" > "$STAGE"
chmod 0755 "$STAGE";chown 0:0 "$STAGE";chcon "$label" "$STAGE"
[ "$(sha256sum "$STAGE" | awk '{print $1}')" = "$expected" ] || abort "Staged runtime hash differs."
mv "$STAGE" "$SH";STAGE=
sync || abort "Sync failed; remain in recovery and use RESTORE-V3."
ui "R8Q diagnostic logging $name installed. Kernel and display settings are unchanged."
if [ "$MODE" = enable ]; then ui "Boot once for about 2 minutes; collect /metadata/r8q-bootdiag-v4 in recovery.";fi
ui "Existing v3/v4 captures are preserved. No formatting or key deletion."
