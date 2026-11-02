"""Optional mapping omission must be proven against the actual filesystem."""
from pathlib import Path
import importlib.util
import subprocess
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('p1_optional_policy',ROOT/'tools/verify_p1_policy.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)


class FakeFilesystem:
    def __init__(self,present=True,entries=(),error=None):
        self.present=present;self.entries=entries;self.error=error;self.checked=[]
    def exists(self,path):
        if path!=v.OPTIONAL_MAPPING_DIRECTORY:raise AssertionError(path)
        return self.present
    def checked_directory(self,path):
        self.checked.append(path)
        if self.error:raise self.error
        return self.entries


class Tests(unittest.TestCase):
    def test_default_cil_set_unchanged(self):
        self.assertEqual(v.cil_spec(),v.SPEC)
        self.assertEqual(len(v.cil_spec()),10)

    def test_only_optional_partition_mappings_omitted(self):
        actual=set(v.cil_spec(True))
        expected=set(row for row in v.SPEC if row[2]not in{
            'system_ext_mapping_30.0.cil','system_ext_mapping_30.0.compat.cil',
            'product_mapping_30.0.cil'})
        self.assertEqual(actual,expected)
        self.assertEqual(len(actual),7)
        for row in v.SPEC:
            if row[0]=='system' or '/mapping/'not in row[1]:self.assertIn(row,actual)

    def test_absent_or_empty_directories_verified_separately(self):
        readers={'system_ext':FakeFilesystem(present=False),'product':FakeFilesystem()}
        result=v.verify_optional_mapping_absence(readers)
        self.assertEqual([(r['partition'],r['state'],r['entries'])for r in result],
                         [('system_ext','absent',0),('product','empty',0)])
        self.assertEqual(readers['system_ext'].checked,[])
        self.assertEqual(readers['product'].checked,[v.OPTIONAL_MAPPING_DIRECTORY])

    def test_any_mapping_version_or_other_entry_rejected(self):
        for name,directory in [('30.0.cil',False),('202604.cil',False),('nested',True),('link',False)]:
            for part in v.OPTIONAL_MAPPING_PARTITIONS:
                with self.subTest(part=part,name=name):
                    readers={p:FakeFilesystem()for p in v.OPTIONAL_MAPPING_PARTITIONS}
                    readers[part]=FakeFilesystem(entries=[(name,directory)])
                    with self.assertRaisesRegex(ValueError,'still contains entries'):
                        v.verify_optional_mapping_absence(readers)

    def test_unreadable_directory_cannot_prove_absence(self):
        readers={p:FakeFilesystem()for p in v.OPTIONAL_MAPPING_PARTITIONS}
        readers['product']=FakeFilesystem(error=ValueError('directory unreadable'))
        with self.assertRaisesRegex(ValueError,'unreadable'):
            v.verify_optional_mapping_absence(readers)

    def erofs_directory(self,stdout,exit_code=0):
        fs=object.__new__(v.Filesystem);fs.ext=None;fs.image=Path('fixture.img')
        with patch.object(v,'command',return_value=subprocess.CompletedProcess([],exit_code,stdout.encode(),b'')):
            return fs.checked_directory('/etc/selinux/mapping')

    def test_checked_erofs_directory_requires_valid_complete_listing(self):
        valid=('Path : /etc/selinux/mapping\nSize: 32  On-disk size: 32  directory\n'
               '       NID TYPE  FILENAME\n     1 2 .\n     2 2 ..\n')
        self.assertEqual(self.erofs_directory(valid),[])
        self.assertEqual(self.erofs_directory(valid+' 3 1 30.0.cil\n'),[('30.0.cil',False)])
        for bad in [valid.replace('directory','regular file'),valid.replace(' 2 2 ..\n',''),
                    valid+'unparsed entry\n',valid.replace('NID TYPE  FILENAME','unknown header')]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):self.erofs_directory(bad)
        with self.assertRaisesRegex(ValueError,'Unable to verify'):
            self.erofs_directory(valid,1)


if __name__=='__main__':unittest.main()
