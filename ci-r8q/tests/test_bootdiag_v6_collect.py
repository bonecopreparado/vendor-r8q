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
