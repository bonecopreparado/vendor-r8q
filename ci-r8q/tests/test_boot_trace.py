"""Keep the boot trace confined to fixed init milestones and the kernel log."""
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import boot_trace


class BootTraceTests(unittest.TestCase):
    def test_donor_bytes_and_fixed_action_order(self):
        donor = b'on init\n    start vold\n'
        with patch.object(boot_trace, 'DONOR_RC_SHA256', hashlib.sha256(donor).hexdigest()):
            result = boot_trace.instrument(donor)
        self.assertTrue(result.endswith(donor))
        prefix = result[:-len(donor)].decode()
        self.assertEqual(
            [line[3:] for line in prefix.splitlines() if line.startswith('on ')],
            list(boot_trace.STATES),
        )
        writes = [line for line in prefix.splitlines() if line.startswith('    ')]
        self.assertEqual(len(writes), len(boot_trace.STATES))
        self.assertTrue(all(line.startswith('    write /dev/kmsg "<4>R8QTRACE ') for line in writes))
        self.assertIn('${init.svc.vold:-unknown}', prefix)

    def test_reject_unknown_donor(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected donor init.rc'):
            boot_trace.instrument(b'on init\n')
