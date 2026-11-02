"""Exercise the large-ROM uploader CLI with a bounded fake curl transport."""
from pathlib import Path
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

MODULE = Path(__file__).resolve().parents[1] / 'tools/upload_rom_gofile.py'
spec = importlib.util.spec_from_file_location('rom_streaming_upload_under_test', MODULE)
upload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload)

NAMES = ('HyperOS4-R8Q-P1-SINGLE-EXPERIMENTAL.zip',
         'HyperOS4-R8Q-P1r1-SINGLE-EXPERIMENTAL.zip')


class StreamingRomUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='r8q-rom-upload-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, name=NAMES[1]):
        path = self.root / name
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('README-TESTER.txt', 'Bounded uploader fixture; not firmware.\n')
        return path

    def invoke(self, arguments, transport=None, token=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        environment = {'GOFILE_TOKEN': token or '', 'GITHUB_STEP_SUMMARY': str(self.root / 'summary.md')}
        with patch.object(sys, 'argv', ['upload_rom_gofile.py', *map(str, arguments)]), \
                patch.dict(os.environ, environment), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                patch.object(upload.subprocess, 'run', side_effect=transport) as run:
            upload.main()
        return stdout.getvalue(), stderr.getvalue(), run

    def transport(self, path, changes=None, private_configs=None):
        content = path.read_bytes()
        def fake_curl(argv, **kwargs):
            self.assertEqual(argv[0], 'curl')
            self.assertTrue(kwargs['capture_output'])
            self.assertGreater(kwargs['timeout'], 0)
            self.assertNotIn(content, argv)
            config = Path(argv[argv.index('--config') + 1])
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            text = config.read_text()
            self.assertIn('file=@' + str(path.resolve()), text)
            self.assertIn('filename=' + path.name, text)
            if private_configs is not None:
                private_configs.append((config, text))
            data = {'downloadPage': 'https://gofile.io/d/R8Qabc12',
                    'size': len(content), 'md5': hashlib.md5(content, usedforsecurity=False).hexdigest(),
                    'guestToken': 'PRIVATE-RESPONSE-TOKEN'}
            data.update(changes or {})
            output = Path(argv[argv.index('--output') + 1])
            output.write_text(json.dumps({'status': 'ok', 'data': data}))
            return types.SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        return fake_curl

    def test_both_p1_and_p1r1_complete_real_cli_and_verify_local_identity(self):
        for name in NAMES:
            with self.subTest(name=name):
                path = self.archive(name)
                result = self.root / (name + '.json')
                private_configs = []
                stdout, stderr, run = self.invoke(
                    [path, '--result', result],
                    self.transport(path, private_configs=private_configs), token='PRIVATE-BEARER-TOKEN')
                run.assert_called_once()
                data = json.loads(result.read_text())
                self.assertEqual(data['name'], name)
                self.assertEqual(data['size'], path.stat().st_size)
                self.assertEqual(data['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertTrue(data['remote_size_checked'])
                self.assertTrue(data['remote_md5_checked'])
                self.assertEqual(data['download_page'], 'https://gofile.io/d/R8Qabc12')
                self.assertEqual(stderr, '')
                visible = stdout + stderr + result.read_text() + (self.root / 'summary.md').read_text()
                self.assertNotIn('PRIVATE-RESPONSE-TOKEN', visible)
                self.assertNotIn('PRIVATE-BEARER-TOKEN', visible)
                self.assertIn('Authorization: Bearer PRIVATE-BEARER-TOKEN', private_configs[0][1])
                self.assertFalse(private_configs[0][0].exists())

    def test_unrelated_or_future_rom_name_rejected_before_file_hash_or_network(self):
        for name in ('unrelated.zip', 'HyperOS4-R8Q-P1r2-SINGLE-EXPERIMENTAL.zip'):
            path = self.archive(name)
            with self.subTest(name=name), patch.object(upload, 'identities') as identities, \
                    patch.object(upload.subprocess, 'run') as run, \
                    patch.object(sys, 'argv', ['upload_rom_gofile.py', str(path), '--result', str(self.root / 'result.json')]), \
                    self.assertRaises(ValueError):
                upload.main()
            identities.assert_not_called()
            run.assert_not_called()

    def test_remote_size_and_md5_mismatch_do_not_publish_result(self):
        path = self.archive()
        for change in ({'size': 1}, {'md5': '0' * 32}):
            result = self.root / 'bad-result.json'
            with self.subTest(change=change), self.assertRaises(ValueError) as error:
                self.invoke([path, '--result', result], self.transport(path, changes=change))
            self.assertFalse(result.exists())
            self.assertNotIn('PRIVATE-RESPONSE-TOKEN', str(error.exception))

    def test_preflight_accepts_nonexistent_p1r1_without_hash_or_transport(self):
        path = self.root / NAMES[1]
        self.assertFalse(path.exists())
        with patch.object(upload, 'identities') as identities:
            stdout, _, run = self.invoke([path, '--check-name-only'])
        identities.assert_not_called()
        run.assert_not_called()
        self.assertIn(NAMES[1], stdout)

    def test_preflight_rejects_unrecognized_name_without_hash_or_transport(self):
        with patch.object(upload, 'identities') as identities, \
                patch.object(upload.subprocess, 'run') as run, \
                patch.object(sys, 'argv', ['upload_rom_gofile.py', 'private.log', '--check-name-only']), \
                self.assertRaises(ValueError):
            upload.main()
        identities.assert_not_called()
        run.assert_not_called()

    def test_symlink_source_rejected_before_network(self):
        actual = self.archive(NAMES[0])
        link = self.root / NAMES[1]
        link.symlink_to(actual)
        with patch.object(upload.subprocess, 'run') as run, \
                patch.object(sys, 'argv', ['upload_rom_gofile.py', str(link), '--result', str(self.root / 'result.json')]), \
                self.assertRaises(ValueError):
            upload.main()
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
