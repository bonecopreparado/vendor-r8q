"""Read-only contracts for the current R8Q port, informed by pinned Lineage trees.

This does not rewrite encryption, HALs, properties, policy or mounted files.
Property evidence from the tracked baseline is not an Android runtime capture.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

REFERENCES = {
    'lineage-23.2': {
        'LineageOS/android_device_samsung_r8q': '27bf887e7cbcda29aa047bd4fcd1760e515cd921',
        'LineageOS/android_device_samsung_sm8250-common': '7a4f1a3feaada10fef3d5afcc4f212817fcd4f84',
    },
    'lineage-24.0': {
        'LineageOS/android_device_samsung_r8q': '47316f913bd4684417442f7eb975ef1f280227d8',
        'LineageOS/android_device_samsung_sm8250-common': '576897d7c84c391b326ebd8b109062e0219b3096',
    },
}
SELECTORS = {'ro.hardware.gatekeeper': 'mdfpp', 'ro.hardware.keystore': 'mdfpp'}
MAX_CONFIG_BYTES = 2*1024**2


def sha(data): return hashlib.sha256(data).hexdigest()


def text(data):
    if not isinstance(data, bytes) or len(data) > MAX_CONFIG_BYTES or b'\0' in data:
        raise ValueError('Expected bounded text configuration')
    return data.decode('utf-8')


def properties(data):
    result = {}
    for line in text(data).splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise ValueError('Unsupported property directive; resolve imports explicitly')
        key, value = (x.strip() for x in line.split('=', 1))
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', key):
            raise ValueError('Invalid property name')
        if key in SELECTORS and key in result and result[key] != value:
            raise ValueError('Conflicting security selector: '+key)
        result[key] = value
    return result


def services(files):
    result = []
    for path, data in files.items():
        if not path.startswith('etc/init/') or not path.endswith('.rc'):
            continue
        current = None
        for raw in text(data).splitlines():
            line = raw.split('#', 1)[0].rstrip()
            if not line:
                continue
            words = line.split()
            if not line[0].isspace():
                current = None
                if words[0] == 'service' and len(words) >= 3:
                    current = dict(name=words[1], executable=words[2], interfaces=[], source=path)
                    result.append(current)
            elif current is not None and words[0] == 'interface' and len(words) == 3:
                current['interfaces'].append(words[1:])
    return result


def declared_instances(data):
    root = ET.fromstring(text(data))
    if root.tag != 'manifest' or root.get('type') != 'device':
        raise ValueError('Expected Vendor device manifest')
    found = {}
    for hal in root.findall('hal'):
        name = hal.findtext('name')
        versions = [v.text for v in hal.findall('version')]
        for interface in hal.findall('interface'):
            iface = interface.findtext('name')
            for instance in interface.findall('instance'):
                for version in versions:
                    found.setdefault(name, set()).add((version, iface, instance.text))
        for fqname in hal.findall('fqname'):
            match = re.fullmatch(r'@([0-9.]+)::([^/]+)/(.+)', fqname.text or '')
            if match: found.setdefault(name, set()).add(match.groups())
    return found


def fstab_rows(data):
    result = []
    for raw in text(data).splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line: continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError('Expected five-column Android fstab')
        result.append(dict(source=parts[0], mountpoint=parts[1], fs=parts[2],
                           mount_flags=parts[3].split(','), fs_mgr_flags=parts[4].split(',')))
    return result


def audit(files, fstab, property_source='tracked_baseline_not_runtime'):
    if not files.get('build.prop') or not files.get('etc/vintf/manifest.xml'):
        raise ValueError('Missing baseline properties or actual Vendor main manifest')
    props = properties(files['build.prop'])
    for key, value in SELECTORS.items():
        if props.get(key) != value:
            raise ValueError('Samsung HAL selector differs: '+key)
    service_rows = services(files)
    relevant = [r for r in service_rows if any(k in r['executable'] for k in ('keymaster','gatekeeper','qseecom'))]
    names = {}
    for row in relevant:
        if row['name'] in names and names[row['name']] != row:
            raise ValueError('Conflicting security init service definitions')
        names[row['name']] = row
    instances = declared_instances(files['etc/vintf/manifest.xml'])
    if ('4.0','IKeymasterDevice','default') not in instances.get('android.hardware.keymaster', set()):
        raise ValueError('Mandatory default TEE Keymaster declaration is absent')
    if not {('1.0','IGatekeeper','default'),('1.0','IGatekeeper','mdfpp')}.issubset(instances.get('android.hardware.gatekeeper', set())):
        raise ValueError('Samsung/QTI Gatekeeper instance contract differs')
    gk = [r for r in relevant if ['android.hardware.gatekeeper@1.0::IGatekeeper','mdfpp'] in r['interfaces']]
    if len(gk) != 1:
        raise ValueError('Expected exactly one explicitly configured MDFPP Gatekeeper service')
    if not any(r['executable'].endswith('/android.hardware.gatekeeper@1.0-service-qti') for r in relevant):
        raise ValueError('Expected retained QTI default Gatekeeper companion')
    km = [r for r in relevant if ['android.hardware.keymaster@4.0::IKeymasterDevice','default'] in r['interfaces']]
    if len(km) != 1:
        raise ValueError('Default TEE startup configuration is absent or ambiguous')
    rows = fstab_rows(fstab)
    if not any(r['source']=='vendor' and r['mountpoint']=='/vendor' and r['fs']=='ext4' for r in rows):
        raise ValueError('P1r4 Vendor is ext4; Lineage EROFS fstab cannot be copied wholesale')
    userdata = [r for r in rows if r['mountpoint']=='/data']
    if len(userdata)!=1 or userdata[0]['fs']!='f2fs' or 'fileencryption=ice' not in userdata[0]['fs_mgr_flags']:
        raise ValueError('Current userdata crypto differs; migration requires separate key/data review')
    if any(f.startswith('keydirectory=') for f in userdata[0]['fs_mgr_flags']):
        raise ValueError('Metadata-encryption migration requires separate key/data review')
    for source, mountpoint in [('apnhlos','/vendor/firmware_mnt'),('modem','/vendor/firmware-modem')]:
        matching = [r for r in rows if r['source']=='/dev/block/bootdevice/by-name/'+source and r['mountpoint']==mountpoint]
        if len(matching)!=1 or matching[0]['fs']!='vfat' or 'ro' not in matching[0]['mount_flags'] or 'context=u:object_r:firmware_file:s0' not in matching[0]['mount_flags']:
            raise ValueError('Physical device firmware mount contract differs: '+source)
    strongbox = ('4.0','IKeymasterDevice','strongbox') in instances.get('android.hardware.keymaster', set())
    return dict(status='STATIC_R8Q_REFERENCE_CONTRACT_PASSED_RUNTIME_UNCONFIRMED',
                references=REFERENCES, property_evidence_source=property_source,
                selectors={k:props[k] for k in SELECTORS}, shipping_api=props.get('ro.product.first_api_level'),
                gatekeeper_coexistence='QTI_default_and_Samsung_MDFPP_retained_and_valid',
                strongbox='declared_vendor_instance_not_removed' if strongbox else 'not_declared',
                default_keymaster=km[0], security_services=relevant,
                input_hashes={'fstab':sha(fstab), **{k:sha(v) for k,v in files.items() if k in {'build.prop','etc/vintf/manifest.xml'} | {r['source'] for r in relevant}}},
                runtime_boot_confirmed=False,
                limits=['Main Vendor manifest is checked; this is not merged VINTF resolution.',
                        'Init service options do not prove binary ABI or successful registration.',
                        'Upstream Samsung wrapper differs from the prebuilt stock service; replacing it requires ABI/build validation.',
                        'Lineage 24 uses FBEv2, metadata encryption and EROFS Vendor; copying those settings would change this port filesystem/crypto contract.',
                        'No files, policy, properties, encryption or firmware are changed by this audit.'])


def load_inputs(baseline, vendor_root=None):
    files = {}
    with zipfile.ZipFile(baseline) as z:
        for info in z.infolist():
            if not info.filename.startswith('configs/'): continue
            path = info.filename[len('configs/'):]
            if path != 'build.prop' and path != 'etc/vintf/manifest.xml' and not (path.startswith('etc/init/') and path.endswith('.rc')):
                continue
            if info.file_size > MAX_CONFIG_BYTES: raise ValueError('Oversized baseline config')
            files[path] = z.read(info)
    if vendor_root is not None:
        vendor_root = Path(vendor_root).resolve()
        for name in list(files):
            if name == 'build.prop': continue
            path = vendor_root/name
            if path.is_symlink() or not path.resolve().is_relative_to(vendor_root) or not path.is_file():
                if name.startswith('etc/init/'): files.pop(name); continue
                raise ValueError('Missing or escaping actual Vendor configuration')
            if path.stat().st_size > MAX_CONFIG_BYTES: raise ValueError('Oversized actual config')
            files[name] = path.read_bytes()
        actual_rc = list((vendor_root/'etc/init').rglob('*.rc'))
        if len(actual_rc) > 1024: raise ValueError('Too many actual init files')
        for path in actual_rc:
            if path.is_symlink() or not path.resolve().is_relative_to(vendor_root) or not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
                raise ValueError('Unexpected actual init file')
            files[str(path.relative_to(vendor_root))] = path.read_bytes()
    return files


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--vendor-root',type=Path)
    p.add_argument('--fstab',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() or a.output.is_symlink(): raise ValueError('Use a fresh audit output path')
    if a.vendor_root is not None and a.output.resolve().is_relative_to(a.vendor_root.resolve()):
        raise ValueError('Write the report outside the input Vendor tree')
    result=audit(load_inputs(a.baseline,a.vendor_root),a.fstab.read_bytes())
    result['baseline_archive_sha256']=sha(a.baseline.read_bytes())
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x')as f:json.dump(result,f,indent=2);f.write('\n')


if __name__=='__main__': main()
