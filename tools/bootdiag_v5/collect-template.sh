#!/sbin/sh
# Recovery-only evidence collection. No firmware partition is mounted/written.
set -eu
set -o pipefail
umask 077
[ "$#" -eq 3 ] || exit 1
OUTFD=$2
case "$OUTFD" in ''|*[!0-9]*) exit 1;; esac
ui() { printf 'ui_print %s\nui_print\n' "$*" > "/proc/self/fd/$OUTFD"; }
WORK=
MOUNTED=0
cleanup() {
    if [ "$MOUNTED" = 1 ]; then umount /metadata || ui "WARNING: Could not release collector's read-only metadata mount."; fi
    case "$WORK" in /tmp/r8q-v5-collect.??????) rm -rf "$WORK";; esac
}
trap cleanup EXIT
abort() { ui "ERROR: $*"; exit 1; }
for tool in getprop id awk cat readlink head stat df mktemp mkdir chmod tar gzip sha256sum wc rm mv timeout mount umount sync; do
    command -v "$tool" >/dev/null 2>&1 || abort "Missing recovery tool: $tool"
done
[ "$(id -u)" = 0 ] || abort "Recovery root required."
[ "$(getprop ro.product.device)" = r8q ] || abort "Only Snapdragon r8q."
[ "$(getprop ro.bootmode)" = recovery ] || [ "$(getprop ro.orangefox.boot)" = 1 ] || abort "Return to OrangeFox recovery first."
[ -d /tmp ] && [ ! -L /tmp ] || abort "Expected regular recovery temporary directory."
[ -d /sdcard ] || abort "Internal storage unavailable. Mount Data/storage in recovery first."
if [ -e /sdcard/Download ] || [ -L /sdcard/Download ]; then
    [ -d /sdcard/Download ] && [ ! -L /sdcard/Download ] || abort "Unexpected Download directory."
else
    mkdir /sdcard/Download || abort "Cannot create Download directory."
fi
# Recovery can leave an empty /sdcard directory in its RAM filesystem while
# Data is unmounted. Such a path would disappear at reboot despite a successful
# copy. Resolve it and require a writable persistent user-storage mount.
storage="$(readlink -f /sdcard/Download)" || abort "Cannot resolve Download storage."
storage_row="$(awk -v target="$storage" '
    { point=$2; if (point=="/" || target==point || index(target,point "/")==1) {
        if (length(point)>best) {best=length(point); row=point " " $3 " " $4}
    }} END {if(!best)exit 1; print row}' /proc/mounts)" || abort "Storage is not mounted. Mount Data/storage in recovery first."
set -- $storage_row
[ "$#" -eq 3 ] || abort "Unexpected storage mount record."
case "$1" in /data|/data/media|/data/media/*|/sdcard|/external_sd|/usb_otg|/storage/*|/mnt/media_rw/*) ;; *) abort "Download is not on mounted user storage. Mount Data/storage first.";; esac
case "$2" in ext4|f2fs|vfat|exfat|fuse|fuseblk|sdcardfs|esdfs) ;; *) abort "Download storage is not a supported persistent filesystem.";; esac
case ",$3," in *,rw,*) ;; *) abort "Download storage is read-only.";; esac
free="$(df -Pk /sdcard/Download | awk 'NR>1{n++;v=$4} END{if(n!=1)exit 1;print v}')" || abort "Cannot measure storage space."
case "$free" in ''|*[!0-9]*) abort "Unexpected free-space result.";; esac
[ "$free" -ge 32768 ] || abort "At least 32 MiB free storage is required."
WORK="$(mktemp -d /tmp/r8q-v5-collect.XXXXXX)" || abort "Cannot create private staging directory."
DATA=$WORK/data/r8q-logs-v5
mkdir -p "$DATA"
STATUS=$DATA/COLLECTOR-STATUS.txt
ERRORS=$DATA/COLLECTOR-ERRORS.txt
printf 'R8Q BOOTDIAG V5 recovery collection\nAndroid boot success is unknown.\n' > "$STATUS"
: > "$ERRORS"
PARTIAL=0
issue() { PARTIAL=1; printf 'MISSING_OR_PARTIAL: %s\n' "$*" >> "$STATUS"; }

# Require the exact tar/gzip features used later; never produce a ZIP-named tar.
mkdir "$WORK/tar-test"
printf 'tar-capability-check\n' > "$WORK/tar-test/check.txt"
tar -czf "$WORK/test.tar.gz" -C "$WORK/tar-test" check.txt 2>> "$ERRORS" || abort "Recovery tar cannot create gzip archives."
gzip -t "$WORK/test.tar.gz" 2>> "$ERRORS" || abort "Recovery gzip verification is unavailable."
tar -tzf "$WORK/test.tar.gz" > "$WORK/test.list" 2>> "$ERRORS" || abort "Recovery tar cannot list gzip archives."
[ "$(tar -xOzf "$WORK/test.tar.gz" check.txt 2>> "$ERRORS")" = tar-capability-check ] || abort "Recovery tar cannot verify archive members."
printf 'source\n' > "$WORK/mv-source"
mv -n "$WORK/mv-source" "$WORK/mv-fresh" 2>> "$ERRORS" || abort "Recovery mv lacks no-clobber support."
[ ! -e "$WORK/mv-source" ] && [ "$(cat "$WORK/mv-fresh")" = source ] || abort "No-clobber fresh-move verification failed."
printf 'source\n' > "$WORK/mv-source"
printf 'preserve\n' > "$WORK/mv-target"
# A skipped -n collision returns zero in older tools and one in newer GNU mv.
# The fresh move above proves flag support; a collision must preserve BOTH
# files regardless of that documented status difference.
if mv -n "$WORK/mv-source" "$WORK/mv-target" 2> "$WORK/mv-collision-stderr"; then mv_status=0; else mv_status=$?; fi
case "$mv_status" in 0|1) ;; *) abort "Recovery mv collision check failed.";; esac
[ -f "$WORK/mv-source" ] && [ "$(cat "$WORK/mv-source")" = source ] &&
    [ "$(cat "$WORK/mv-target")" = preserve ] || abort "No-clobber verification failed."

EXPECTED=/dev/block/platform/soc/1d84000.ufshc/by-name/metadata
METADATA_OK=0
metadata_ready() {
    row="$(awk '$2=="/metadata"{print $1,$3;n++} END{if(n!=1)exit 1}' /proc/mounts)" || return 1
    set -- $row
    [ "$2" = ext4 ] || return 1
    actual="$(readlink -f "$1")" || return 1
    expected="$(readlink -f "$EXPECTED")" || return 1
    [ -b "$actual" ] && [ "$actual" = "$expected" ]
}
if metadata_ready; then
    METADATA_OK=1
    printf 'metadata=already-mounted; read only by collector\n' >> "$STATUS"
elif ! awk '$2=="/metadata"{found=1} END{exit !found}' /proc/mounts; then
    if [ -d /metadata ] && [ ! -L /metadata ] && [ -b "$EXPECTED" ]; then
        if mount -t ext4 -o ro,noload,nodev,nosuid,noexec "$EXPECTED" /metadata 2>> "$ERRORS"; then
            MOUNTED=1
            if metadata_ready; then METADATA_OK=1; else issue 'metadata mount identity verification failed'; fi
        else issue 'metadata read-only mount failed'; fi
    else issue 'metadata source or mount point unavailable'; fi
else
    issue 'unexpected existing metadata mount; it was not changed or read'
fi
[ "$METADATA_OK" = 1 ] || issue 'V5 capture directory unavailable because metadata is not verified'

# Stream sources such as /proc/last_kmsg can report size zero. Read at most cap+1
# to distinguish bounded evidence from a truncated source, including procfs.
copy_stream() {
    source=$1; destination=$2; maximum=$3; description=$4
    if [ ! -f "$source" ] || [ -L "$source" ] || [ ! -r "$source" ]; then issue "$description unavailable"; return; fi
    if ! timeout 8 head -c "$((maximum+1))" "$source" > "$WORK/stream" 2>> "$ERRORS"; then
        issue "$description read failed"; rm -f "$WORK/stream"; return
    fi
    bytes="$(wc -c < "$WORK/stream")"
    if [ "$bytes" -eq 0 ]; then issue "$description empty"; rm -f "$WORK/stream"; return; fi
    if [ "$bytes" -gt "$maximum" ]; then
        issue "$description exceeded limit; saved bounded prefix"
        head -c "$maximum" "$WORK/stream" > "$destination"
        rm "$WORK/stream"
    else mv "$WORK/stream" "$destination"; fi
}

BASE=/metadata/r8q-bootdiag-v5
VALID_MEMBER=
CAPTURES=0
if [ "$METADATA_OK" = 1 ] && [ -d "$BASE" ] && [ ! -L "$BASE" ] && [ "$(stat -c '%u:%a' "$BASE")" = 0:700 ]; then
    mkdir "$DATA/r8q-bootdiag-v5"
    for directory in "$BASE"/* "$BASE"/.[!.]* "$BASE"/..?*; do
        [ -e "$directory" ] || [ -L "$directory" ] || continue
        name=${directory##*/}
        suffix=${name#capture.}
        case "$name" in capture.??????) ;; *) issue 'unexpected V5 directory entry skipped'; continue;; esac
        case "$suffix" in *[!A-Za-z0-9]*) issue 'unsafe capture suffix skipped'; continue;; esac
        if [ ! -d "$directory" ] || [ -L "$directory" ] || [ "$(stat -c '%u:%a' "$directory")" != 0:700 ]; then
            issue 'unexpected capture ownership/type skipped'; continue
        fi
        CAPTURES=$((CAPTURES+1))
        [ "$CAPTURES" -le 3 ] || { issue 'more than three V5 captures; excess skipped'; break; }
        if [ ! -f "$directory/COMPLETE.txt" ] || [ -L "$directory/COMPLETE.txt" ] ||
           [ "$(head -c 64 "$directory/COMPLETE.txt" 2>> "$ERRORS")" != capture=complete ]; then
            issue 'Android capture did not reach its completion marker; early evidence retained'
        fi
        target=$DATA/r8q-bootdiag-v5/$name
        mkdir "$target"
        files=0
        total=0
        for source in "$directory"/* "$directory"/.[!.]* "$directory"/..?*; do
            [ -e "$source" ] || [ -L "$source" ] || continue
            leaf=${source##*/}
            case "$leaf" in ''|*[!A-Za-z0-9_.@-]*) issue 'unsafe capture filename skipped'; continue;; esac
            if [ "${#leaf}" -gt 128 ] || [ ! -f "$source" ] || [ -L "$source" ]; then issue 'nonregular or excessive capture filename skipped'; continue; fi
            files=$((files+1))
            [ "$files" -le 256 ] || { issue 'capture file-count limit exceeded'; break; }
            bytes="$(stat -c '%s' "$source")" || { issue 'capture file stat failed'; continue; }
            case "$bytes" in ''|*[!0-9]*) issue 'capture size invalid'; continue;; esac
            if [ "$bytes" -gt 1048576 ] || [ "$((total+bytes))" -gt 2097152 ]; then issue 'capture byte limit exceeded; file skipped'; continue; fi
            if timeout 8 head -c "$bytes" "$source" > "$target/$leaf" 2>> "$ERRORS"; then
                copied="$(wc -c < "$target/$leaf")"
                if [ "$copied" -ne "$bytes" ]; then issue 'capture file changed or copy was short'; fi
                total=$((total+copied))
                if [ "$copied" -gt 0 ]; then
                    case "$leaf" in boot.log|composer-native-early.txt|composer-native-later.txt|composer-early.txt|composer-later.txt|kernel-version.txt|kernel-config.gz)
                        VALID_MEMBER=r8q-logs-v5/r8q-bootdiag-v5/$name/$leaf;;
                    esac
                fi
            else issue 'capture file copy failed'; fi
        done
    done
else issue 'V5 capture directory missing, symlinked, or has unexpected ownership/mode'; fi
[ -n "$VALID_MEMBER" ] || issue 'no nonempty Android V5 capture data was found'
copy_stream /proc/last_kmsg "$DATA/last_kmsg" 4194304 last_kmsg
copy_stream /tmp/recovery.log "$DATA/recovery.log" 2097152 recovery.log

if [ -d /sys/fs/pstore ] && [ ! -L /sys/fs/pstore ]; then
    mkdir "$DATA/pstore"
    count=0
    for source in /sys/fs/pstore/*; do
        [ -e "$source" ] || [ -L "$source" ] || continue
        leaf=${source##*/}
        case "$leaf" in ''|*[!A-Za-z0-9_.@-]*) issue 'unsafe pstore filename skipped'; continue;; esac
        count=$((count+1))
        [ "$count" -le 8 ] || { issue 'pstore file-count cap exceeded'; break; }
        copy_stream "$source" "$DATA/pstore/$leaf" 262144 pstore-file
    done
else printf 'pstore=unavailable (optional)\n' >> "$STATUS"; fi

if [ ! -s "$DATA/recovery.log" ] && [ ! -s "$DATA/last_kmsg" ] && [ -z "$VALID_MEMBER" ]; then
    abort "No useful evidence was collected. No empty archive was created. See recovery log."
fi
if [ "$PARTIAL" = 1 ]; then LABEL=PARTIAL; SUFFIX=-PARTIAL; else LABEL=COMPLETE; SUFFIX=; fi
printf 'collection_state=%s\nV5_capture_directories=%s\n' "$LABEL" "$CAPTURES" >> "$STATUS"
ARCHIVE=$WORK/logs.tar.gz
# All staged inputs are bounded below 15 MiB plus tar metadata. The file-size
# limit is at most 32 MiB on supported shells; verify the actual archive too.
( ulimit -f 32768; timeout 30 tar -czf "$ARCHIVE" -C "$WORK/data" r8q-logs-v5 ) 2>> "$ERRORS" || abort "Archive creation failed. No completed archive published."
[ "$(stat -c '%s' "$ARCHIVE")" -le 33554432 ] || abort "Archive exceeded 32 MiB bound."
gzip -t "$ARCHIVE" 2>> "$ERRORS" || abort "Archive gzip integrity failed."
tar -tzf "$ARCHIVE" > "$WORK/members" 2>> "$ERRORS" || abort "Archive listing failed."
if [ -s "$DATA/recovery.log" ]; then
    [ "$(tar -xOzf "$ARCHIVE" r8q-logs-v5/recovery.log 2>> "$ERRORS" | wc -c)" -gt 0 ] || abort "Archive verification lost recovery.log."
fi
if [ -n "$VALID_MEMBER" ]; then
    [ "$(tar -xOzf "$ARCHIVE" "$VALID_MEMBER" 2>> "$ERRORS" | wc -c)" -gt 0 ] || abort "Archive verification lost Android capture data."
fi
token=${WORK##*.}
case "$token" in ??????) ;; *) abort "Unexpected fresh output suffix.";; esac
OUTPUT=/sdcard/Download/R8Q-BOOTDIAG-V5-logs-$token$SUFFIX.tar.gz
PENDING=$OUTPUT.inprogress
( set -C; cat "$ARCHIVE" > "$PENDING" ) || abort "Cannot write a fresh storage file; previous files were preserved."
expected="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
[ "$(sha256sum "$PENDING" | awk '{print $1}')" = "$expected" ] || abort "Storage copy hash differs; do not share the .inprogress file."
[ ! -e "$OUTPUT" ] && [ ! -L "$OUTPUT" ] || abort "Output collision; refusing to replace a file."
mv -n "$PENDING" "$OUTPUT" || abort "Cannot publish verified archive."
[ ! -e "$PENDING" ] && [ -s "$OUTPUT" ] || abort "Output collision; existing archive preserved."
sync || abort "Storage sync failed; archive exists but durability is unconfirmed."
ui "$LABEL evidence archive saved: $OUTPUT"
if [ "$PARTIAL" = 1 ]; then ui "Some evidence was missing or bounded. This is a PARTIAL collection; attach it with the error report."; fi
ui "Attach this .tar.gz file manually. It is not a flashable ZIP and does not mean Android booted."
ui "Existing captures, firmware, keys and user files were preserved."
exit 0
