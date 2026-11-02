from pathlib import Path
import importlib.util,unittest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('rom_upload',ROOT/'ci-r8q/tools/upload_rom_gofile.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
    def check(self,data):return m.public_result(dict(status='ok',data=data),Path('HyperOS4-R8Q-P1-SINGLE.zip'),dict(bytes=100,sha256='a'*64,md5='b'*32))
    def test_verified_public_metadata_drops_tokens(self):
        r=self.check(dict(downloadPage='https://gofile.io/d/abc123',size=100,md5='b'*32,guestToken='PRIVATE'))
        self.assertNotIn('PRIVATE',str(r));self.assertTrue(r['remote_size_checked']);self.assertTrue(r['remote_md5_checked'])
    def test_wrong_size_or_md5_rejected(self):
        for changes in (dict(size=99),dict(md5='c'*32)):
            with self.assertRaises(ValueError):self.check(dict(downloadPage='https://gofile.io/d/abc123',**changes))
    def test_unexpected_download_hosts_or_parameters_rejected(self):
        for url in ('http://gofile.io/d/abc123','https://other.test/d/abc123','https://gofile.io/d/abc123?token=x','https://gofile.io@other.test/d/abc123'):
            with self.assertRaises(ValueError):self.check(dict(downloadPage=url))
if __name__=='__main__':unittest.main()
