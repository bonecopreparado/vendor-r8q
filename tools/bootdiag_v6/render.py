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
    anchor='case "$leaf" in boot.log|composer-native-early.txt'
    if script.count(anchor)!=1:
        raise ValueError('Reviewed nonempty Android evidence guard changed')
    script=script.replace(anchor,'case "$leaf" in crash-late.txt|boot.log|composer-native-early.txt')
    return script.encode()
