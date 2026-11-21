"""Stage bounded Android init milestones for recovery's last_kmsg."""
import hashlib
import json

INIT_RC = '/system/etc/init/hw/init.rc'
DONOR_RC_SHA256 = '40277b3c46beb95a6379bf61828574c5bd2cede072c95d5de806287ff97f3ec5'
STATES = (
    'early-init', 'init', 'late-init', 'post-fs', 'post-fs-data',
    'zygote-start', 'boot', 'property:sys.boot_completed=1',
)
SERVICES = (
    'apexd', 'bpfloader', 'vold', 'keystore2', 'hwservicemanager',
    'surfaceflinger', 'zygote',
)


def instrument(original):
    digest = hashlib.sha256(original).hexdigest()
    if digest != DONOR_RC_SHA256:
        raise ValueError('Unexpected donor init.rc for the boot trace')
    snapshot = ' '.join(
        f'{name}=${{init.svc.{name}:-unknown}}' for name in SERVICES
    )
    blocks = []
    for state in STATES:
        message = f'<4>R8QTRACE {state}'
        if state in ('zygote-start', 'boot', 'property:sys.boot_completed=1'):
            message += ' ' + snapshot
        blocks.append(f'on {state}\n    write /dev/kmsg "{message}"\n\n')
    # Queue these markers before the donor's actions. Leave its bytes intact.
    return ''.join(blocks).encode('ascii') + original


def stage(plans, original):
    plan_path = plans / 'system-plan.json'
    plan = json.loads(plan_path.read_text())
    if any(row['path'] == INIT_RC for row in plan['operations']):
        raise ValueError('System plan already edits init.rc')
    content = instrument(original)
    name = 'candidate/system' + INIT_RC
    target = plans / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(content)
    digest = hashlib.sha256(content).hexdigest()
    plan['operations'].append({
        'op': 'replace', 'path': INIT_RC, 'source': name,
        'old_sha256': DONOR_RC_SHA256, 'sha256': digest,
    })
    plan_path.write_text(json.dumps(plan, indent=2) + '\n')
    return {'path': INIT_RC, 'sha256': digest, 'sink': '/dev/kmsg', 'events': list(STATES)}
