"""Execute the ordered addon in file fixtures; no phone or native ELF execution."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
import test_bootdiag as legacy

ROOT = Path(__file__).resolve().parents[2]
SHELL = os.environ.get('MKSH_BINARY', '/bin/bash')
spec = importlib.util.spec_from_file_location('package_bootdiag_v5', ROOT / 'tools/package_bootdiag_v5.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
PROBE = b'fixture native bytes; never executed by these installation tests\n'
PROBE_SHA = hashlib.sha256(PROBE).hexdigest()


class Tests(unittest.TestCase):
    def fixture(self, version=3, flags=None, **kwargs):
        r = legacy.Tests.fixture(self, flags=flags, **kwargs)
        (r / 'vendor/etc/init/r8q-bootdiag.rc').write_bytes((ROOT / 'tools/bootdiag/init.rc').read_bytes())
        (r / 'vendor/bin/r8q-bootdiag.sh').write_bytes(self.source(version))
        mock = legacy.WRAPPER.replace(
            "if flags.get('activate_rc') and args[-1].endswith('r8q-bootdiag.rc'):sys.exit(1)",
            "if flags.get('activate_script') and args[-1].endswith('r8q-bootdiag.sh'):sys.exit(1)\n if flags.get('activate_probe') and '/r8q-composer-dump-' in args[-1]:sys.exit(1)")
        (r / 'bin/mv').write_text(mock)
        remover = '''#!/usr/bin/env python3
from pathlib import Path
import json,os,sys
r=Path(os.environ['FIXTURE_ROOT']);f=json.loads((r/'flags.json').read_text())
if f.get('remove_probe') and any('/r8q-composer-dump-' in a for a in sys.argv[1:]):sys.exit(1)
if f.get('remove_stage') and any('/.r8q-bootdiag-v5.' in a for a in sys.argv[1:]):sys.exit(1)
os.execv('/usr/bin/rm',['rm']+sys.argv[1:])
'''
        (r / 'bin/rm').write_text(remover)
        (r / 'bin/rm').chmod(0o755)
        return r

    def source(self, version):
        if version == 5:
            return package.render_runtime(PROBE_SHA)
        path = 'tools/bootdiag/bootdiag.sh' if version == 3 else 'tools/bootdiag_v4/runtime.sh'
        return (ROOT / path).read_bytes()

    def probe(self, r):
        return r / 'vendor/bin' / ('r8q-composer-dump-' + PROBE_SHA[:12])

    def execute(self, r, mode='enable', corrupt=False):
        archive = r / 'fixture.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            for version in (3, 4, 5):
                z.writestr(f'payload/runtime-v{version}.sh', self.source(version))
            z.writestr('payload/composer-dump', b'damaged' if corrupt else PROBE)
        text = package.render_upgrade(mode, PROBE_SHA).decode()
        ref = (ROOT / 'patches/0007-policy-integration/candidate/vendor/etc/init/hw/init.qcom.rc').read_bytes()
        text = text.replace(package.VENDOR_SHA, hashlib.sha256(ref).hexdigest())
        for path in ('/sys/class/block', '/proc/mounts', '/vendor', '/tmp/r8q-bootdiag-v5'):
            text = text.replace(path, '@FIX@' + path)
        text = text.replace('@FIX@', str(r))
        script = r / 'run.sh'
        script.write_text(text)
        return subprocess.run([SHELL, script, '3', '1', archive], env=dict(os.environ,
            PATH=str(r / 'bin') + ':' + os.environ['PATH'], FIXTURE_ROOT=str(r)),
            capture_output=True, text=True, timeout=20)

    def test_enable_idempotence_and_matching_restoration_from_v3_and_v4(self):
        for version in (3, 4):
            r = self.fixture(version=version)
            rc = r / 'vendor/etc/init/r8q-bootdiag.rc'
            original_rc = rc.read_bytes()
            for _ in range(2):
                result = self.execute(r)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((r / 'vendor/bin/r8q-bootdiag.sh').read_bytes(), self.source(5))
                self.assertEqual(self.probe(r).read_bytes(), PROBE)
                self.assertEqual(self.probe(r).stat().st_mode & 0o777, 0o755)
                self.assertEqual(rc.read_bytes(), original_rc)
                self.assertIn(' ro,', (r / 'proc/mounts').read_text())
            for _ in range(2):
                result = self.execute(r, f'restore-v{version}')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((r / 'vendor/bin/r8q-bootdiag.sh').read_bytes(), self.source(version))
                self.assertFalse(self.probe(r).exists())
                self.assertEqual(rc.read_bytes(), original_rc)

    def test_wrong_device_mount_type_or_logical_name_abort_before_remount(self):
        for options in (dict(flags={'device': True}), dict(mounted=False), dict(fs='erofs'), dict(dm='system')):
            r = self.fixture(**options)
            before = (r / 'vendor/bin/r8q-bootdiag.sh').read_bytes()
            result = self.execute(r)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((r / 'vendor/bin/r8q-bootdiag.sh').read_bytes(), before)
            self.assertFalse(self.probe(r).exists())
            self.assertNotIn('mount ', (r / 'events').read_text())

    def test_unknown_runtime_rc_vendor_or_helper_and_symlinks_are_preserved(self):
        for name in ('vendor/bin/r8q-bootdiag.sh', 'vendor/etc/init/r8q-bootdiag.rc',
                     'vendor/etc/init/hw/init.qcom.rc', 'probe', 'probe-symlink'):
            r = self.fixture()
            path = self.probe(r) if name.startswith('probe') else r / name
            if name == 'probe-symlink':
                path.symlink_to('missing-unknown-file')
            else:
                path.write_bytes(b'unknown user file')
            result = self.execute(r)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(path.is_symlink() if name == 'probe-symlink' else path.read_bytes() == b'unknown user file')
            self.assertNotIn('mount ', (r / 'events').read_text())

    def test_corrupt_helper_payload_aborts_before_remount(self):
        r = self.fixture()
        result = self.execute(r, corrupt=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('mount ', (r / 'events').read_text())

    def test_label_helper_activation_and_runtime_activation_failures_keep_old_runtime(self):
        for flags in ({'chcon': True}, {'activate_probe': True}, {'activate_script': True}, {'remount': True}):
            r = self.fixture(flags=flags)
            result = self.execute(r)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((r / 'vendor/bin/r8q-bootdiag.sh').read_bytes(), self.source(3))
            self.assertFalse(self.probe(r).exists())
            self.assertEqual(list((r / 'vendor/bin').glob('.r8q-bootdiag-v5.*')), [])
            self.assertIn(' ro,', (r / 'proc/mounts').read_text())

    def test_interrupted_known_helper_state_can_enable_or_restore(self):
        for mode in ('enable', 'restore-v3'):
            r = self.fixture()
            self.probe(r).write_bytes(PROBE)
            result = self.execute(r, mode)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((r / 'vendor/bin/r8q-bootdiag.sh').read_bytes(), self.source(5 if mode == 'enable' else 3))
            self.assertEqual(self.probe(r).exists(), mode == 'enable')

    def test_failed_staging_cleanup_still_attempts_vendor_readonly_remount(self):
        r = self.fixture(flags={'chcon': True, 'remove_stage': True})
        result = self.execute(r)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((r / 'vendor/bin/r8q-bootdiag.sh').read_bytes(), self.source(3))
        self.assertFalse(self.probe(r).exists())
        self.assertIn(' ro,', (r / 'proc/mounts').read_text())
        self.assertIn('private staging file remains', result.stdout)
        self.assertEqual(len(list((r / 'vendor/bin').glob('.r8q-bootdiag-v5.*'))), 1)

    def test_known_v5_with_missing_helper_can_repair_or_restore(self):
        for mode in ('enable', 'restore-v3'):
            r = self.fixture(version=5)
            result = self.execute(r, mode)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self.probe(r).exists(), mode == 'enable')

    def test_wrong_restore_target_does_not_upgrade_older_diagnostics(self):
        r = self.fixture(version=3)
        result = self.execute(r, 'restore-v4')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((r / 'vendor/bin/r8q-bootdiag.sh').read_bytes(), self.source(3))
        self.assertNotIn('mount ', (r / 'events').read_text())

    def test_restore_removal_failure_leaves_old_runtime_and_resumes(self):
        r = self.fixture(version=5, flags={'remove_probe': True})
        self.probe(r).write_bytes(PROBE)
        result = self.execute(r, 'restore-v4')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((r / 'vendor/bin/r8q-bootdiag.sh').read_bytes(), self.source(4))
        self.assertEqual(self.probe(r).read_bytes(), PROBE)
        (r / 'flags.json').write_text('{}')
        result = self.execute(r, 'restore-v4')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.probe(r).exists())


if __name__ == '__main__':
    unittest.main()
