#!/sbin/sh
# Temporary r8q vendor diagnostics. Only the two named files may be changed.
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
REF=/vendor/etc/init/hw/init.qcom.rc
SCRIPTREF=/vendor/bin/init.qti.qcv.sh
RC=/vendor/etc/init/r8q-bootdiag.rc
SH=/vendor/bin/r8q-bootdiag.sh
WORK=
REMOUNTED=0
STAGE_RC=
STAGE_SH=
NEW_SH=0
NEW_RC=0
cleanup() {
    [ -z "$STAGE_RC" ] || rm -f "$STAGE_RC"
    [ -z "$STAGE_SH" ] || rm -f "$STAGE_SH"
    # An interrupted activation must not leave a new script without its rc.
    if [ "$NEW_SH" = 1 ] && [ "$NEW_RC" = 0 ]; then rm -f "$SH"; fi
    if [ "$REMOUNTED" = 1 ]; then
        if ! mount -o remount,ro /vendor; then ui "WARNING: vendor remount read-only failed; reboot recovery."; fi
    fi
    [ -z "$WORK" ] || { rm -f "$WORK/rc" "$WORK/sh"; rmdir "$WORK" 2>/dev/null || true; }
}
trap cleanup EXIT
for tool in getprop id awk cat basename readlink sha256sum mktemp mount unzip chmod chown chcon ls mv rm rmdir sync; do
    command -v "$tool" >/dev/null 2>&1 || abort "Missing recovery tool: $tool"
done
[ "$(id -u)" = 0 ] || abort "Recovery root required."
[ "$(getprop ro.product.device)" = r8q ] || abort "Only Snapdragon r8q."
mountrow="$(awk '$2=="/vendor" {print $1, $3, $4; n++} END {if(n!=1)exit 1}' /proc/mounts)" || abort "Mount Vendor in OrangeFox first."
set -- $mountrow
SOURCE=$1
[ "$2" = ext4 ] || abort "Vendor must be the expected ext4 filesystem."
OPTIONS=$3
resolved="$(readlink -f "$SOURCE")" || abort "Cannot resolve vendor device."
node="$(basename "$resolved")"
[ "$(cat "/sys/class/block/$node/dm/name")" = vendor ] || abort "Mounted source is not the vendor logical partition."
[ -f "$REF" ] && [ ! -L "$REF" ] || abort "Missing expected P1 vendor reference."
hash="$(sha256sum "$REF" | awk '{print $1}')"
[ "$hash" = "@@REFERENCE_SHA@@" ] || abort "Vendor differs from the reviewed P1 candidate. Nothing changed."
[ -f "$SCRIPTREF" ] && [ ! -L "$SCRIPTREF" ] || abort "Script-label reference is absent."
for dir in /vendor/bin /vendor/etc/init; do
    [ -d "$dir" ] && [ ! -L "$dir" ] || abort "Unexpected vendor path: $dir"
done
check_existing() {
    if [ -e "$1" ] || [ -L "$1" ]; then
        [ -f "$1" ] && [ ! -L "$1" ] || abort "Unexpected diagnostic path: $1"
        got="$(sha256sum "$1" | awk '{print $1}')"
        [ "$got" = "$2" ] || [ "$got" = "$3" ] || abort "Existing file differs; refusing to overwrite/remove: $1"
    fi
}
check_existing "$RC" "@@RC_SHA@@" "@@OLD_RC_SHA@@"
check_existing "$SH" "@@SH_SHA@@" "@@OLD_SH_SHA@@"
if [ "$MODE" = enable ]; then
    if [ -f "$RC" ] && [ -f "$SH" ]; then
        if [ "$(sha256sum "$RC" | awk '{print $1}')" = "@@RC_SHA@@" ] &&
           [ "$(sha256sum "$SH" | awk '{print $1}')" = "@@SH_SHA@@" ]; then
            ui "Boot diagnostics v2 already enabled."; exit 0
        fi
        abort "Older diagnostic version found. Install V2 REMOVE, then V2 ENABLE."
    fi
    [ ! -e "$RC" ] && [ ! -e "$SH" ] || abort "Incomplete old diagnostic setup; run REMOVE first."
    WORK="$(mktemp -d /tmp/r8q-bootdiag.XXXXXX)" || abort "Cannot create private temporary directory."
    TMPDIR="$WORK"; export TMPDIR
    unzip -p "$ZIPFILE" payload/init.rc > "$WORK/rc" || abort "Cannot read rc payload."
    unzip -p "$ZIPFILE" payload/bootdiag.sh > "$WORK/sh" || abort "Cannot read script payload."
    [ "$(sha256sum "$WORK/rc" | awk '{print $1}')" = "@@RC_SHA@@" ] || abort "RC payload hash differs."
    [ "$(sha256sum "$WORK/sh" | awk '{print $1}')" = "@@SH_SHA@@" ] || abort "Script payload hash differs."
    rc_label="$(ls -dZ "$REF" | awk '{for(i=1;i<=NF;i++)if($i ~ /^u:object_r:[A-Za-z0-9_]+:s0$/){print $i;n++}} END{if(n!=1)exit 1}')" || abort "Cannot read rc SELinux label."
    sh_label="$(ls -dZ "$SCRIPTREF" | awk '{for(i=1;i<=NF;i++)if($i ~ /^u:object_r:[A-Za-z0-9_]+:s0$/){print $i;n++}} END{if(n!=1)exit 1}')" || abort "Cannot read script SELinux label."
fi
case ",$OPTIONS," in *,rw,*) ;; *)
    mount -o remount,rw /vendor || abort "Cannot remount Vendor writable. Nothing changed."
    REMOUNTED=1 ;;
esac
if [ "$MODE" = enable ]; then
    STAGE_SH="$(mktemp /vendor/bin/.r8q-bootdiag.XXXXXX)"
    STAGE_RC="$(mktemp /vendor/etc/init/.r8q-bootdiag.XXXXXX)"
    cat "$WORK/sh" > "$STAGE_SH"
    cat "$WORK/rc" > "$STAGE_RC"
    chmod 0755 "$STAGE_SH"; chmod 0644 "$STAGE_RC"
    chown 0:0 "$STAGE_SH" "$STAGE_RC"
    chcon "$sh_label" "$STAGE_SH"; chcon "$rc_label" "$STAGE_RC"
    [ "$(sha256sum "$STAGE_SH" | awk '{print $1}')" = "@@SH_SHA@@" ] || abort "Staged script differs."
    [ "$(sha256sum "$STAGE_RC" | awk '{print $1}')" = "@@RC_SHA@@" ] || abort "Staged rc differs."
    mv "$STAGE_SH" "$SH"; STAGE_SH=; NEW_SH=1
    mv "$STAGE_RC" "$RC"; STAGE_RC=; NEW_RC=1
    sync || abort "Sync failed; remain in recovery and run REMOVE."
    ui "R8Q diagnostic logging v2 enabled. This is not a boot fix."
    ui "Boot System once; after about 3 minutes return to recovery and collect last_kmsg."
else
    # Preflight above accepts only our exact bytes, including partial setups.
    rm -f "$RC" "$SH"
    sync || abort "Sync failed."
    ui "R8Q diagnostic logging removed."
fi
ui "No userdata formatting or partition-image flashing was performed."
