"""Trace the checkpoints and vendor waits without changing init command order."""
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import boot_trace as trace


class BootTraceTests(unittest.TestCase):
    def setUp(self):
        self.sources = {
            ('system', trace.INIT_RC): (
                'on post-fs\n    ' + trace.CHECKPOINT + '\non late-fs\n    ' + trace.EARLY_HAL + '\n'
            ).encode(),
            ('vendor', trace.TARGET_RC): ('on late-fs\n' + ''.join(
                f'    {command}\n' for command in (trace.WAIT_HWSM, trace.WAIT_KEYMASTER, trace.MOUNT_DATA)
            )).encode(),
            ('vendor', trace.QSEE_RC): (
                'on late-fs\n    ' + trace.WAIT_QSEE + '\n    ' + trace.START_PROCA + '\n'
            ).encode(),
        }

    def read_source(self, part, path):
        return self.sources[(part, path)]

    def test_stage_keeps_waits_and_storage_commands_between_markers(self):
        pins = {key: hashlib.sha256(data).hexdigest() for key, data in self.sources.items()}
        with TemporaryDirectory() as temp, patch.object(trace, 'SOURCE_PINS', pins):
            plans = Path(temp)
            for part in ('system', 'vendor'):
                (plans/f'{part}-plan.json').write_text('{"operations": []}')
            report = trace.stage(plans, self.read_source)
            self.assertEqual(len(report['files']), 3)
            for row in report['files']:
                part, path = row['partition'], row['path']
                source = self.sources[(part, path)]
                output = (plans / ('candidate/' + part + path)).read_bytes()
                self.assertEqual(row['sha256'], hashlib.sha256(output).hexdigest())
                # The system gains a prefix as well as the insertion around commands.
                if part == 'system':
                    prefix, output = output.split(b'\n\non post-fs\n    write /dev/kmsg "<4>R8QTRACE checkpoint:begin', 1)
                    states = [line[3:].decode() for line in prefix.splitlines() if line.startswith(b'on ')]
                    self.assertEqual(states, list(trace.STATES))
                    output = b'on post-fs\n    write /dev/kmsg "<4>R8QTRACE checkpoint:begin' + output
                else:
                    self.assertTrue(all(b'R8QTRACE vendor ' in line for line in output.splitlines()
                                        if line.startswith(b'    write /dev/kmsg ')))
                original_commands = b''.join(line for line in output.splitlines(keepends=True)
                                             if not line.startswith(b'    write /dev/kmsg '))
                self.assertEqual(original_commands, source)

    def test_reject_wrong_source_before_writing_any_file(self):
        with TemporaryDirectory() as temp:
            plans = Path(temp)
            for part in ('system', 'vendor'):
                (plans/f'{part}-plan.json').write_text('{"operations": []}')
            with self.assertRaisesRegex(ValueError, 'Unexpected source for boot trace'):
                trace.stage(plans, self.read_source)
            self.assertFalse((plans/'candidate').exists())

    def test_missing_or_duplicate_anchor_is_rejected(self):
        command = ('    ' + trace.WAIT_QSEE + '\n').encode()
        for original in (b'', command * 2):
            with self.subTest(original=original), self.assertRaisesRegex(ValueError, 'single init command'):
                trace.instrument_qsee(original)
