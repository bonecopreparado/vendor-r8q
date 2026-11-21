"""Prepare bounded diagnostics for the next ROM; retain all earlier captures."""
from pathlib import Path
import hashlib
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import package_bootdiag_v5 as previous
_render_previous=previous.render_runtime
V5_TEMPLATE_SHA='cc22d3900e8df694e380c5aa3fff7550911059c2d902dbc181e7ed190a5fa738'
V5_COLLECTOR_SHA='5721dab4a2a24d5c7c37b10db366392f0e8079720eff1e8b9afe7419f8dde29c'


def render_runtime(probe_sha):
    template=(ROOT/'tools/bootdiag_v5/runtime-template.sh').read_bytes()
    if hashlib.sha256(template).hexdigest()!=V5_TEMPLATE_SHA:
        raise ValueError('Reviewed V5 diagnostic template differs')
    script=_render_previous(probe_sha).decode()
    for old,new,count in (
        ('r8q-bootdiag-v5','r8q-bootdiag-v6',1),
        ('SDM:V','SDM:W',1),
        ('StrictController:V IptablesRestoreController:V',
         'StrictController:V IptablesRestoreController:V BpfLoader:V bpfloader:V hyper_bpfloader:V LibBpfLoader:V',1),
        ('DEBUG:F libc:F','DEBUG:F libc:F linker:F linker64:F init:W AndroidRuntime:E',1),
    ):
        if script.count(old)!=count:
            raise ValueError('Reviewed diagnostic context changed: '+old)
        script=script.replace(old,new)
    script=script.replace('R8QBOOT v5','R8QBOOT v6')
    anchor='printf \'capture=complete\\n\' > "$CAPTURE/COMPLETE.txt"'
    if script.count(anchor)!=1:
        raise ValueError('Reviewed completion marker changed')
    script=script.replace(anchor,'''# A verbose early boot can exhaust the streaming log before a later abort.
# Save a bounded fresh crash-buffer snapshot after the independent late probes.
if [ -n "$getprop" ]; then
    for late_property in sys.boot_completed init.svc.netd init.svc.surfaceflinger; do
        capture "property-late-$late_property.txt" 256 2 "$getprop" "$late_property"
    done
fi
if [ -n "$logcat" ] && [ -S /dev/socket/logdr ]; then
    capture crash-late.txt 65536 4 "$logcat" -d -b crash -t 80 -v threadtime
else
    unavailable crash-late.txt 'tool-or-logdr=unavailable'
fi
'''+anchor)
    return script.encode()


def render_collector():
    source=(ROOT/'tools/bootdiag_v5/collect-template.sh').read_bytes()
    if hashlib.sha256(source).hexdigest()!=V5_COLLECTOR_SHA:
        raise ValueError('Reviewed V5 collector differs')
    script=source.decode().replace('v5','v6').replace('V5','V6')
    guard='[ "$(getprop ro.bootmode)" = recovery ] || [ "$(getprop ro.orangefox.boot)" = 1 ] || abort "Return to OrangeFox recovery first."'
    if script.count(guard)!=1:
        raise ValueError('Reviewed recovery guard changed')
    script=script.replace(guard,'''# Some r8q TWRP builds report ro.bootmode=unknown.
if [ "$(getprop ro.bootmode)" != recovery ] && [ "$(getprop ro.orangefox.boot)" != 1 ]; then
    [ "$(getprop ro.twrp.boot)" = 1 ] &&
    [ "$(getprop init.svc.recovery)" = running ] &&
    [ "$(getprop ro.twrp.fastbootd)" != 1 ] || abort "Return to TWRP or OrangeFox recovery first."
fi''')
    anchor='case "$leaf" in boot.log|composer-native-early.txt'
    if script.count(anchor)!=1:
        raise ValueError('Reviewed nonempty Android evidence guard changed')
    script=script.replace(anchor,'case "$leaf" in crash-late.txt|boot.log|composer-native-early.txt')
    start = script.index('[ -d /sdcard ] || abort')
    end = script.index('free="$(df -Pk /sdcard/Download', start)
    storage = '''# Select already-mounted persistent storage before creating Download.
# An empty recovery /sdcard in RAM must never receive the archive.
DESTINATION=
for candidate in /sdcard /external_sd /usb_otg; do
    [ -d "$candidate" ] || continue
    resolved="$(readlink -f "$candidate")" || continue
    storage_row="$(R8Q_STORAGE_TARGET="$resolved" awk 'BEGIN {target=ENVIRON["R8Q_STORAGE_TARGET"]}
        { point=$2; if (point=="/" || target==point || index(target,point "/")==1) {
            if (length(point)>best) {best=length(point);row=point " " $3 " " $4}
        }} END {if(!best)exit 1;print row}' /proc/mounts)" || abort "Cannot inspect recovery storage mounts."
    set -- $storage_row
    [ "$#" -eq 3 ] || abort "Unexpected storage mount record."
    case "$1" in /data|/data/media|/data/media/*|/sdcard|/external_sd|/usb_otg|/storage/*|/mnt/media_rw/*) ;; *) continue;; esac
    case "$2" in ext4|f2fs|vfat|exfat|fuse|fuseblk|sdcardfs|esdfs) ;; *) continue;; esac
    case ",$3," in *,rw,*) ;; *) continue;; esac
    DESTINATION=$resolved/Download
    if [ -e "$DESTINATION" ] || [ -L "$DESTINATION" ]; then
        [ -d "$DESTINATION" ] && [ ! -L "$DESTINATION" ] || abort "Unexpected Download directory."
    else
        mkdir "$DESTINATION" || abort "Cannot create Download directory on mounted storage."
    fi
    break
done
[ -n "$DESTINATION" ] || abort "No writable mounted user storage. Mount internal storage, SD or USB first."
'''
    script = script[:start] + storage + script[end:]
    script = script.replace('df -Pk /sdcard/Download', 'df -Pk "$DESTINATION"')
    script = script.replace('OUTPUT=/sdcard/Download/', 'OUTPUT=$DESTINATION/')
    # Use plain tar on recoveries whose gzip applet cannot verify archives.
    script = ''.join(line for line in script.splitlines(keepends=True)
                     if not line.startswith('gzip -t '))
    for old, new in (
        ('tar gzip sha256sum', 'tar sha256sum'),
        ('tar/gzip features', 'tar features'),
        ('tar -czf', 'tar -cf'),
        ('tar -tzf', 'tar -tf'),
        ('tar -xOzf', 'tar -xOf'),
        ('.tar.gz', '.tar'),
        ('gzip archives', 'TAR archives'),
    ):
        script = script.replace(old, new)
    return script.encode()
