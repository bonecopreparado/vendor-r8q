#!/sbin/sh
# Ordered, resumable two-file diagnostic upgrade. The init rc is unchanged.
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
PROBE=/vendor/bin/r8q-composer-dump-@@PROBE_SUFFIX@@
PROBE_SHA=@@PROBE_SHA@@
WORK=
STAGE=
REMOUNTED=0
ADDED=0
cleanup() {
    [ -z "$STAGE" ] || rm -f "$STAGE" || ui "WARNING: A private staging file remains; keep recovery.log."
    # Before the new runtime is active an added helper is only an unused orphan.
    # Preserve it if v5 is active or its bytes changed; never remove user data.
    if [ "$ADDED" = 1 ] && [ "$(sha256sum "$SH" | awk '{print $1}')" != @@V5_SH_SHA@@ ] &&
       [ -f "$PROBE" ] && [ ! -L "$PROBE" ] &&
       [ "$(sha256sum "$PROBE" | awk '{print $1}')" = "$PROBE_SHA" ]; then
        rm -f "$PROBE" || ui "WARNING: An unused verified helper remains; repeat RESTORE."
    fi
    if [ "$REMOUNTED" = 1 ]; then mount -o remount,ro /vendor || ui "WARNING: Vendor read-only remount failed; reboot recovery."; fi
    [ -z "$WORK" ] || { rm -f "$WORK/runtime" "$WORK/probe" || ui "WARNING: Private temporary payload cleanup failed."; rmdir "$WORK" 2>/dev/null || true; }
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
[ "$(sha256sum "$RC" | awk '{print $1}')" = @@V3_RC_SHA@@ ] || abort "Install the reviewed diagnostic v3 first; init rc differs."
current="$(sha256sum "$SH" | awk '{print $1}')"
[ "$current" = @@V3_SH_SHA@@ ] || [ "$current" = @@V4_SH_SHA@@ ] || [ "$current" = @@V5_SH_SHA@@ ] || abort "Unknown diagnostic runtime. Nothing changed."
if [ -e "$PROBE" ] || [ -L "$PROBE" ]; then
    [ -f "$PROBE" ] && [ ! -L "$PROBE" ] || abort "Unexpected helper object. Nothing changed."
    [ "$(sha256sum "$PROBE" | awk '{print $1}')" = "$PROBE_SHA" ] || abort "Unknown helper bytes. Nothing changed."
fi
case "$MODE" in
    enable) expected=@@V5_SH_SHA@@; payload=payload/runtime-v5.sh; name=v5;;
    restore-v4) expected=@@V4_SH_SHA@@; payload=payload/runtime-v4.sh; name=v4;;
    restore-v3) expected=@@V3_SH_SHA@@; payload=payload/runtime-v3.sh; name=v3;;
    *) abort "Unknown operation.";;
esac
if [ "$MODE" != enable ]; then
    [ "$current" = @@V5_SH_SHA@@ ] || [ "$current" = "$expected" ] || abort "Wrong restoration target for current runtime. Nothing changed."
fi
WORK="$(mktemp -d /tmp/r8q-bootdiag-v5.XXXXXX)" || abort "Cannot create private temporary directory."
TMPDIR=$WORK;export TMPDIR
unzip -p "$ZIPFILE" "$payload" > "$WORK/runtime" || abort "Cannot read runtime payload."
[ "$(sha256sum "$WORK/runtime" | awk '{print $1}')" = "$expected" ] || abort "Runtime payload hash differs. Nothing changed."
if [ "$MODE" = enable ]; then
    unzip -p "$ZIPFILE" payload/composer-dump > "$WORK/probe" || abort "Cannot read helper payload."
    [ "$(sha256sum "$WORK/probe" | awk '{print $1}')" = "$PROBE_SHA" ] || abort "Helper payload hash differs. Nothing changed."
fi
label="$(ls -dZ "$SH" | awk '{for(i=1;i<=NF;i++)if($i ~ /^u:object_r:[A-Za-z0-9_]+:s0$/){print $i;n++}} END{if(n!=1)exit 1}')" || abort "Cannot identify original runtime label."
case ",$OPTIONS," in *,rw,*) ;; *)mount -o remount,rw /vendor || abort "Vendor writable remount failed.";REMOUNTED=1;;esac
stage_file() {
    STAGE="$(mktemp /vendor/bin/.r8q-bootdiag-v5.XXXXXX)" || abort "Cannot create vendor staging file."
    cat "$1" > "$STAGE" || abort "Cannot stage diagnostic file."
    chmod 0755 "$STAGE";chown 0:0 "$STAGE";chcon "$label" "$STAGE"
    [ "$(sha256sum "$STAGE" | awk '{print $1}')" = "$2" ] || abort "Staged file hash differs."
    mv "$STAGE" "$3" || abort "Activation failed; remain in recovery and repeat ENABLE or RESTORE."
    STAGE=
}
if [ "$MODE" = enable ]; then
    # Old scripts ignore this versioned helper. Install+sync it first, then
    # activate v5 in one rename. This is ordered recovery, not a two-file atomic
    # transaction. V5 itself refuses an absent or altered helper and keeps logs.
    [ -f "$PROBE" ] || ADDED=1
    stage_file "$WORK/probe" "$PROBE_SHA" "$PROBE"
    sync || abort "Helper sync failed; remain in recovery."
    stage_file "$WORK/runtime" "$expected" "$SH"
else
    # Disable references before removing the verified helper. A power loss can
    # leave an unused known helper, which repeating this RESTORE cleans up.
    stage_file "$WORK/runtime" "$expected" "$SH"
    sync || abort "Runtime sync failed; remain in recovery and repeat RESTORE."
    if [ -f "$PROBE" ] && [ ! -L "$PROBE" ]; then
        [ "$(sha256sum "$PROBE" | awk '{print $1}')" = "$PROBE_SHA" ] || abort "Helper changed; preserving it."
        rm "$PROBE" || abort "Runtime restored, helper removal failed; repeat RESTORE."
    fi
fi
sync || abort "Final sync failed; remain in recovery and repeat the operation."
ui "R8Q diagnostic logging $name installed. No ROM, kernel or library was replaced."
if [ "$MODE" = enable ]; then ui "Boot once for about 2 minutes, then collect /metadata/r8q-bootdiag-v5 in recovery.";fi
ui "Existing v3/v4/v5 captures are preserved. No formatting or key deletion."
