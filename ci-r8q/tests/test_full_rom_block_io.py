"""Native direct-I/O interface guards and real 64-bit sparse-file fixtures."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'):raise unittest.SkipTest('Host C compiler required')
        cls.tmp=tempfile.TemporaryDirectory(prefix='r8q-blockio-');cls.folder=Path(cls.tmp.name)
        cls.production=cls.folder/'production';cls.fixture=cls.folder/'fixture'
        for binary,extra in ((cls.production,[]),(cls.fixture,['-DR8Q_BLOCK_IO_FIXTURES'])):
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',*extra,
                ROOT/'tools/single_zip_helper.c','-o',binary],check=True,capture_output=True)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix='r8q-blockio-file-');self.addCleanup(t.cleanup)
        self.root=Path(t.name);self.image=self.root/'target'
        with self.image.open('wb')as f:f.truncate(10292822016)

    def call(self,binary,*args,**kw):
        return subprocess.run([str(binary),*map(str,args)],capture_output=True,timeout=15,**kw)

    def test_production_only_accepts_block_devices_even_with_fixture_environment(self):
        self.assertEqual(self.call(self.production,'--block-io-version').stdout.strip(),b'R8Q_BLOCK_IO_DIRECT_V1')
        self.assertEqual(self.call(self.fixture,'--block-io-version').stdout.strip(),b'R8Q_BLOCK_IO_FIXTURE_V1')
        for args in [('--read-block',self.image,0,4096),('--flush-block',self.image)]:
            result=self.call(self.production,*args,env=dict(os.environ,R8Q_BLOCK_IO_FIXTURES='1'))
            self.assertNotEqual(result.returncode,0);self.assertEqual(result.stdout,b'')

    def test_reads_exact_regions_beyond_4_and_8_gib_without_integer_wrap(self):
        for offset,byte in [(0,b'A'),(5*1024**3,b'B'),(9*1024**3,b'C')]:
            with self.image.open('r+b')as f:f.seek(offset);f.write(byte*4096)
            result=self.call(self.fixture,'--read-block',self.image,offset,4096)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout,byte*4096)
        result=self.call(self.fixture,'--flush-block',self.image);self.assertEqual(result.returncode,0,result.stderr)

    def test_alignment_overflow_noncanonical_ranges_and_unknown_capacities_are_refused(self):
        for offset,length in [('00','4096'),('-1','4096'),('0','0'),('1','4096'),('0','4097'),
                              ('18446744073709551616','4096'),('10292822016','4096')]:
            with self.subTest(offset=offset,length=length):
                r=self.call(self.fixture,'--read-block',self.image,offset,length)
                self.assertNotEqual(r.returncode,0);self.assertEqual(r.stdout,b'')
        wrong=self.root/'wrong';wrong.write_bytes(b'wrong-size')
        self.assertNotEqual(self.call(self.fixture,'--flush-block',wrong).returncode,0)

    def test_symlink_targets_and_wrong_argument_counts_are_refused(self):
        link=self.root/'link';link.symlink_to(self.image)
        for args in [('--read-block',link,0,4096),('--flush-block',link),('--read-block',self.image,0)]:
            self.assertNotEqual(self.call(self.fixture,*args).returncode,0)


if __name__=='__main__':unittest.main()
