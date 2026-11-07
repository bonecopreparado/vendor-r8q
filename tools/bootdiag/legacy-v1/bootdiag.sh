#!/system/bin/sh
# Kernel ring evidence only; never mount or change userdata/keys/properties.
set -u
KMSG=/dev/kmsg
[ -c "$KMSG" ] && [ -w "$KMSG" ] || exit 1
mark() { printf '<6>[R8QBOOT] %s\n' "$*" > "$KMSG"; }
mark "BEGIN filtered Android userspace capture v1"
attempt=0
while [ ! -S /dev/socket/logdr ]; do
    attempt=$((attempt+1))
    [ "$attempt" -lt 20 ] || { mark "logdr socket unavailable after 20 seconds"; exit 0; }
    sleep 1
done
for tool in timeout cut; do
    command -v "$tool" >/dev/null 2>&1 || { mark "Missing capture tool: $tool"; exit 0; }
done
# Deliberately exclude the kernel buffer to avoid feeding our own mirror back.
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
exit 0
