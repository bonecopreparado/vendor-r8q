#!/system/bin/sh
# v3: bounded regular-file capture on the already-mounted metadata filesystem.
set -u
umask 077
BASE=/metadata/r8q-bootdiag-v3
for tool in timeout cut head tr awk dirname basename sleep readlink df stat mkdir mktemp chmod sync; do
    command -v "$tool" >/dev/null 2>&1 || exit 1
done
# Never mount/remount/format metadata or touch existing Android key directories.
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
metadata_ready || exit 1
if [ -e "$BASE" ] || [ -L "$BASE" ]; then
    [ -d "$BASE" ] && [ ! -L "$BASE" ] || exit 1
    [ "$(stat -c '%u:%a' "$BASE")" = 0:700 ] || exit 1
else
    mkdir -m 0700 "$BASE" || exit 1
fi
# At most four captures, under 2 MiB each; never delete previous evidence.
captures=0
for entry in "$BASE"/* "$BASE"/.[!.]* "$BASE"/..?*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    [ -d "$entry" ] && [ ! -L "$entry" ] || exit 1
    case "${entry##*/}" in capture.??????) ;; *) exit 1;; esac
    captures=$((captures+1))
done
[ "$captures" -lt 4 ] || exit 1
CAPTURE="$(mktemp -d "$BASE/capture.XXXXXX")" || exit 1
chmod 0700 "$CAPTURE" || exit 1
LOGFILE=$CAPTURE/boot.log
# The exclusive new directory prevents following pre-existing log symlinks.
(set -C; : > "$LOGFILE") || exit 1
chmod 0600 "$LOGFILE" || exit 1
exec 9>> "$LOGFILE" || exit 1
mark() { printf '[R8QBOOT] %s\n' "$*" >&9; }
flush() { timeout 5 sync "$LOGFILE" >/dev/null 2>&1 || true; }
mark "BEGIN filtered Android userspace capture v3 (init event; persistent file)"
flush
snapshot() {
    mark "PROC snapshot begin"
    count=0
    for file in /proc/[0-9]*/comm; do
        [ -r "$file" ] || continue
        IFS= read -r name < "$file" || continue
        case "$name" in init|vold|vdc|keystore2|servicemanager|hwservicemanage|android.hardwar) ;; *) continue;; esac
        pid="$(basename "$(dirname "$file")")"
        # Command arguments are private except these fixed vdc subcommands.
        cmd="$(head -c 512 "/proc/$pid/cmdline" 2>/dev/null | tr '\000' ' ' | awk '
            {
                if ($1 ~ /^[A-Za-z0-9_\/.@:-]+$/ && length($1)<=160) printf "%s", $1
                else printf "[unavailable]"
                if ($1 ~ /\/vdc$/ && ($2=="cryptfs" || $2=="checkpoint") &&
                    ($3=="init_user0" || $3=="prepareCheckpoint" || $3=="encryptFstab" ||
                     $3=="mountFstab" || $3=="supportsCheckpoint" || $3=="needsCheckpoint" ||
                     $3=="commitChanges" || $3=="markBootAttempt")) printf " %s %s", $2, $3
                printf "\n"
            }')" || cmd=unavailable
        channel="$(head -c 128 "/proc/$pid/wchan" 2>/dev/null)" || channel=unavailable
        mark "PROC pid=$pid name=$name cmd=$cmd wchan=$channel" || true
        head -n 6 "/proc/$pid/stack" 2>/dev/null | while IFS= read -r frame; do
            frame="$(printf '%s' "$frame" | cut -b 1-200)" || continue
            mark "STACK pid=$pid $frame" || true
        done
        count=$((count+1))
        [ "$count" -lt 16 ] || break
    done
    mark "PROC snapshot end" || true
    flush
}
( sleep 20; snapshot; sleep 40; snapshot ) &
snapshot_pid=$!
attempt=0
while [ ! -S /dev/socket/logdr ]; do
    attempt=$((attempt+1))
    if [ "$attempt" -ge 20 ]; then
        mark "logdr socket unavailable after 20 seconds; retaining process snapshots"
        wait "$snapshot_pid" || true
        flush
        exit 0
    fi
    sleep 1
done
# Exclude kernel and suppress our own marker, avoiding mirror feedback.
timeout 120 /system/bin/logcat -b main -b system -b crash -v threadtime init:V vold:V vdc:V keystore2:V ServiceManagement:V hwservicemanager:V servicemanager:V '*:W' 2>&1 |
(
    count=0
    while IFS= read -r line; do
        case "$line" in *R8QBOOT*) continue;; esac
        bounded="$(printf '%s' "$line" | cut -b 1-900)" || continue
        mark "$bounded" || true
        count=$((count+1))
        [ "$count" -lt 1500 ] || break
    done
    mark "END filtered capture; lines=$count" || true
)
wait "$snapshot_pid" || true
mark "END capture v3" || true
flush
exit 0
