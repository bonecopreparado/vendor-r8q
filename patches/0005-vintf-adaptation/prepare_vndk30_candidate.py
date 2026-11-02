"""Declare the existing factory VNDK30 component; never change a ROM image.

The source APEX payload and framework metadata are pinned. This produces an
additive framework manifest fragment only after its actual ARM/ARM64 VNDK
providers have been enumerated and validated. Activation/linker resolution on
the phone remains a separate gate.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import struct
import tarfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
PAYLOAD=ROOT/'reports/audit-20261101/round2/linker/vndk30-payload.img'
PAYLOAD_SHA='aec3539cbd1a27b7ae39a6248a999a2e42bc608d0457f0fca4436002fc32752c'
APEX_SHA='8217800fbfc8a7b4a002fe13e5eb40e0f5d9eecf61afcf0f9d34c7da8bfe716a'
FRAGMENT='''<?xml version="1.0" encoding="utf-8"?>
<!-- Existing factory com.android.vndk.v30 provider; see evidence.json. -->
<manifest version="1.0" type="framework">
    <vendor-ndk>
        <version>30</version>
    </vendor-ndk>
</manifest>
'''


def sha(data):return hashlib.sha256(data).hexdigest()


def framework_manifest():
    bundle=ROOT/'ci-r8q/inputs/checkvintf-inputs.tar.gz'
    if sha(bundle.read_bytes())!='f17ddd9728493043147ab5506a4123e1c613e0570943962904e789ce08030432':
        raise ValueError('Pinned VINTF metadata archive differs')
    with tarfile.open(bundle) as z:
        return z.extractfile('checkvintf-inputs/root/system_ext/etc/vintf/manifest.xml').read()


def inspect_elf(data,expected_class,expected_machine):
    if len(data)<64 or data[:4]!=b'\x7fELF' or data[4]!=expected_class or data[5]!=1:
        raise ValueError('VNDK provider is not the expected little-endian ELF class')
    if struct.unpack_from('<H',data,16)[0]!=3 or struct.unpack_from('<H',data,18)[0]!=expected_machine:
        raise ValueError('VNDK provider has an unexpected ELF type/machine')


def inventory(payload=PAYLOAD):
    with payload.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
    if actual!=PAYLOAD_SHA:raise ValueError('Factory VNDK30 payload identity differs')
    spec=importlib.util.spec_from_file_location('r8q_vndk_ext4',ROOT/'ci-r8q/vendor_audit/ext4_readonly.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    records=[];lists={};provided={}
    with module.Ext4(payload) as fs:
        for stem in ('vndkcore','vndksp','vndkprivate','vndkproduct','llndk'):
            path='/etc/'+stem+'.libraries.30.txt';blob=fs.read_file(path,max_bytes=64*1024)
            names=blob.decode().splitlines()
            if len(names)!=len(set(names)) or any('/' in n or not n.endswith('.so') for n in names):
                raise ValueError('Unexpected factory VNDK library list')
            lists[stem]=dict(path=path,sha256=sha(blob),names=names)
        expected=set(lists['vndkcore']['names'])|set(lists['vndksp']['names'])
        for directory,elf_class,machine in [('/lib',1,40),('/lib64',2,183)]:
            present={};queue=[directory]
            while queue:
                parent=queue.pop()
                for name,is_directory in fs.list_dir(parent):
                    if is_directory:queue.append(parent+'/'+name)
                    else:present.setdefault(name,[]).append(parent+'/'+name)
            # The shipped list combines both architectures' compiler runtimes.
            # Those explicitly named runtimes belong only to the matching ISA.
            arch_expected={n for n in expected if not ('-aarch64-' in n and elf_class==1)
                           and not ('-arm-' in n and elf_class==2)}
            missing=sorted(arch_expected-set(present))
            if missing:raise ValueError('Missing factory VNDK providers in '+directory+': '+str(missing))
            for name in sorted(arch_expected):
                for path in present[name]:
                    data=fs.read_file(path,max_bytes=64*1024**2)
                    inspect_elf(data,elf_class,machine)
                    records.append(dict(path=path,bytes=len(data),sha256=sha(data),elf_class=elf_class,machine=machine))
            provided[directory]=len(arch_expected)
    return dict(source_payload_sha256=actual,source_apex_sha256=APEX_SHA,
                module='com.android.vndk.v30',lists=lists,providers=records,
                complete_vndkcore_and_sp_per_arch=provided,
                limits=['Factory presence is not proof of APEX activation or linker namespaces.',
                        'LLNDK libraries are provided outside this APEX and are not declared validated by this inventory.',
                        'This does not establish vendor ABI or framework/SELinux compatibility.'])


def build(out=HERE/'candidate'):
    manifest_bytes=framework_manifest();baseline=ET.fromstring(manifest_bytes)
    if baseline.attrib.get('type')!='framework' or {n.findtext('version') for n in baseline.findall('vendor-ndk')}!={'34'}:
        raise ValueError('Reviewed framework VNDK declarations changed')
    evidence=inventory()
    relative=Path('system_ext/etc/vintf/manifest/r8q-vndk30.xml')
    fragment=out/relative;fragment.parent.mkdir(parents=True,exist_ok=True);fragment.write_text(FRAGMENT)
    evidence.update(status='ADDITIVE_DECLARATION_OF_PRESENT_FACTORY_COMPONENT_NOT_BOOT_VALIDATION',
                    source_manifest_sha256=sha(manifest_bytes),added_path='/'+relative.as_posix(),
                    fragment_sha256=sha(fragment.read_bytes()),removed_files=[],removed_hals=[],
                    vendor_declared_vndk_unchanged='30',framework_existing_vndk_unchanged='34',
                    sepolicy_versions_unchanged=True,fcm_levels_unchanged=True,boot_ready=False)
    (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(dict(status=evidence['status'],providers=len(evidence['providers']),fragment=str(fragment),
                         sha256=evidence['fragment_sha256'],boot_ready=False),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=HERE/'candidate')
    build(parser.parse_args().out)
