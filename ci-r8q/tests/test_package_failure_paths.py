"""Fault injection for package publication; bounded fixtures, no ROM/device writes."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import package_p1_single as package


@unittest.skipUnless(shutil.which('cc'),'Host C compiler required')
class PackageFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='r8q-package-failure-')
        cls.helper=Path(cls.temp.name)/'reader'
        subprocess.run(['cc','-D_FILE_OFFSET_BITS=64','-Os','-Wall','-Wextra','-Werror',
                        str(ROOT/'tools/single_zip_helper.c'),'-o',str(cls.helper)],check=True)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        self.tempdir=tempfile.TemporaryDirectory(prefix='r8q-package-case-')
        self.addCleanup(self.tempdir.cleanup)
        self.root=Path(self.tempdir.name)
        self.images=[]
        for part,length in [('super',8192),('boot',4096),('dtbo',4096)]:
            data=(part.encode()*length)[:length]
            source=self.root/(part+'.img');source.write_bytes(data)
            self.images.append(dict(partition=part,file=str(source),bytes=length,
                                    sha256=hashlib.sha256(data).hexdigest()))

    def build(self,output):
        return package.build(output,self.helper,self.images,require_arm64=False,host_helper=self.helper)

    def assert_no_published_files(self,folder):
        self.assertFalse(list(folder.glob('*.zip')))
        self.assertFalse(list(folder.glob('*.sha256')))
        self.assertFalse((folder/'P1-SINGLE-build-report.json').exists())
        self.assertFalse((folder/'P1-TESTER-ENGLISH.txt').exists())

    def test_second_pass_failure_never_leaves_a_flashable_filename(self):
        output=self.root/'failed.zip'
        original=package.image_chunks
        def fail_second_pass(images,archive=None,expected=None):
            rows=original(images,archive=archive,expected=expected)
            if archive is not None:raise OSError('Injected failure after writing image data')
            return rows
        with patch.object(package,'image_chunks',side_effect=fail_second_pass):
            with self.assertRaisesRegex(OSError,'Injected failure'):self.build(output)
        self.assert_no_published_files(self.root)
        self.assertFalse((self.root/'failed.zip.partial').exists())

    def test_metadata_with_valid_crc_but_changed_content_is_rejected(self):
        original=package.zipfile.ZipFile
        for target in ('P1-MANIFEST.json','README-TESTER.txt','LICENSE.txt',
                       'THIRD-PARTY-NOTICES.txt','META-INF/com/google/android/updater-script'):
            with self.subTest(member=target):
                folder=self.root/str(len(list(self.root.iterdir())));folder.mkdir()
                class CorruptMetadata(original):
                    def writestr(self,info,data,*args,**kwargs):
                        if getattr(info,'filename',info)==target:data+=b'\nchanged\n'
                        return super().writestr(info,data,*args,**kwargs)
                with patch.object(package.zipfile,'ZipFile',CorruptMetadata):
                    with self.assertRaisesRegex(ValueError,'Final metadata content differs'):
                        self.build(folder/'metadata.zip')
                self.assert_no_published_files(folder)

    def test_stale_success_sidecars_are_preserved_and_rejected(self):
        for name in ('candidate.zip.sha256','P1-TESTER-ENGLISH.txt','P1-SINGLE-build-report.json'):
            with self.subTest(sidecar=name):
                folder=self.root/name.replace('.','_');folder.mkdir()
                stale=folder/name;stale.write_text('previous build must remain')
                with self.assertRaisesRegex(ValueError,'success sidecars must be new'):
                    self.build(folder/'candidate.zip')
                self.assertEqual(stale.read_text(),'previous build must remain')
                self.assertFalse((folder/'candidate.zip').exists())

    def test_symlink_sidecar_does_not_overwrite_its_target(self):
        target=self.root/'existing.txt';target.write_text('preserve')
        (self.root/'candidate.zip.sha256').symlink_to(target)
        with self.assertRaisesRegex(ValueError,'success sidecars must be new'):
            self.build(self.root/'candidate.zip')
        self.assertEqual(target.read_text(),'preserve')
        self.assertFalse((self.root/'candidate.zip').exists())

    def test_interrupted_partial_is_preserved_and_requires_a_new_directory(self):
        partial=self.root/'candidate.zip.partial';partial.write_bytes(b'incomplete previous build')
        with self.assertRaisesRegex(ValueError,'fresh packaging directory'):
            self.build(self.root/'candidate.zip')
        self.assertEqual(partial.read_bytes(),b'incomplete previous build')
        self.assert_no_published_files(self.root)

    def test_late_sidecar_failure_rolls_back_success_markers_and_zip(self):
        original=Path.open
        def fail_report(path,*args,**kwargs):
            if path.name=='P1-SINGLE-build-report.json' and args==('x',):
                raise OSError('Injected report write failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',fail_report):
            with self.assertRaisesRegex(OSError,'Injected report write failure'):
                self.build(self.root/'candidate.zip')
        self.assert_no_published_files(self.root)
        self.assertFalse((self.root/'candidate.zip.partial').exists())


if __name__=='__main__':unittest.main()
