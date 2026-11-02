"""The independent full-tree comparator must catch unplanned data changes."""
from pathlib import Path
import copy
import importlib.util
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('tree_diff',ROOT/'tools/verify_ext4_tree_diff.py')
diff=importlib.util.module_from_spec(spec);spec.loader.exec_module(diff)


class TreeDiffTests(unittest.TestCase):
    def fixture(self):
        entries={'/':dict(kind='directory',mode=0o40755,uid=0,gid=0,flags=0,children=['one','two','link']),
                 '/one':dict(kind='regular',mode=0o100644,uid=0,gid=0,flags=0,bytes=3,sha256='a'*64),
                 '/two':dict(kind='regular',mode=0o100644,uid=0,gid=0,flags=0,bytes=3,sha256='b'*64),
                 '/link':dict(kind='symlink',mode=0o120777,uid=0,gid=0,flags=0,target='one')}
        return dict(entries=entries,hardlink_groups=[],counts=dict(regular=2,symlink=1,directory=1))

    def test_exact_planned_replacement_and_removal_pass(self):
        before=self.fixture();after=copy.deepcopy(before)
        after['entries']['/one']['sha256']='c'*64
        del after['entries']['/two'];after['entries']['/']['children'].remove('two')
        report=diff.compare(before,after,dict(changes=[dict(op='replace',path='/one',old_sha256='a'*64,sha256='c'*64),dict(op='delete',path='/two',old_sha256='b'*64)]))
        self.assertEqual(report['failures'],[])
        self.assertEqual(report['content_changed'],['/one'])
        self.assertEqual(report['removed'],['/two'])

    def test_unplanned_file_change_is_rejected(self):
        before=self.fixture();after=copy.deepcopy(before);after['entries']['/two']['sha256']='c'*64
        self.assertTrue(diff.compare(before,after,dict(changes=[]))['failures'])

    def test_symlink_and_owner_changes_are_rejected(self):
        for key,value in [('target','two'),('uid',1000)]:
            with self.subTest(key=key):
                before=self.fixture();after=copy.deepcopy(before);after['entries']['/link'][key]=value
                self.assertTrue(diff.compare(before,after,dict(changes=[]))['failures'])

    def test_wrong_expected_digest_and_unplanned_entries_are_rejected(self):
        before=self.fixture();after=copy.deepcopy(before)
        wrong=diff.compare(before,after,dict(changes=[dict(op='replace',path='/one',old_sha256='0'*64,sha256='a'*64)]))
        self.assertTrue(wrong['failures'])
        del after['entries']['/two'];after['entries']['/']['children'].remove('two')
        self.assertTrue(diff.compare(before,after,dict(changes=[]))['failures'])

    def test_hardlink_topology_changes_are_rejected(self):
        before=self.fixture();after=copy.deepcopy(before);after['hardlink_groups']=[['/one','/two']]
        self.assertFalse(diff.compare(before,after,dict(changes=[]))['hardlink_topology_preserved'])
        self.assertTrue(diff.compare(before,after,dict(changes=[]))['failures'])


if __name__=='__main__':unittest.main()
