"""Exercise boot helper I/O using regular temporary files, never devices."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'tools/boot_memory/boot_io.c'
BOOT_BYTES = 67108864


def file_sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='r8q-bootio-build-')
        cls.root = Path(cls.temp.name)
        cls.production = cls.root/'bootio-production'
        cls.fixture = cls.root/'bootio-fixture'
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('Host C compiler is needed for native I/O tests')
        flags = ['-std=c11','-O2','-Wall','-Wextra','-Werror']
        subprocess.run([cc,*flags,str(SOURCE),'-o',str(cls.production)],check=True,capture_output=True)
        subprocess.run([cc,*flags,'-DR8Q_TEST_REGULAR_FILES',str(SOURCE),'-o',str(cls.fixture)],check=True,capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='r8q-bootio-')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)

    def image(self,name,byte=b'\0'):
        p=self.path/name
        with p.open('wb')as f:
            for _ in range(64):f.write(byte*1048576)
        return p

    def call(self,binary,*args,**kw):
        return subprocess.run([str(binary),*map(str,args)],capture_output=True,timeout=20,**kw)

    def test_build_mode_markers_are_explicit_and_mutually_exclusive(self):
        for binary,chosen,absent in [
            (self.production,b'R8Q_BOOTIO_PRODUCTION_BLOCK_ONLY_V1',b'R8Q_BOOTIO_TEST_REGULAR_FILES_V1'),
            (self.fixture,b'R8Q_BOOTIO_TEST_REGULAR_FILES_V1',b'R8Q_BOOTIO_PRODUCTION_BLOCK_ONLY_V1')]:
            result=self.call(binary,'--version')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),chosen)
            raw=binary.read_bytes();self.assertIn(chosen,raw);self.assertNotIn(absent,raw)

    def test_production_rejects_regular_targets_even_with_fixture_environment(self):
        source=self.image('source',b'S');target=self.image('target',b'T')
        env=dict(os.environ,R8Q_TEST_REGULAR_FILES='1')
        for args in [('--check',target),('--read',target),('--write',source,target)]:
            result=self.call(self.production,*args,env=env)
            self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertEqual(file_sha(target),
                         hashlib.sha256(b'T'*BOOT_BYTES).hexdigest())

    def test_fixture_full_copy_fresh_read_and_persistent_file_sync(self):
        source=self.image('source',b'S');target=self.image('target',b'T')
        result=self.call(self.fixture,'--check',target);self.assertEqual(result.returncode,0,result.stderr)
        result=self.call(self.fixture,'--write',source,target);self.assertEqual(result.returncode,0,result.stderr)
        expected=file_sha(source)
        self.assertEqual(file_sha(target),expected)
        out=self.path/'readback'
        with out.open('wb')as f:
            result=subprocess.run([str(self.fixture),'--read',str(target)],stdout=f,stderr=subprocess.PIPE,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(out.stat().st_size,BOOT_BYTES)
        self.assertEqual(file_sha(out),expected)
        result=self.call(self.fixture,'--sync-file',out);self.assertEqual(result.returncode,0,result.stderr)
        result=self.call(self.fixture,'--sync-directory',self.path);self.assertEqual(result.returncode,0,result.stderr)
        alias=self.path/'dir-link';alias.symlink_to(self.path)
        self.assertNotEqual(self.call(self.fixture,'--sync-directory',alias).returncode,0)

    def test_wrong_sizes_and_symlinks_are_refused_before_target_changes(self):
        source=self.image('source',b'S');target=self.image('target',b'T')
        before=file_sha(target)
        short=self.path/'short';short.write_bytes(b'short')
        large=self.path/'large'
        with large.open('wb')as f:f.truncate(BOOT_BYTES+1)
        symlink=self.path/'link';symlink.symlink_to(source)
        targetlink=self.path/'target-link';targetlink.symlink_to(target)
        cases=[('--write',short,target),('--write',large,target),('--write',symlink,target),
               ('--write',source,targetlink),('--write',source,short),('--read',short),
               ('--check',large),('--check',targetlink),('--sync-file',symlink)]
        for args in cases:
            with self.subTest(args=args):
                result=self.call(self.fixture,*args);self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertEqual(file_sha(target),before)

    def test_same_inode_source_and_target_and_unknown_commands_are_refused(self):
        source=self.image('source',b'S');alias=self.path/'hardlink';os.link(source,alias)
        for args in [('--write',source,source),('--write',source,alias),('--anything',source)]:
            result=self.call(self.fixture,*args);self.assertNotEqual(result.returncode,0,result.stdout)


if __name__=='__main__':unittest.main()
