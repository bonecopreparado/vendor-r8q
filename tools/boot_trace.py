"""Stage bounded Android init milestones for recovery's last_kmsg."""
import hashlib
import json


INIT_RC = '/system/etc/init/hw/init.rc'
TARGET_RC = '/etc/init/hw/init.target.rc'
QSEE_RC = '/etc/init/pa_daemon_qsee.rc'
SOURCE_PINS = {
    ('system', INIT_RC): '40277b3c46beb95a6379bf61828574c5bd2cede072c95d5de806287ff97f3ec5',
    ('vendor', TARGET_RC): 'd1e82b089bac28ef1150c1e2ff1300fae70992d7b8be151ffa9256aa4d3873a1',
    ('vendor', QSEE_RC): 'e3828b572fd3795620619788755891eefc49809c1695cefd84a96143b9f223a3',
}
STATES = (
    'early-init', 'init', 'late-init', 'early-fs', 'fs', 'post-fs', 'late-fs',
    'post-fs-data', 'zygote-start', 'boot', 'property:sys.boot_completed=1',
)
SERVICES = (
    'apexd', 'bpfloader', 'vold', 'keystore2', 'hwservicemanager',
    'surfaceflinger', 'zygote',
)
CHECKPOINT = 'exec - system system -- /system/bin/vdc checkpoint markBootAttempt'
EARLY_HAL = 'class_start early_hal'
WAIT_HWSM = 'wait_for_prop hwservicemanager.ready true'
WAIT_KEYMASTER = 'exec_start wait_for_keymaster'
MOUNT_DATA = 'mount_all /vendor/etc/fstab.qcom --late'
WAIT_QSEE = 'wait_for_prop vendor.sys.qseecomd.enable true'
START_PROCA = 'start proca'
VOLD = 'vold=${init.svc.vold:-unknown}'
KEYMASTER = 'keymaster=${init.svc.vendor.keymaster-4-0:-unknown}'
METADATA = 'metadata=${ro.crypto.metadata.enabled:-unknown}'
QSEE = 'qsee=${vendor.sys.qseecomd.enable:-unknown} qseecomd=${init.svc.vendor.qseecomd:-unknown}'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_marker(message):
    return f'    write /dev/kmsg "<4>R8QTRACE {message}"\n'.encode('ascii')


def instrument_commands(original, commands):
    """Insert traces on either side of exact commands without changing those commands."""
    for command, before, after in commands:
        anchor = f'    {command}\n'.encode('ascii')
        if original.count(anchor) != 1:
            raise ValueError('Expected a single init command: ' + command)
        original = original.replace(anchor, write_marker(before) + anchor + write_marker(after), 1)
    return original


def instrument_system(original):
    snapshot = ' '.join(f'{name}=${{init.svc.{name}:-unknown}}' for name in SERVICES)
    blocks = []
    for state in STATES:
        message = state
        if state in ('zygote-start', 'boot', 'property:sys.boot_completed=1'):
            message += ' ' + snapshot
        blocks.append(f'on {state}\n'.encode('ascii') + write_marker(message) + b'\n')
    body = instrument_commands(original, (
        (CHECKPOINT, f'checkpoint:begin {VOLD}', f'checkpoint:end {VOLD}'),
        (EARLY_HAL, f'early-hal:begin {KEYMASTER}', f'early-hal:end {KEYMASTER}'),
    ))
    return b''.join(blocks) + body


def instrument_target(original):
    return instrument_commands(original, (
        (WAIT_HWSM, 'vendor hwservicemanager:wait ready=${hwservicemanager.ready:-unknown}',
         'vendor hwservicemanager:ready ready=${hwservicemanager.ready:-unknown}'),
        (WAIT_KEYMASTER, f'vendor wait-for-keymaster:begin {KEYMASTER}', f'vendor wait-for-keymaster:end {KEYMASTER}'),
        (MOUNT_DATA, f'vendor mount-all:begin {VOLD} {KEYMASTER} {METADATA}',
         f'vendor mount-all:end {VOLD} {KEYMASTER} {METADATA}'),
    ))


def instrument_qsee(original):
    return instrument_commands(original, (
        (WAIT_QSEE, f'vendor qsee:wait {QSEE}', f'vendor qsee:ready {QSEE}'),
        (START_PROCA, 'vendor proca:begin', 'vendor proca:end proca=${init.svc.proca:-unknown}'),
    ))


def stage(plans, read_original):
    edits = []
    plan_paths = {part: plans / f'{part}-plan.json' for part in ('system', 'vendor')}
    records = {part: json.loads(path.read_text()) for part, path in plan_paths.items()}
    for part, path, instrument in (
        ('system', INIT_RC, instrument_system),
        ('vendor', TARGET_RC, instrument_target),
        ('vendor', QSEE_RC, instrument_qsee),
    ):
        expected = SOURCE_PINS[(part, path)]
        original = read_original(part, path)
        if sha(original) != expected:
            raise ValueError('Unexpected source for boot trace: ' + part + path)
        if any(row['path'] == path for row in records[part]['operations']):
            raise ValueError('Existing plan already edits: ' + part + path)
        content = instrument(original)
        relative = 'candidate/' + part + path
        digest = sha(content)
        records[part]['operations'].append(dict(
            op='replace', path=path, source=relative, old_sha256=expected, sha256=digest,
        ))
        edits.append((part, path, relative, digest, content))

    for _, _, relative, _, content in edits:
        target = plans / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(content)
    for part, plan_path in plan_paths.items():
        plan_path.write_text(json.dumps(records[part], indent=2) + '\n')
    return dict(sink='/dev/kmsg', events=list(STATES), files=[
        dict(partition=part, path=path, old_sha256=SOURCE_PINS[(part, path)], sha256=digest)
        for part, path, _, digest, _ in edits
    ])
