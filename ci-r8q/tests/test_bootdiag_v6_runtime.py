from pathlib import Path
import importlib.util
import unittest
from unittest.mock import patch
import test_bootdiag_v5_runtime as old

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('bootdiag_v6_render',ROOT/'tools/bootdiag_v6/render.py')
render=importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)


class Tests(unittest.TestCase):
    execute=old.Tests.execute

    def fixture(self,**options):
        with patch.object(old.package,'render_runtime',render.render_runtime):
            return old.Tests.fixture(self,**options)

    def capture(self,r):
        captures=list((r/'metadata/r8q-bootdiag-v6').glob('capture.*'))
        self.assertEqual(len(captures),1)
        return captures[0]

    def test_full_v5_capture_slots_are_preserved_and_do_not_block_v6(self):
        r,_=self.fixture()
        base=r/'metadata/r8q-bootdiag-v5'
        for i in range(3):
            d=base/('capture.%06d'%i);d.mkdir(parents=True)
            (d/'boot.log').write_text('preserve old evidence')
        result=self.execute(r)
        self.assertEqual(result.returncode,0,result.stderr)
        capture=self.capture(r)
        self.assertIn('R8QBOOT v6',(capture/'README.txt').read_text())
        self.assertTrue((capture/'COMPLETE.txt').is_file())
        self.assertTrue(all(p.read_text()=='preserve old evidence' for p in base.glob('capture.*/boot.log')))

    def test_late_crash_snapshot_and_bpf_errors_survive_stream_limits(self):
        r,_=self.fixture(flags={'large':True})
        result=self.execute(r)
        self.assertEqual(result.returncode,0,result.stderr)
        capture=self.capture(r)
        self.assertTrue((capture/'crash-late.txt').is_file())
        self.assertLessEqual((capture/'crash-late.txt').stat().st_size,65536)
        self.assertLess(sum(p.stat().st_size for p in capture.iterdir() if p.is_file()),2*1024*1024)
        calls=(r/'events').read_text()
        self.assertIn('"-d", "-b", "crash", "-t", "80"',calls)
        self.assertIn('SDM:W',calls)
        self.assertNotIn('SDM:V',calls)
        self.assertIn('hyper_bpfloader:V',calls)
        self.assertIn('linker:F',calls)
        self.assertIn('init:W',calls)
        self.assertIn('SurfaceFlinger:V',calls)
        self.assertTrue((capture/'property-late-sys.boot_completed.txt').is_file())
        self.assertTrue((capture/'property-late-init.svc.netd.txt').is_file())

    def test_readonly_metadata_remains_rejected(self):
        r,_=self.fixture(options='ro,relatime')
        result=self.execute(r)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((r/'metadata/r8q-bootdiag-v6').exists())


if __name__=='__main__':unittest.main()
