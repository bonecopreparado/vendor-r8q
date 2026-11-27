"""Stage high-priority audit fixes across Vendor, ODM, Product and Boot ramdisk.

Addresses confirmed bootblockers and hardening issues:
- F-01: Remove broken QTI StrongBox HAL, init service, permission and manifest entry,
  plus binaryless ghost HALs in /vendor/etc/vintf/manifest.xml.
- F-04/F-08/F-09: Purge alien OnePlus/ColorOS 16 binaries, init .rc (including
  init.SN100x.nfc.rc which chown/chmod'd /data/vendor to 0777 nfc:nfc), VINTF
  fragments, OPlus jars and OnePlus build.prop overrides from odm.img.
- F-05: Unify FBEv2 (aes-256-xts:aes-256-cts:v2+inlinecrypt_optimized +
  metadata_encryption) and first-stage mounts across ramdisk and /vendor/etc/fstab.qcom.
- F-06: Inject ro.bpf.kver_override=5.10.239 into product/etc/build.prop for
  Android 17 bpfloader/netbpfload on kernel 4.19.325.
- F-07/F-12/F-17/F-18: Restore security.capability xattrs on QCOM QRTR/BT/GPS
  daemons, fix /vendor/{build,default}.prop mode 0600->0644, fix 12 GiB ZRAM
  typo in fstab.ramplus, remove stray '*/' in ueventd.rc, remove ColorOS
  brightness_sync, and remove Broadcom Wi-Fi APEX on QCA6390.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import build_boot_candidate as boot_tool
import patch_ext4_candidate as ext4

FBE2_DATA_FLAGS = (
    'latemount,wait,check,'
    'fileencryption=aes-256-xts:aes-256-cts:v2+inlinecrypt_optimized,'
    'keydirectory=/metadata/vold/metadata_encryption,'
    'sysfs_path=/sys/devices/platform/soc/1d84000.ufshc,'
    'quota,reservedsize=128M,checkpoint=fs,formattable'
)
FBE2_ODE_FLAGS = 'wait,check,fileencryption=aes-256-xts:aes-256-cts:v2+inlinecrypt_optimized,nofail'

VENDOR_DELETE_PATHS = (
    '/etc/init/android.hardware.keymaster@4.0-strongbox-service-qti.rc',
    '/bin/hw/android.hardware.keymaster@4.0-strongbox-service-qti',
    '/etc/permissions/android.hardware.strongbox_keystore.xml',
    '/bin/brightness_sync.sh',
    '/apex/com.samsung.android.wifi.broadcom.signed.apex',
)

GHOST_VINTF_HALS = frozenset({
    'android.hardware.contexthub',
    'android.hardware.radio.deprecated',
    'vendor.qti.hardware.mwqemadapter',
    'vendor.qti.hardware.radio.qcrilhook',
    'vendor.qti.hardware.radio.qtiradio',
    'vendor.qti.hardware.radio.uim_remote_server',
    'vendor.qti.hardware.soter',
})

ODM_DELETE_PATHS = (
    '/bin/hw/vendor-oplus-hardware-performance-V1-service',
    '/bin/hw/vendor-oplus-hardware-power-powermonitor-V1-service',
    '/bin/hw/vendor.nxp.hardware.nfc@1.2-service',
    '/bin/hw/vendor.oplus.hardware.charger-V3-service',
    '/bin/hw/vendor.oplus.hardware.charger@1.0-service',
    '/bin/hw/vendor.oplus.hardware.lmvibrator@1.0-service',
    '/bin/hw/vendor.oplus.hardware.nfcExtns-service',
    '/bin/hw/vendor.oplus.hardware.nfc_aidl-service',
    '/bin/hw/vendor.oplus.hardware.olc2-V1-service',
    '/bin/hw/vendor.oplus.hardware.ormsHalService-aidl-service',
    '/bin/hw/vendor.oplus.hardware.stability.oplus_project-V1-service',
    '/bin/hw/vendor.oplus.hardware.thermalmntcfg@1.0-service',
    '/bin/hw/vendor.oplus.hardware.wifi-aidl-service',
    '/bin/oplus_performance.sh',
    '/etc/build.prop.bak',
    '/etc/init/init.SN100x.nfc.rc',
    '/etc/init/oplus_performance.rc',
    '/etc/init/ormsHalService-default.rc',
    '/etc/init/vendor-oplus-hardware-performance-V1-service.rc',
    '/etc/init/vendor-oplus-hardware-power-powermonitor-V1-service.rc',
    '/etc/init/vendor.nxp.hardware.nfc@1.2-service.rc',
    '/etc/init/vendor.oplus.hardware.charger-V3-service.rc',
    '/etc/init/vendor.oplus.hardware.charger@1.0-service.rc',
    '/etc/init/vendor.oplus.hardware.lmvibrator@1.0-service.rc',
    '/etc/init/vendor.oplus.hardware.nfcExtns-service.rc',
    '/etc/init/vendor.oplus.hardware.nfc_aidl-service.rc',
    '/etc/init/vendor.oplus.hardware.olc2-V1-service.rc',
    '/etc/init/vendor.oplus.hardware.stability.oplus_project-V1-service.rc',
    '/etc/init/vendor.oplus.hardware.thermalmntcfg@1.0-service.rc',
    '/etc/init/vendor.oplus.hardware.wifi-aidl-service-qcom.rc',
    '/etc/vintf/manifest/manifest_nfc_sn100t.xml',
    '/etc/vintf/manifest/manifest_oplus_charger.xml',
    '/etc/vintf/manifest/manifest_oplus_charger_aidl.xml',
    '/etc/vintf/manifest/manifest_oplus_nfcExtns.xml',
    '/etc/vintf/manifest/manifest_oplus_nfc_aidl.xml',
    '/etc/vintf/manifest/manifest_oplus_stability_project_aidl.xml',
    '/etc/vintf/manifest/manifest_oplus_thermalmntcfg.xml',
    '/etc/vintf/manifest/manifest_performance_aidl.xml',
    '/etc/vintf/manifest/manifest_powermonitor_aidl.xml',
    '/etc/vintf/manifest/ormsHalService-default.xml',
    '/etc/vintf/manifest/vendor.oplus.hardware.olc2_aidl.xml',
    '/framework/vendor.oplus.hardware.charger-V1.0-java.jar',
    '/framework/vendor.oplus.hardware.fido.fido2ca-V1.0-java.jar',
    '/framework/vendor.oplus.hardware.lmvibrator-V1.0-java.jar',
    '/framework/vendor.oplus.hardware.orms-V1.0-java.jar',
    '/framework/vendor.oplus.hardware.osense.client-V1.0-java.jar',
    '/framework/vendor.oplus.hardware.stability.oplus_project-V1.0-java.jar',
    '/framework/vendor.oplus.hardware.thermalmntcfg-V1.0-java.jar',
)

CLEAN_ODM_BUILD_PROP = (
    '# Clean r8q ODM properties (alien OnePlus/ColorOS properties purged)\n'
    'ro.product.odm.device=r8q\n'
    'ro.product.odm.name=r8q\n'
)

CLEAN_ODM_MANIFEST = '<manifest version="2.0" type="device">\n</manifest>\n'

# Linux VFS_CAP_REVISION_2 (0x02000000) | VFS_CAP_FLAGS_EFFECTIVE (0x1)
VFS_CAP_MAGIC_REV2_EFF = 0x02000001
CAP_SETGID = 6
CAP_SETUID = 7
CAP_NET_BIND_SERVICE = 10
CAP_NET_ADMIN = 12
CAP_BLOCK_SUSPEND = 36

VENDOR_CAPABILITIES = {
    '/bin/pm-service': (CAP_NET_BIND_SERVICE,),
    '/bin/pd-mapper': (CAP_NET_BIND_SERVICE,),
    '/bin/cnss-daemon': (CAP_NET_BIND_SERVICE,),
    '/bin/loc_launcher': (CAP_SETGID, CAP_SETUID),
    '/bin/hw/android.hardware.bluetooth@1.0-service-qti': (CAP_NET_ADMIN, CAP_BLOCK_SUSPEND),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode_vfs_cap_v2(caps):
    """Encode Linux security.capability xattr (struct vfs_cap_data, rev 2)."""
    mask = 0
    for cap in caps:
        if not 0 <= cap < 64:
            raise ValueError(f'Capability out of range: {cap}')
        mask |= 1 << cap
    perm_lo = mask & 0xFFFFFFFF
    perm_hi = (mask >> 32) & 0xFFFFFFFF
    return struct.pack('<5I', VFS_CAP_MAGIC_REV2_EFF, perm_lo, 0, perm_hi, 0).hex()


def clean_vendor_manifest(raw_bytes):
    """Strip QTI StrongBox and binaryless ghost HALs from vendor manifest.xml."""
    text = raw_bytes.decode('utf-8')
    # 1. Remove strongbox instance & fqname inside android.hardware.keymaster
    text = re.sub(r'^[ \t]*<instance>strongbox</instance>[ \t]*\r?\n', '', text, flags=re.M)
    text = re.sub(r'^[ \t]*<fqname>@4\.0::IKeymasterDevice/strongbox</fqname>[ \t]*\r?\n', '', text, flags=re.M)
    # 2. Remove binaryless ghost <hal> blocks
    def _drop_ghost(match):
        block = match.group(0)
        name_match = re.search(r'<name>\s*([^<\s]+)\s*</name>', block)
        if name_match and name_match.group(1) in GHOST_VINTF_HALS:
            return ''
        return block

    updated = re.sub(r'[ \t]*<hal\b[^>]*>.*?</hal>[ \t]*\r?\n?', _drop_ghost, text, flags=re.S)
    if '<instance>strongbox</instance>' in updated or '/strongbox</fqname>' in updated:
        raise ValueError('Failed to strip strongbox from vendor manifest.xml')
    if updated == text:
        raise ValueError('Vendor manifest.xml did not change as expected')
    return updated.encode('utf-8')


def unify_fstab_fbe2(raw_bytes):
    """Unify first-stage logical mounts (system_ext + erofs) and FBEv2 userdata."""
    lines = raw_bytes.decode('utf-8').splitlines()
    out = []
    has_product_erofs = any(l.startswith('product\t/product\terofs\t') for l in lines)
    has_sys_ext = any(l.startswith('system_ext\t/system_ext\t') for l in lines)
    userdata_updated = False
    for line in lines:
        if line.startswith('product\t/product\text4\t'):
            out.append(line)
            if not has_product_erofs:
                out.append('product\t/product\terofs\tro\twait,avb,logical,first_stage_mount')
            if not has_sys_ext:
                out.append('system_ext\t/system_ext\text4\tro\twait,avb,logical,first_stage_mount')
                out.append('system_ext\t/system_ext\terofs\tro\twait,avb,logical,first_stage_mount')
            continue
        if '/prism' in line and 'nofail,avb,first_stage_mount' in line:
            out.append(line.replace('nofail,avb,first_stage_mount', 'nofail,first_stage_mount'))
            continue
        if '/optics' in line and 'nofail,avb,first_stage_mount' in line:
            out.append(line.replace('nofail,avb,first_stage_mount', 'nofail,first_stage_mount'))
            continue
        if line.startswith('/dev/block/bootdevice/by-name/userdata\t/data\tf2fs\t'):
            parts = line.split('\t')
            if len(parts) < 5:
                raise ValueError('Unexpected userdata fstab row')
            if 'inlinecrypt' not in parts[3]:
                parts[3] = parts[3] + ',inlinecrypt'
            parts[4] = FBE2_DATA_FLAGS
            out.append('\t'.join(parts))
            userdata_updated = True
            continue
        if line.startswith('/dev/block/bootdevice/by-name/keydata\t') or line.startswith('/dev/block/bootdevice/by-name/keyrefuge\t'):
            parts = line.split('\t')
            if len(parts) >= 5:
                parts[4] = FBE2_ODE_FLAGS
                out.append('\t'.join(parts))
                continue
        out.append(line)
    if not userdata_updated:
        raise ValueError('Expected userdata f2fs entry in fstab.qcom')
    return ('\n'.join(out) + '\n').encode('utf-8')


def fix_fstab_ramplus(raw_bytes):
    text = raw_bytes.decode('utf-8')
    if 'zramsize=12147483648' not in text:
        raise ValueError('Expected 12 GiB ZRAM typo in fstab.ramplus')
    return text.replace('zramsize=12147483648', 'zramsize=2147483648', 1).encode('utf-8')


def fix_ueventd_rc(raw_bytes):
    lines = raw_bytes.decode('utf-8').splitlines()
    removed = 0
    out = []
    for line in lines:
        if line.strip() == '*/':
            removed += 1
            continue
        out.append(line)
    if removed != 1:
        raise ValueError(f'Expected 1 stray comment terminator in ueventd.rc, found {removed}')
    return ('\n'.join(out) + '\n').encode('utf-8')


def strip_brightness_sync(raw_bytes):
    text = raw_bytes.decode('utf-8')
    pattern = re.compile(
        r'\n[ \t]*service brightness_sync /vendor/bin/brightness_sync\.sh\n'
        r'(?:[ \t]+[^\n]*\n)+',
    )
    updated, count = pattern.subn('\n# Removed incompatible ColorOS brightness_sync service.\n', text)
    if count != 1:
        raise ValueError(f'Expected 1 brightness_sync service block in init.qcom.rc, found {count}')
    return updated.encode('utf-8')


def add_bpf_override(raw_bytes):
    text = raw_bytes.decode('utf-8')
    if 'ro.bpf.kver_override=' in text:
        return raw_bytes
    if not text.endswith('\n'):
        text += '\n'
    text += '# Android 17 bpfloader compatibility for SM8250 kernel 4.19.325 (LineageOS r8q parity)\n'
    text += 'ro.bpf.kver_override=5.10.239\n'
    return text.encode('utf-8')


def _stage_replace(plans, plan, part, path, old_bytes, new_bytes):
    relative = f'candidate/{part}{path}'
    dest = plans / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(new_bytes)
    existing = [r for r in plan['operations'] if r['path'] == path]
    if existing:
        if len(existing) != 1 or existing[0]['op'] != 'replace':
            raise ValueError(f'Conflicting staged operation for {part}:{path}')
        existing[0]['source'] = relative
        existing[0]['sha256'] = sha(new_bytes)
    else:
        plan['operations'].append(dict(
            op='replace', path=path, old_sha256=sha(old_bytes),
            source=relative, sha256=sha(new_bytes),
        ))


def _stage_delete(plan, path, old_bytes):
    if any(r['path'] == path for r in plan['operations']):
        raise ValueError(f'Path already staged before delete: {path}')
    plan['operations'].append(dict(op='delete', path=path, old_sha256=sha(old_bytes)))


def stage(plans, reader):
    """Apply confirmed Vendor, ODM and Product audit fixes into staged JSON plans."""
    plans = Path(plans)
    summary = dict(vendor=[], odm=[], product=[])

    # 1. Vendor plan fixes
    v_plan_path = plans / 'vendor-plan.json'
    v_plan = json.loads(v_plan_path.read_text())
    for path in VENDOR_DELETE_PATHS:
        old = reader('vendor', path)
        _stage_delete(v_plan, path, old)
        summary['vendor'].append(dict(op='delete', path=path, old_sha256=sha(old)))

    for path, transform in (
        ('/etc/vintf/manifest.xml', clean_vendor_manifest),
        ('/etc/fstab.qcom', unify_fstab_fbe2),
        ('/etc/fstab.ramplus', fix_fstab_ramplus),
        ('/ueventd.rc', fix_ueventd_rc),
    ):
        old = reader('vendor', path)
        new = transform(old)
        _stage_replace(plans, v_plan, 'vendor', path, old, new)
        summary['vendor'].append(dict(op='replace', path=path, old_sha256=sha(old), sha256=sha(new)))

    # Strip brightness_sync from the already-staged init.qcom.rc replacement
    qcom_rc_rows = [r for r in v_plan['operations'] if r['path'] == '/etc/init/hw/init.qcom.rc']
    if len(qcom_rc_rows) != 1 or qcom_rc_rows[0]['op'] != 'replace':
        raise ValueError('Expected staged init.qcom.rc replacement in vendor-plan.json')
    qcom_current = (plans / qcom_rc_rows[0]['source']).read_bytes()
    qcom_fixed = strip_brightness_sync(qcom_current)
    _stage_replace(plans, v_plan, 'vendor', '/etc/init/hw/init.qcom.rc', qcom_current, qcom_fixed)
    summary['vendor'].append(dict(op='replace', path='/etc/init/hw/init.qcom.rc',
                                  old_sha256=sha(qcom_current), sha256=sha(qcom_fixed)))
    v_plan_path.write_text(json.dumps(v_plan, indent=2) + '\n')

    # 2. ODM plan cleanup
    o_plan_path = plans / 'odm-plan.json'
    o_plan = json.loads(o_plan_path.read_text())
    for path in ODM_DELETE_PATHS:
        old = reader('odm', path)
        _stage_delete(o_plan, path, old)
        summary['odm'].append(dict(op='delete', path=path, old_sha256=sha(old)))
    for path, content in (
        ('/build.prop', CLEAN_ODM_BUILD_PROP.encode('utf-8')),
        ('/etc/build.prop', CLEAN_ODM_BUILD_PROP.encode('utf-8')),
        ('/etc/vintf/manifest.xml', CLEAN_ODM_MANIFEST.encode('utf-8')),
    ):
        old = reader('odm', path)
        _stage_replace(plans, o_plan, 'odm', path, old, content)
        summary['odm'].append(dict(op='replace', path=path, old_sha256=sha(old), sha256=sha(content)))
    o_plan_path.write_text(json.dumps(o_plan, indent=2) + '\n')

    # 3. Product BPF kernel version override
    p_plan_path = plans / 'product-plan.json'
    if p_plan_path.is_file():
        p_plan = json.loads(p_plan_path.read_text())
        old_prop = reader('product', '/etc/build.prop')
        new_prop = add_bpf_override(old_prop)
        _stage_replace(plans, p_plan, 'product', '/etc/build.prop', old_prop, new_prop)
        summary['product'].append(dict(op='replace', path='/etc/build.prop',
                                       old_sha256=sha(old_prop), sha256=sha(new_prop)))
        p_plan_path.write_text(json.dumps(p_plan, indent=2) + '\n')

    return dict(status='AUDIT_FIXES_STAGED_NOT_BOOT_TESTED', hardware_boot_confirmed=False, **summary)


def patch_boot_ramdisk_fbe2(boot_bytes):
    """Update only fstab.qcom inside a v2/newc boot image ramdisk to FBEv2."""
    parts = boot_tool.sections(boot_bytes)
    if boot_bytes[576:608] != boot_tool.boot_id(parts):
        raise ValueError('Source boot ID invalid before ramdisk FBEv2 sync')
    if not parts['tail'].startswith(b'SEANDROIDENFORCE\0') or any(parts['tail'][16:]):
        raise ValueError('Unexpected Samsung boot trailer')
    rows, tail = boot_tool.parse_cpio(parts['ramdisk'])
    matches = [r for r in rows if r['name'] == b'fstab.qcom']
    if len(matches) != 1:
        raise ValueError('Expected exactly one fstab.qcom in ramdisk')
    new_fstab = unify_fstab_fbe2(matches[0]['data'])
    rebuilt = bytearray()
    for row in rows:
        if row['name'] != b'fstab.qcom':
            rebuilt.extend(row['record'])
            continue
        header = bytearray(row['header'])
        header[54:62] = f'{len(new_fstab):08x}'.encode('ascii')
        rebuilt.extend(header)
        rebuilt.extend(row['rawname'])
        rebuilt.extend(bytes(boot_tool.align(len(rebuilt)) - len(rebuilt)))
        rebuilt.extend(new_fstab)
        rebuilt.extend(bytes(boot_tool.align(len(rebuilt)) - len(rebuilt)))
    rebuilt.extend(tail)
    parts['ramdisk'] = bytes(rebuilt)
    header = bytearray(boot_bytes[:parts['page']])
    struct.pack_into('<I', header, 16, len(rebuilt))
    header[576:608] = boot_tool.boot_id(parts)
    candidate = bytearray(header)
    for key in ('kernel', 'ramdisk', 'second', 'recovery_dtbo', 'dtb'):
        candidate.extend(parts[key])
        candidate.extend(bytes(boot_tool.align(len(candidate), parts['page']) - len(candidate)))
    candidate.extend(b'SEANDROIDENFORCE\0')
    if len(candidate) > len(boot_bytes):
        raise ValueError('FBEv2 boot candidate exceeds partition capacity')
    candidate.extend(bytes(len(boot_bytes) - len(candidate)))
    candidate = bytes(candidate)
    check = boot_tool.sections(candidate)
    if candidate[576:608] != boot_tool.boot_id(check):
        raise ValueError('Rebuilt FBEv2 boot ID mismatch')
    for key in ('kernel', 'second', 'recovery_dtbo', 'dtb'):
        if check[key] != parts[key]:
            raise ValueError('Unrelated boot section changed: ' + key)
    return candidate, dict(
        status='RAMDISK_FSTAB_FBE2_SYNCED_NOT_BOOT_TESTED',
        before_sha256=sha(boot_bytes), after_sha256=sha(candidate),
        fstab_before_sha256=sha(matches[0]['data']), fstab_after_sha256=sha(new_fstab),
    )


def repair_vendor_metadata(image, source_sha256):
    """Fix 0600 prop modes and restore missing security.capability xattrs on vendor.img."""
    image = Path(image)
    if image.is_symlink() or not image.is_file() or ext4.sha_file(image) != source_sha256:
        raise ValueError('Vendor image missing or SHA-256 differs before metadata repair')
    fixed = image.with_name('vendor-metadata-hardened.img')
    changes = []
    with tempfile.TemporaryDirectory(prefix='r8q-vendor-meta-') as tmp:
        work = Path(tmp)
        shutil.copyfile(image, fixed)
        try:
            fs = ext4.Ext4(fixed, work)
            # 1. Fix 0600 -> 0644 on /build.prop and /default.prop
            for prop_path in ('/build.prop', '/default.prop'):
                meta = fs.regular(prop_path)
                if (meta['mode'] & 0o7777) != 0o644:
                    expected = copy.deepcopy(meta)
                    expected['mode'] = (meta['mode'] & ~0o7777) | 0o644
                    fs.restore(prop_path, expected)
                    if not ext4.metadata_equal(expected, fs.stat(prop_path)):
                        raise ValueError('Failed to repair mode on ' + prop_path)
                    changes.append(dict(path=prop_path, kind='mode', before=oct(meta['mode'] & 0o7777), after='0o644'))
            # 2. Restore security.capability xattrs matching LineageOS sm8250-common/config.fs
            for bin_path, caps in sorted(VENDOR_CAPABILITIES.items()):
                meta = fs.stat(bin_path, missing_ok=True)
                if meta is None or meta['type'] != 'regular':
                    continue
                cap_hex = encode_vfs_cap_v2(caps)
                if meta['xattrs'].get('security.capability') != cap_hex:
                    expected = copy.deepcopy(meta)
                    expected['xattrs']['security.capability'] = cap_hex
                    fs.restore(bin_path, expected)
                    if not ext4.metadata_equal(expected, fs.stat(bin_path)):
                        raise ValueError('Failed to restore capability on ' + bin_path)
                    changes.append(dict(path=bin_path, kind='capability', caps=list(caps), hex=cap_hex))
            check = ext4.fsck(fixed)
            after_sha = ext4.sha_file(fixed)
            with fixed.open('rb') as stream:
                os.fsync(stream.fileno())
            os.replace(fixed, image)
        finally:
            if fixed.exists():
                fixed.unlink()
    return dict(
        status='VENDOR_METADATA_HARDENED_NOT_BOOT_TESTED',
        before_sha256=source_sha256, after_sha256=after_sha,
        changes=changes, candidate_e2fsck=check, hardware_boot_confirmed=False,
    )
