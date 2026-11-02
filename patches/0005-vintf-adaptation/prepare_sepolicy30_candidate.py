"""Declare the existing 30.0 mapping interface, gated on policy integration.

This retains the device's real 30.0 interface and every existing requirement.
It never raises the vendor version or writes a partition. It produces a
candidate only when all actual framework mapping inputs match the reviewed
policy bundle. A declaration cannot repair the source CIL compile failure.
"""
from pathlib import Path
import argparse
import difflib
import hashlib
import json
import tarfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
SOURCE_SHA='cee761dcc1ecbbb5c8169cace340bd201cd8734c19e17d34ec3a1580e8e23076'
MAPPINGS=('system_mapping_30.0.cil','system_mapping_30.0.compat.cil',
          'system_ext_mapping_30.0.cil','system_ext_mapping_30.0.compat.cil','product_mapping_30.0.cil')
ANCHOR=b'        <sepolicy-version>31.0</sepolicy-version>'
ENTRY=b'        <sepolicy-version>30.0</sepolicy-version>\n'


def sha(data):return hashlib.sha256(data).hexdigest()


def source_bytes():
    bundle=ROOT/'ci-r8q/inputs/checkvintf-inputs.tar.gz'
    if sha(bundle.read_bytes())!='f17ddd9728493043147ab5506a4123e1c613e0570943962904e789ce08030432':
        raise ValueError('Pinned VINTF metadata archive differs')
    with tarfile.open(bundle) as z:
        return z.extractfile('checkvintf-inputs/root/system/etc/vintf/compatibility_matrix.device.xml').read()


def mapping_records():
    bundle=ROOT/'ci-r8q/inputs/selinux-policy-audit-bundle.tar.gz'
    if sha(bundle.read_bytes())!='e2f1f72e28e3f55ea0ce896a98b4b48e017dbf74c385538e9fb4f3484b6b2524':
        raise ValueError('Pinned policy input archive differs')
    records=[]
    with tarfile.open(bundle) as z:
        manifest=json.loads(z.extractfile('policy-bundle/manifest.json').read())
        for name in MAPPINGS:
            blob=z.extractfile('policy-bundle/original/'+name).read()
            if not blob or sha(blob)!=manifest['files']['original/'+name]:
                raise ValueError('Actual mapping source differs: '+name)
            records.append(dict(file=name,bytes=len(blob),sha256=sha(blob)))
    return records


def patch(blob):
    if sha(blob)!=SOURCE_SHA:raise ValueError('Framework matrix identity differs')
    parsed=ET.fromstring(blob)
    if parsed.attrib.get('type')!='framework' or parsed.find('sepolicy') is None:
        raise ValueError('Unexpected framework matrix shape')
    if '30.0' in [e.text for e in parsed.findall('sepolicy/sepolicy-version')]:
        raise ValueError('Framework matrix already declares 30.0')
    if blob.count(ANCHOR)!=1:raise ValueError('Expected sepolicy insertion anchor differs')
    revised=blob.replace(ANCHOR,ENTRY+ANCHOR)
    if revised.replace(ENTRY,b'',1)!=blob:raise ValueError('Unexpected matrix change')
    return revised


def build(out=HERE/'candidate'):
    mapping_evidence=mapping_records()
    source=source_bytes();candidate=patch(source)
    relative=Path('system/etc/vintf/compatibility_matrix.device.xml')
    target=out/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(candidate)
    (out/'sepolicy30.diff').write_text(''.join(difflib.unified_diff(source.decode().splitlines(True),candidate.decode().splitlines(True),
                                                               fromfile=str(relative),tofile=str(relative))))
    evidence=dict(status='ADDITIVE_DECLARATION_OF_PRESENT_MAPPING_INTERFACE_REQUIRES_COHERENT_POLICY',
                  source_sha256=SOURCE_SHA,candidate_sha256=sha(candidate),mapping_sources=mapping_evidence,
                  added_sepolicy_interface='30.0',device_declared_interface_unchanged='30.0',kernel_policy_version_unchanged=30,
                  removed_requirements=[],removed_hals=[],fcm_levels_unchanged=True,boot_ready=False,
                  required_before_image_integration=['Integrate reviewed CIL repairs and compatible app context corrections coherently.',
                                                     'Compile exact complete final composition with all six capabilities intact.',
                                                     'Run exact final context, VINTF and kernel checks; review unresolved assertion findings.',
                                                     'Do not advertise this entry with unchanged original P0 CIL, which fails compilation.'],
                  limits=['Present mapping files and candidate init compilation demonstrate a supplied mapping path, not full semantic or runtime correctness.',
                          'No Android SELinux load, framework initialization, phone boot or hardware behavior was tested.'])
    (out/'sepolicy30-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(dict(file=str(target),sha256=sha(candidate),boot_ready=False),indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=HERE/'candidate');build(ap.parse_args().out)
