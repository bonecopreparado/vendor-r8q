"""Exercise the actual boot-only shell with the project's recovery fixtures."""
import re
import sys
import unittest
from zipfile import ZipFile

import test_boot_memory_installer as fixture
sys.path.insert(0, str(fixture.ROOT/'tools'))
import package_mount_wait as package


class MountWaitTests(unittest.TestCase):
    def prepare(self, flags=None):
        root, original, candidate = fixture.Tests.fixture(self, flags)
        paths = {
            '/dev/block/bootdevice/by-name/boot': str(root/'dev/bootlink'),
            '/proc/mounts': str(root/'proc-mounts'),
            '/sys/class/power_supply/battery/': str(root/'battery')+'/',
            '/tmp': str(root/'tmp'),
        }
        with ZipFile(root/'fixture.zip') as source:
            compressed = source.read('images/boot.img.gz')
            helper = source.read('tools/bootio')
        script = package.render(original, candidate, package.sha(compressed), package.sha(helper), 'diagnostic').decode()
        script = script.replace('[ -b "$BOOT" ]', '[ -f "$BOOT" ]')
        script = re.sub('|'.join(re.escape(p) for p in paths), lambda m: paths[m.group()], script)
        (root/'run.sh').write_text(script)
        # The installer should work without /data mounted.
        (root/'proc-mounts').write_text('')
        return root, original, candidate

    def test_success_then_retry(self):
        root, _, candidate = self.prepare()
        result = fixture.Tests.run_script(self, root)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(fixture.file_sha(root/'dev/boot'), candidate)
        retry = fixture.Tests.run_script(self, root)
        self.assertEqual(retry.returncode, 0, retry.stdout+retry.stderr)
        self.assertEqual(fixture.Tests.events(self, root).count('write candidate'), 1)
        self.assertEqual(list((root/'tmp').iterdir()), [])

    def test_wrong_boot_is_refused(self):
        root, _, _ = self.prepare()
        with (root/'dev/boot').open('r+b') as target:
            target.write(b'unknown boot')
        previous = fixture.file_sha(root/'dev/boot')
        result = fixture.Tests.run_script(self, root)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(fixture.file_sha(root/'dev/boot'), previous)
        self.assertNotIn('helper --write', fixture.Tests.events(self, root))

    def test_partial_write_and_mismatched_readback_restore_preflight_boot(self):
        for flag in ('write_error', 'readback_error'):
            with self.subTest(flag=flag):
                root, original, _ = self.prepare({flag: True})
                result = fixture.Tests.run_script(self, root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Previous boot restored and verified', result.stdout)
                self.assertEqual(fixture.file_sha(root/'dev/boot'), original)
