#!/system/bin/sh
# Android-only asynchronous evidence. No mounts, property changes or HAL restarts.
set -u
umask 077
SH=/system/bin/sh

snapshot() {
    printf 'PROC snapshot begin\n'
    count=0
    for dir in /proc/[0-9]*; do
        [ -d "$dir" ] || continue
        exe="$(readlink "$dir/exe" 2>/dev/null)" || continue
        exe="${exe% (deleted)}"
        case "$exe" in
            /system/bin/init|/system/bin/vold|/system/bin/vdc|/system/bin/keystore2|/system/bin/servicemanager|/system/bin/surfaceflinger|/system/bin/netd|/system_ext/bin/hwservicemanager|/system/system_ext/bin/hwservicemanager|/vendor/bin/hw/android.hardware.keymaster@4.0-service|/vendor/bin/hw/android.hardware.keymaster@4.0-strongbox-service-qti|/vendor/bin/hw/android.hardware.graphics.composer@2.[1-4]-service|/vendor/bin/hw/vendor.qti.hardware.display.composer-service) ;;
            *) continue;;
        esac
        pid="${dir##*/}"
        name="$(head -c 64 "$dir/comm" 2>/dev/null | tr '\n\r' '  ')"
        cmd="$(head -c 512 "$dir/cmdline" 2>/dev/null | tr '\000' ' ' | awk '
            {
                if ($1 ~ /^[A-Za-z0-9_\/.@:-]+$/ && length($1)<=160) printf "%s", $1
                else printf "[unavailable]"
                if ($1 ~ /\/vdc$/ && ($2=="cryptfs" || $2=="checkpoint") &&
                    ($3=="init_user0" || $3=="prepareCheckpoint" || $3=="encryptFstab" ||
                     $3=="mountFstab" || $3=="supportsCheckpoint" || $3=="needsCheckpoint" ||
                     $3=="commitChanges" || $3=="markBootAttempt")) printf " %s %s", $2, $3
                printf "\n"
            }')"
        channel="$(head -c 128 "$dir/wchan" 2>/dev/null | tr '\n\r' '  ')"
        printf 'PROC pid=%s name=%s exe=%s cmd=%s wchan=%s\n' "$pid" "$name" "$exe" "$cmd" "$channel"
        head -n 6 "$dir/stack" 2>/dev/null | while IFS= read -r frame; do
            printf 'STACK pid=%s %s\n' "$pid" "$(printf '%s' "$frame" | cut -b 1-200)"
        done
        count=$((count+1))
        [ "$count" -lt 16 ] || break
    done
    printf 'PROC snapshot end\n'
}
if [ "${1:-}" = --snapshot ]; then snapshot; exit 0; fi
[ "$#" -eq 0 ] || exit 1

BASE=/metadata/r8q-bootdiag-v4
for tool in timeout cut head tr awk sleep readlink df stat mkdir mktemp chmod sync cat wc; do
    command -v "$tool" >/dev/null 2>&1 || { printf 'R8QBOOT v4 missing required tool: %s\n' "$tool" >&2; exit 1; }
done
metadata_ready() {
    [ -d /metadata ] && [ ! -L /metadata ] || return 1
    row="$(awk '$2=="/metadata" {print $1, $3, $4; n++} END {if(n!=1)exit 1}' /proc/mounts)" || return 1
    set -- $row
    [ "$2" = ext4 ] || return 1
    case ",$3," in *,rw,*) ;; *) return 1;; esac
    expected="$(readlink -f /dev/block/platform/soc/1d84000.ufshc/by-name/metadata)" || return 1
    actual="$(readlink -f "$1")" || return 1
    [ -b "$actual" ] && [ "$actual" = "$expected" ] || return 1
    free="$(df -Pk /metadata | awk 'NR>1 {n++; v=$4} END {if(n!=1)exit 1; print v}')" || return 1
    case "$free" in ''|*[!0-9]*) return 1;; esac
    [ "$free" -ge 12288 ] || return 1
}
metadata_ready || { printf 'R8QBOOT v4 metadata guard failed\n' >&2; exit 1; }
if [ -e "$BASE" ] || [ -L "$BASE" ]; then
    [ -d "$BASE" ] && [ ! -L "$BASE" ] || exit 1
    [ "$(stat -c '%u:%a' "$BASE")" = 0:700 ] || exit 1
else
    mkdir -m 0700 "$BASE" || exit 1
fi
captures=0
for entry in "$BASE"/* "$BASE"/.[!.]* "$BASE"/..?*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    [ -d "$entry" ] && [ ! -L "$entry" ] || exit 1
    case "${entry##*/}" in capture.??????) ;; *) exit 1;; esac
    captures=$((captures+1))
done
[ "$captures" -lt 3 ] || { printf 'R8QBOOT v4 capture limit reached; preserve existing evidence\n' >&2; exit 1; }
CAPTURE="$(mktemp -d "$BASE/capture.XXXXXX")" || exit 1
chmod 0700 "$CAPTURE" || exit 1
printf 'R8QBOOT v4: private Android evidence; not a boot fix.\nLimits: 1000 logcat lines x900 bytes; fixed probe caps; aggregate below 2 MiB.\n' > "$CAPTURE/README.txt"

# Each invocation has a fixed output cap and its producer status is independent
# of head's status. Names/limits/commands are supplied only by fixed calls below.
capture() {
    tag=$1; limit=$2; seconds=$3; shift 3
    (
        timeout "$seconds" "$@"
        result=$?
        printf '%s\n' "$result" > "$CAPTURE/$tag.producer-status"
    ) 2>&1 | head -c "$limit" > "$CAPTURE/$tag"
    reader=$?
    producer=unavailable
    [ ! -s "$CAPTURE/$tag.producer-status" ] || producer="$(cat "$CAPTURE/$tag.producer-status")"
    bytes="$(wc -c < "$CAPTURE/$tag")"
    printf 'producer_status=%s\nreader_status=%s\nbytes=%s\nlimit=%s\n' "$producer" "$reader" "$bytes" "$limit" > "$CAPTURE/$tag.status"
    timeout 3 sync "$CAPTURE/$tag" >/dev/null 2>&1 || true
}
unavailable() {
    printf '%s\n' "$2" > "$CAPTURE/$1.status"
}
read_file() {
    if [ -r "$2" ]; then capture "$1" "$3" 3 head -c "$3" "$2"
    else unavailable "$1" 'source=missing-or-unreadable'; fi
}
find_tool() {
    for candidate in "/system/bin/$1" "/system_ext/bin/$1"; do
        if [ -x "$candidate" ]; then printf '%s\n' "$candidate"; return; fi
    done
    command -v "$1" 2>/dev/null
}

probe_composer() {
    round=$1
    read_file "uptime-$round.txt" /proc/uptime 256
    lshal="$(find_tool lshal)" || lshal=
    selected=
    if [ -n "$lshal" ]; then
        capture "lshal-$round.txt" 32768 3 "$lshal" list --types=binderized --neat -i
        for version in 2.4 2.3 2.2 2.1; do
            wanted="android.hardware.graphics.composer@$version::IComposer/default"
            if awk -v want="$wanted" '$1==want {yes=1} END {exit !yes}' "$CAPTURE/lshal-$round.txt"; then
                selected=$wanted; break
            fi
        done
    else
        unavailable "lshal-$round.txt" 'tool=lshal-unavailable'
    fi
    if [ -n "$selected" ]; then
        printf '%s\n' "$selected" > "$CAPTURE/composer-$round.selected"
        # No -E: a base HIDL descriptor can be implemented by a derived HAL.
        capture "composer-$round.txt" 131072 4 "$lshal" debug "$selected"
        return
    fi
    # Named AIDL fallback only; never dump all Android services.
    service="$(find_tool service)" || service=
    dumpsys="$(find_tool dumpsys)" || dumpsys=
    aidl=android.hardware.graphics.composer3.IComposer/default
    if [ -n "$service" ] && [ -n "$dumpsys" ]; then
        capture "aidl-check-$round.txt" 512 2 "$service" check "$aidl"
        if awk -v line="Service $aidl: found" '$0==line {yes=1} END {exit !yes}' "$CAPTURE/aidl-check-$round.txt"; then
            printf '%s\n' "$aidl" > "$CAPTURE/composer-$round.selected"
            capture "composer-$round.txt" 131072 4 "$dumpsys" -t 3 "$aidl"
            return
        fi
    fi
    unavailable "composer-$round.txt" 'composer=no-whitelisted-service-found; no HAL was started or restarted'
}

# These jobs start independently of logcat; early return to recovery should
# still leave first-round HWC data. No init action waits for this service.
( sleep 8; probe_composer early ) &
composer_early=$!
( sleep 20; probe_composer later ) &
composer_later=$!
( sleep 20; capture processes-20.txt 32768 5 "$SH" "$0" --snapshot ) &
process_early=$!
( sleep 60; capture processes-60.txt 32768 5 "$SH" "$0" --snapshot ) &
process_later=$!

read_file kernel-config.gz /proc/config.gz 131072
read_file kernel-modules.txt /proc/modules 32768
read_file ip-tables-targets.txt /proc/net/ip_tables_targets 4096
read_file ip6-tables-targets.txt /proc/net/ip6_tables_targets 4096
read_file kernel-version.txt /proc/version 4096
read_file uptime-start.txt /proc/uptime 256
read_file fb0-modes.txt /sys/class/graphics/fb0/modes 1024
read_file fb0-mode.txt /sys/class/graphics/fb0/mode 1024
read_file drm-modes.txt /sys/class/drm/card0-DSI-1/modes 1024
read_file drm-status.txt /sys/class/drm/card0-DSI-1/status 1024
getprop="$(find_tool getprop)" || getprop=
if [ -n "$getprop" ]; then
    for prop in ro.surface_flinger.enable_frame_rate_override debug.sf.frame_rate_multiple_threshold ro.surface_flinger.use_content_detection_for_refresh_rate debug.sf.hw ro.sf.lcd_density vendor.display.disable_dynamic_fps vendor.display.enable_optimize_refresh ro.product.first_api_level; do
        capture "property-$prop.txt" 256 2 "$getprop" "$prop"
    done
else
    unavailable properties 'tool=getprop-unavailable'
fi

logcat="$(find_tool logcat)" || logcat=
attempt=0
while [ ! -S /dev/socket/logdr ] && [ "$attempt" -lt 15 ]; do sleep 1; attempt=$((attempt+1)); done
if [ -n "$logcat" ] && [ -S /dev/socket/logdr ]; then
    (
        timeout 90 "$logcat" -b main -b system -b crash -v threadtime \
            SurfaceFlinger:V RefreshRateSelector:V HWComposer:V HwcComposer:V ComposerHal:V HWC2:V SDM:V \
            netd:V Netd:V StrictController:V IptablesRestoreController:V vold:I keystore2:I hwservicemanager:I \
            DEBUG:F libc:F '*:S'
        result=$?
        printf '%s\n' "$result" > "$CAPTURE/boot.log.producer-status"
    ) 2>&1 |
    (
        count=0
        while IFS= read -r line; do
            case "$line" in *R8QBOOT*) continue;; esac
            printf '[R8QBOOT] %s\n' "$(printf '%s' "$line" | cut -b 1-900)"
            count=$((count+1)); [ "$count" -lt 1000 ] || break
        done
        printf '%s\n' "$count" > "$CAPTURE/boot.log.lines"
    ) > "$CAPTURE/boot.log"
    reader=$?
    producer=unavailable
    [ ! -s "$CAPTURE/boot.log.producer-status" ] || producer="$(cat "$CAPTURE/boot.log.producer-status")"
    printf 'producer_status=%s\nreader_status=%s\n' "$producer" "$reader" > "$CAPTURE/boot.log.status"
else
    unavailable boot.log 'tool-or-logdr=unavailable; independent probes retained'
fi
wait "$composer_early" || true
wait "$composer_later" || true
wait "$process_early" || true
wait "$process_later" || true
printf 'capture=complete\n' > "$CAPTURE/COMPLETE.txt"
timeout 3 sync "$CAPTURE" >/dev/null 2>&1 || true
exit 0
