"""Guard semantic additions and rejection of unrelated source mutations."""
import importlib.util
from pathlib import Path
import struct
import unittest
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
def module(name):
    spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
V=module('prepare_vndk30_candidate');S=module('prepare_sepolicy30_candidate')


class CandidateTests(unittest.TestCase):
    def test_vndk_addition_is_only_the_actual_version(self):
        root=ET.fromstring(V.FRAGMENT)
        self.assertEqual(root.attrib,{'version':'1.0','type':'framework'})
        self.assertEqual([c.tag for c in root],['vendor-ndk'])
        self.assertEqual(root.findtext('vendor-ndk/version'),'30')

    def test_elf_arch_must_match_actual_provider(self):
        data=bytearray(64);data[:6]=b'\x7fELF\x02\x01';struct.pack_into('<HH',data,16,3,183)
        V.inspect_elf(data,2,183)
        for clas,mach in [(1,183),(2,40)]:
            with self.assertRaises(ValueError):V.inspect_elf(data,clas,mach)
        with self.assertRaises(ValueError):V.inspect_elf(b'not an ELF',2,183)

    def test_sepolicy_patch_preserves_every_other_byte(self):
        original=S.source_bytes();new=S.patch(original)
        self.assertEqual(new.replace(S.ENTRY,b'',1),original)
        before=ET.fromstring(original);after=ET.fromstring(new)
        self.assertEqual(ET.tostring(before.find('avb')),ET.tostring(after.find('avb')))
        self.assertEqual(len(before.findall('hal')),len(after.findall('hal')))
        self.assertEqual(after.findtext('sepolicy/kernel-sepolicy-version'),'30')
        versions=[e.text for e in after.findall('sepolicy/sepolicy-version')]
        self.assertEqual(versions,["30.0"]+[e.text for e in before.findall('sepolicy/sepolicy-version')])

    def test_changed_or_already_patched_matrix_rejected(self):
        original=S.source_bytes()
        for altered in [original+b'\n',S.patch(original),original.replace(b'31.0',b'99.0')]:
            with self.assertRaises(ValueError):S.patch(altered)

    def test_missing_mapping_file_would_not_be_a_supported_interface(self):
        self.assertEqual(len(S.MAPPINGS),5)
        records=S.mapping_records()
        self.assertEqual([r['file'] for r in records],list(S.MAPPINGS))
        self.assertTrue(all(r['bytes']>0 and len(r['sha256'])==64 for r in records))


if __name__=='__main__':unittest.main()
