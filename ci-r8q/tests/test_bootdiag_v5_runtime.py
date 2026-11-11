"""Exercise added native-probe capture/failure handling in regular-file fixtures."""
from pathlib import Path
import hashlib
import importlib.util
import re
import unittest
import test_bootdiag_v4_runtime as previous

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('package_bootdiag_v5_runtime', ROOT / 'tools/package_bootdiag_v5.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
NATIVE = b'''#!/usr/bin/env python3
from pathlib import Path
import json,os,sys
r=Path(os.environ['FIXTURE_ROOT']);flags=json.loads((r/'flags.json').read_text())
with (r/'events').open('a') as f:f.write('native-probe []\\n')
print('Native HWC dump width=1080 height=2400 dpi=400 vsync=16666666')
if flags.get('large'):print('X'*200000)
sys.exit(flags.get('native_status',0))
'''
NATIVE_SHA = hashlib.sha256(NATIVE).hexdigest()


class Tests(unittest.TestCase):
    execute = previous.Tests.execute

    def fixture(self, **options):
        r = previous.Tests.fixture(self, **options)
        (r / 'vendor/bin').mkdir(parents=True)
        helper = r / 'vendor/bin' / ('r8q-composer-dump-' + NATIVE_SHA[:12])
        helper.write_bytes(NATIVE)
        helper.chmod(0o755)
        (r / 'proc/self/attr').mkdir(parents=True)
        (r / 'proc/self/attr/current').write_text('u:r:logd:s0\n')
        script = package.render_runtime(NATIVE_SHA).decode().replace('SH=/system/bin/sh', 'SH=' + previous.SHELL)
        script = script.replace('[ -b "$actual" ]', '[ -f "$actual" ]')
        paths = {'/dev/block/platform/soc/1d84000.ufshc/by-name/metadata': str(r / 'dev/metadata'),
                 '/metadata': str(r / 'metadata'), '/proc/': str(r / 'proc') + '/', '/sys/': str(r / 'sys') + '/',
                 '/dev/socket/logdr': str(r / 'logdr'), '/system/bin/': str(r / 'bin') + '/',
                 '/system_ext/bin/': str(r / 'system_ext/bin') + '/', '/vendor/bin/': str(r / 'vendor/bin') + '/'}
        script = re.sub('|'.join(re.escape(p) for p in sorted(paths, key=len, reverse=True)), lambda m: paths[m.group()], script)
        script = script.replace('[ ! -S ', '[ ! -f ').replace('[ -S ', '[ -f ')
        (r / 'run.sh').write_text(script)
        return r, helper

    def capture(self, r):
        entries = list((r / 'metadata/r8q-bootdiag-v5').glob('capture.*'))
        self.assertEqual(len(entries), 1)
        return entries[0]

    def test_native_dump_precedes_lshal_and_uses_two_bounded_rounds(self):
        r, _ = self.fixture()
        result = self.execute(r)
        self.assertEqual(result.returncode, 0, result.stderr)
        capture = self.capture(r)
        for name in ('early', 'later'):
            self.assertIn('Native HWC dump', (capture / f'composer-native-{name}.txt').read_text())
            self.assertIn('producer_status=0', (capture / f'composer-native-{name}.txt.status').read_text())
            self.assertTrue((capture / f'composer-{name}.txt').is_file())
        self.assertIn('logd:s0', (capture / 'service-context.txt').read_text())
        events = (r / 'events').read_text()
        self.assertEqual(events.count('native-probe []'), 2)
        self.assertLess(events.index('native-probe []'), events.index('lshal ['))
        self.assertTrue((capture / 'COMPLETE.txt').is_file())
        self.assertEqual(capture.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in capture.iterdir() if p.is_file()))

    def test_native_linker_or_execution_failure_retains_other_captures(self):
        r, _ = self.fixture(flags={'native_status': 126})
        result = self.execute(r)
        self.assertEqual(result.returncode, 0, result.stderr)
        capture = self.capture(r)
        self.assertIn('producer_status=126', (capture / 'composer-native-early.txt.status').read_text())
        self.assertTrue((capture / 'boot.log').is_file())
        self.assertTrue((capture / 'processes-20.txt').is_file())
        self.assertTrue((capture / 'COMPLETE.txt').is_file())

    def test_missing_changed_nonexecutable_or_symlinked_helper_is_not_executed(self):
        for kind in ('missing', 'changed', 'mode', 'symlink'):
            r, helper = self.fixture()
            if kind == 'missing': helper.unlink()
            elif kind == 'changed': helper.write_bytes(b'unreviewed native code')
            elif kind == 'mode': helper.chmod(0o644)
            else:
                helper.unlink()
                helper.symlink_to(r / 'run.sh')
            result = self.execute(r)
            self.assertEqual(result.returncode, 0, result.stderr)
            capture = self.capture(r)
            self.assertTrue((capture / 'composer-native-early.txt.status').is_file())
            self.assertNotIn('native-probe []', (r / 'events').read_text())
            self.assertTrue((capture / 'COMPLETE.txt').is_file())

    def test_full_v4_namespace_does_not_block_new_v5_evidence_and_bounds_hold(self):
        r, _ = self.fixture(flags={'large': True})
        old = r / 'metadata/r8q-bootdiag-v4'
        for index in range(3):
            d = old / f'capture.{index:06}'
            d.mkdir(parents=True)
            (d / 'boot.log').write_text('preserved old V4')
        result = self.execute(r)
        self.assertEqual(result.returncode, 0, result.stderr)
        capture = self.capture(r)
        self.assertLess(sum(p.stat().st_size for p in capture.iterdir() if p.is_file()), 2 * 1024 * 1024)
        self.assertEqual((capture / 'composer-native-early.txt').stat().st_size, 131072)
        self.assertTrue(all(p.read_text() == 'preserved old V4' for p in old.glob('capture.*/boot.log')))

    def test_metadata_mount_guards_and_new_namespace_retention_still_apply(self):
        for options in (dict(mounted=False), dict(fs='f2fs'), dict(options='ro,relatime'),
                        dict(correct_device=False), dict(flags={'free': 12287})):
            r, _ = self.fixture(**options)
            result = self.execute(r)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((r / 'metadata/r8q-bootdiag-v5').exists())
        r, _ = self.fixture()
        base = r / 'metadata/r8q-bootdiag-v5'
        for index in range(3):
            d = base / f'capture.{index:06}'
            d.mkdir(parents=True, mode=0o700)
            (d / 'boot.log').write_text('preserved V5')
        result = self.execute(r)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('capture limit reached', result.stderr)
        self.assertEqual(len(list(base.glob('capture.*'))), 3)

    def test_logcat_limit_counts_bytes_for_multibyte_text(self):
        r, _ = self.fixture()
        (r / 'bin/logcat').write_text("#!/usr/bin/env python3\nprint('é' * 2000)\n")
        (r / 'bin/logcat').chmod(0o755)
        result = self.execute(r)
        self.assertEqual(result.returncode, 0, result.stderr)
        capture = self.capture(r)
        lines = (capture / 'boot.log').read_bytes().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(lines[0]), 910)
        self.assertEqual((capture / 'boot.log.lines').read_text().strip(), '1')


if __name__ == '__main__':
    unittest.main()
