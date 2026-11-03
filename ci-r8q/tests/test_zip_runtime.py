"""Final-archive runtime checks with a real native helper and small fixtures."""
from pathlib import Path
import hashlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import package_p1_single as package
import verify_zip_runtime as runtime


@unittest.skipUnless(shutil.which('cc'),'Host C compiler required')
class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.helper=self.folder/'reader'
        subprocess.run(['cc','-D_FILE_OFFSET_BITS=64','-O2',str(ROOT/'tools/single_zip_helper.c'),'-o',str(self.helper)],check=True)
        images=[]
        for part,length in [('super',32768),('boot',8192),('dtbo',4096)]:
            path=self.folder/(part+'.img');data=(part.encode()*length)[:length];path.write_bytes(data)
            images.append(dict(partition=part,file=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        self.archive=self.folder/'candidate.zip'
        package.build(self.archive,self.helper,images,require_arm64=False)

    def test_reads_every_payload_with_the_packaged_executable(self):
        result=runtime.verify(self.archive,self.helper,require_arm64=False)
        self.assertEqual(len(result['chunks']),3)
        self.assertEqual(result['sha256'],hashlib.sha256(self.archive.read_bytes()).hexdigest())

    def test_altered_outer_payload_is_rejected(self):
        with zipfile.ZipFile(self.archive) as source:row=source.getinfo('payloads/super-000.gz')
        with self.archive.open('r+b') as stream:
            stream.seek(row.header_offset);header=stream.read(30)
            start=row.header_offset+30+sum(struct.unpack_from('<HH',header,26))
            stream.seek(start+1);old=stream.read(1);stream.seek(start+1);stream.write(bytes([old[0]^1]))
        with self.assertRaisesRegex(ValueError,'CRC32 mismatch'):
            runtime.verify(self.archive,self.helper,require_arm64=False)

    def test_different_helper_is_rejected_before_execution(self):
        changed=self.folder/'different';changed.write_bytes(self.helper.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'differs from packaged'):
            runtime.verify(self.archive,changed,require_arm64=False)

    def test_stalled_or_overlong_runtime_stream_is_rejected(self):
        with self.assertRaises(TimeoutError):
            runtime.stream_digest([sys.executable,'-c','import time;time.sleep(2)'],1,timeout=0.1)
        with self.assertRaisesRegex(ValueError,'excess bytes'):
            runtime.stream_digest([sys.executable,'-c','print("extra")'],1)


if __name__=='__main__':unittest.main()
