"""Read exported XML only; report metadata facts, not a libvintf reimplementation."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CONFIGS = ROOT / 'reports/fs-configs'
documents = []
for partition in ('hyperos_system', 'hyperos_system_ext', 'hyperos_product', 'r8q_vendor', 'hyperos_vendor'):
    start = CONFIGS / partition
    for path in sorted(start.rglob('*.xml')):
        if '/etc/vintf/' not in path.as_posix():
            continue
        node = ET.fromstring(path.read_bytes())
        if node.tag not in ('manifest', 'compatibility-matrix'):
            continue
        documents.append(dict(file=path.relative_to(ROOT).as_posix(), partition=partition,
                              kind=node.tag, attrs=dict(node.attrib),
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                              vendor_ndk=[n.text for n in node.findall('./vendor-ndk/version')],
                              system_sdk=[n.text for n in node.findall('./system-sdk/version')],
                              manifest_sepolicy=[n.text for n in node.findall('./sepolicy/version')],
                              matrix_sepolicy=[n.text for n in node.findall('./sepolicy/sepolicy-version')],
                              kernel_policy=[n.text for n in node.findall('./sepolicy/kernel-sepolicy-version')]))
framework = [d for d in documents if d['attrs'].get('type') == 'framework']
devices = [d for d in documents if d['attrs'].get('type') == 'device']
summary = dict(
    status='SOURCE_GUIDED_METADATA_AUDIT_NOT_CHECKVINTF_OR_BOOT_TEST',
    source_commit='df89ad736e14ac375f61d50fa543ae7cd746a140',
    framework_matrix_levels=sorted({d['attrs']['level'] for d in framework if d['kind']=='compatibility-matrix' and 'level' in d['attrs']}),
    unlevelled_framework_matrices=[d['file'] for d in framework if d['kind']=='compatibility-matrix' and 'level' not in d['attrs']],
    framework_vendor_ndk=sorted({v for d in framework for v in d['vendor_ndk']}),
    framework_base_matrix_sepolicy=sorted({v for d in framework if 'level' not in d['attrs'] for v in d['matrix_sepolicy']}),
    framework_system_sdk=sorted({v for d in framework for v in d['system_sdk']}),
    device_declarations=[dict(file=d['file'], attrs=d['attrs'], vendor_ndk=d['vendor_ndk'],
                              sepolicy=d['manifest_sepolicy'], system_sdk=d['system_sdk'])
                         for d in devices if d['vendor_ndk'] or d['manifest_sepolicy']],
    limitations=['APEX VINTF collection is incomplete except selected VNDK30/scheduling payload checks',
                 'No kernel runtime or donor libvintf execution',
                 'No assertions that an XML edit would fix compatibility'])
(HERE/'metadata-facts.json').write_text(json.dumps(dict(summary=summary,documents=documents),indent=2)+'\n')
print(json.dumps(summary,indent=2))
