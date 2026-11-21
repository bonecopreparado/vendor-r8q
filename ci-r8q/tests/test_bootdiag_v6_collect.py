from pathlib import Path
import importlib.util
import tarfile
import unittest
from unittest.mock import patch
import test_bootdiag_v5_collect as old

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('v6_collect_render',ROOT/'tools/bootdiag_v6/render.py')
render=importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)


class Tests(unittest.TestCase):
    execute=old.Tests.execute
    archive=old.Tests.archive

    def fixture(self,**options):
        # Reuse the actual recovery fixture/path redirection, substituting only
        # the source collector returned for that one template read.
        collector=render.render_collector().decode()
        original=Path.read_text
        template=ROOT/'tools/bootdiag_v5/collect-template.sh'
        def read(path,*args,**kwargs):
            return collector if path==template else original(path,*args,**kwargs)
        with patch.object(Path,'read_text',read):
            r=old.Tests.fixture(self,**options)
        source=r/'metadata/r8q-bootdiag-v5'
        if source.exists():source.rename(r/'metadata/r8q-bootdiag-v6')
        return r

    def test_new_crash_snapshot_is_collected_and_originals_preserved(self):
        r=self.fixture()
        capture=r/'metadata/r8q-bootdiag-v6/capture.A1B2C3'
        (capture/'boot.log').write_bytes(b'')
        (capture/'crash-late.txt').write_text('late Android fatal evidence')
        before={p:p.read_bytes() for p in (r/'metadata').rglob('*') if p.is_file()}
        result=self.execute(r)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        archive=self.archive(r)
        self.assertIn('V6',archive.name)
        self.assertNotIn('PARTIAL',archive.name)
        with tarfile.open(archive,'r:gz') as tar:
            path='r8q-logs-v6/r8q-bootdiag-v6/capture.A1B2C3/crash-late.txt'
            self.assertEqual(tar.extractfile(path).read(),b'late Android fatal evidence')
        self.assertEqual(before,{p:p.read_bytes() for p in (r/'metadata').rglob('*') if p.is_file()})

    def test_ram_backed_storage_is_still_refused(self):
        r=self.fixture(storage_mounted=False)
        result=self.execute(r)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(list((r/'sdcard/Download').glob('*.tar.gz')))

    def external_storage(self, r, options='rw'):
        external = r / 'external_sd'
        external.mkdir()
        with (r/'proc/mounts').open('a') as stream:
            stream.write(f'/dev/block/mmcblk0p1 {external} vfat {options} 0 0\n')
        script = r/'run.sh'
        text = script.read_text().replace('/external_sd', str(external))
        # Retain the absolute mount candidate and its corresponding allowlist.
        script.write_text(text)
        return external

    def test_unmounted_internal_uses_mounted_sd_and_preserves_capture(self):
        r = self.fixture(storage_mounted=False)
        external = self.external_storage(r)
        result = self.execute(r)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archives = list((external/'Download').glob('*.tar.gz'))
        self.assertEqual(len(archives), 1)
        self.assertFalse(list((r/'sdcard/Download').glob('*.tar.gz')))
        with tarfile.open(archives[0], 'r:gz') as archive:
            self.assertTrue(archive.extractfile('r8q-logs-v6/recovery.log').read())

    def test_readonly_sd_does_not_receive_download_directory(self):
        r = self.fixture(storage_mounted=False)
        external = self.external_storage(r, options='ro')
        result = self.execute(r)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((external/'Download').exists())

    def test_sd_symlink_download_is_refused(self):
        r = self.fixture(storage_mounted=False)
        external = self.external_storage(r)
        (external/'Download').symlink_to(r/'tmp', target_is_directory=True)
        result = self.execute(r)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unexpected Download directory', result.stdout)

    def toybox_gzip(self, r, corrupt=False):
        # Reject -t like recovery Toybox. Mutate the trailer before decoding
        # to prove a bad gzip is rejected, rather than accepting lost status.
        wrapper = r/'bin/gzip'
        program = """#!/usr/bin/env python3
import os, sys
from pathlib import Path
if '-t' in sys.argv:
    sys.exit(2)
"""
        if corrupt:
            program += """p=Path(sys.argv[-1])
data=bytearray(p.read_bytes())
data[-8] ^= 1
p.write_bytes(data)
"""
        program += "os.execv('/usr/bin/gzip', ['gzip'] + sys.argv[1:])\n"
        wrapper.write_text(program)
        wrapper.chmod(0o755)

    def test_recovery_gzip_without_test_option_still_verifies_archive(self):
        r = self.fixture()
        self.toybox_gzip(r)
        result = self.execute(r)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with tarfile.open(self.archive(r), 'r:gz') as archive:
            self.assertTrue(archive.extractfile('r8q-logs-v6/recovery.log').read())

    def test_decoder_crc_failure_prevents_publication(self):
        r = self.fixture()
        self.toybox_gzip(r, corrupt=True)
        result = self.execute(r)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list((r/'sdcard/Download').glob('*.tar.gz')))

    def twrp(self, r, **changes):
        props={'ro.product.device':'r8q','ro.bootmode':'unknown',
               'ro.twrp.boot':'1','init.svc.recovery':'running','ro.twrp.fastbootd':'0'}
        props.update(changes)
        (r/'bin/getprop').write_text('#!/usr/bin/env python3\nimport sys\nprint('+repr(props)+'.get(sys.argv[1],""))\n')

    def test_actual_twrp_unknown_bootmode_properties_allow_collection(self):
        r=self.fixture();self.twrp(r)
        result=self.execute(r)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue(self.archive(r).is_file())

    def test_fastbootd_android_and_absent_recovery_service_are_refused(self):
        for changes in ({'ro.twrp.fastbootd':'1'}, {'init.svc.recovery':'stopped'},
                        {'ro.twrp.boot':'0','ro.bootmode':'normal'}):
            r=self.fixture();self.twrp(r,**changes)
            result=self.execute(r)
            self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertFalse(list((r/'sdcard/Download').glob('*.tar.gz')))


if __name__=='__main__':unittest.main()
