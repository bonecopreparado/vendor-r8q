#!/system/bin/sh
# v2: start on init, independent of property actions deferred behind boot waits.
set -u
KMSG=/dev/kmsg
[ -c "$KMSG" ] && [ -w "$KMSG" ] || exit 1
mark() { printf '<6>[R8QBOOT] %s\n' "$*" > "$KMSG"; }
mark "BEGIN filtered Android userspace capture v2 (init event)"
for tool in timeout cut head tr awk dirname basename sleep; do
    command -v "$tool" >/dev/null 2>&1 || { mark "Missing capture tool: $tool"; exit 0; }
done
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
}
( sleep 20; snapshot; sleep 40; snapshot ) &
snapshot_pid=$!
attempt=0
while [ ! -S /dev/socket/logdr ]; do
    attempt=$((attempt+1))
    if [ "$attempt" -ge 20 ]; then
        mark "logdr socket unavailable after 20 seconds; retaining process snapshots"
        wait "$snapshot_pid" || true
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
mark "END capture v2" || true
exit 0
