"""Execute phone-only recovery collection against bounded regular-file fixtures."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SHELL = os.environ.get('MKSH_BINARY', shutil.which('mksh') or '/bin/bash')
MOCK = r'''#!/usr/bin/env python3
from pathlib import Path
import json,os,sys
r=Path(os.environ['FIXTURE_ROOT']);f=json.loads((r/'flags.json').read_text());name=Path(sys.argv[0]).name;args=sys.argv[1:]
with (r/'events').open('a') as stream:stream.write(name+' '+json.dumps(args)+'\n')
if name=='id':print('0')
elif name=='getprop':
 print(('wrong' if f.get('device') else 'r8q') if args[0]=='ro.product.device' else ('normal' if f.get('android') else 'recovery') if args[0]=='ro.bootmode' else '0')
elif name=='df':
 print('Filesystem 1024-blocks Used Available Capacity Mounted');print('fixture 100000 100 '+str(f.get('free',100000))+' 1% '+str(r/'sdcard/Download'))
elif name=='stat':
 path=Path(args[-1]);print(('0:'+oct(path.stat().st_mode&0o777)[2:]) if args[-2]=='%u:%a' else path.stat().st_size)
elif name=='mount':
 if f.get('mount_fail'):sys.exit(1)
 with (r/'proc/mounts').open('a') as stream:stream.write(str(r/'dev/metadata')+' '+str(r/'metadata')+' ext4 ro,noload,nodev,nosuid,noexec 0 0\n')
elif name=='umount':
 path=r/'proc/mounts';path.write_text(''.join(line+'\n' for line in path.read_text().splitlines() if line.split()[1]!=str(r/'metadata')))
elif name=='sync':pass
elif name=='timeout':os.execvp(args[1],args[1:])
else:sys.exit(3)
'''


class Tests(unittest.TestCase):
    def fixture(self, flags=None, mounted=True, fs='ext4', capture=True, storage_fs='ext4', storage_options='rw,relatime', storage_mounted=True):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        r = Path(temp.name)
        for path in ('bin', 'tmp', 'proc', 'dev', 'metadata', 'sdcard/Download', 'sys/fs/pstore'):
            (r / path).mkdir(parents=True)
        (r / 'flags.json').write_text(json.dumps(flags or {}))
        (r / 'events').write_text('')
        (r / 'dev/metadata').write_text('metadata block fixture')
        storage_row = f'{r}/dev/userdata {r}/sdcard {storage_fs} {storage_options} 0 0\n' if storage_mounted else 'rootfs / rootfs rw 0 0\n'
        (r / 'proc/mounts').write_text(storage_row + (f'{r}/dev/metadata {r}/metadata {fs} rw,relatime 0 0\n' if mounted else ''))
        (r / 'proc/last_kmsg').write_text('previous Android kernel evidence\n')
        (r / 'tmp/recovery.log').write_text('OrangeFox recovery evidence\n')
        (r / 'sys/fs/pstore/console-ramoops-0').write_text('optional kernel pstore evidence\n')
        if capture:
            d = r / 'metadata/r8q-bootdiag-v5/capture.A1B2C3'
            d.mkdir(parents=True, mode=0o700)
            d.parent.chmod(0o700)
            (d / 'boot.log').write_text('Android SurfaceFlinger crash evidence\n')
            (d / 'README.txt').write_text('capture metadata')
            (d / 'COMPLETE.txt').write_text('capture=complete\n')
        for name in ('id', 'getprop', 'df', 'stat', 'mount', 'umount', 'sync', 'timeout'):
            path = r / 'bin' / name
            path.write_text(MOCK)
            path.chmod(0o755)
        script = (ROOT / 'tools/bootdiag_v5/collect-template.sh').read_text()
        # Files stand in for block nodes only in this fixture.
        script = script.replace('[ -b ', '[ -f ')
        # The recovery UI descriptor is a live host descriptor, not fixture
        # evidence. Keep it live while redirecting the procfs input paths.
        script = script.replace('/proc/self/fd/', '@@LIVE_UI_FD@@')
        paths = {'/dev/block/platform/soc/1d84000.ufshc/by-name/metadata': str(r / 'dev/metadata'),
                 '/proc/': str(r / 'proc') + '/', '/sys/': str(r / 'sys') + '/', '/metadata': str(r / 'metadata'),
                 '/sdcard': str(r / 'sdcard'), '/tmp': str(r / 'tmp')}
        script = re.sub('|'.join(re.escape(p) for p in sorted(paths, key=len, reverse=True)), lambda m: paths[m.group()], script)
        script = script.replace('@@LIVE_UI_FD@@', '/proc/self/fd/')
        (r / 'run.sh').write_text(script)
        return r

    def execute(self, r):
        return subprocess.run([SHELL, r / 'run.sh', '3', '1', 'fixture.zip'],
            env=dict(os.environ, PATH=str(r / 'bin') + ':' + os.environ['PATH'], FIXTURE_ROOT=str(r)),
            capture_output=True, text=True, timeout=30)

    def archive(self, r):
        paths = list((r / 'sdcard/Download').glob('*.tar.gz'))
        self.assertEqual(len(paths), 1)
        return paths[0]

    def test_complete_genuine_tar_gz_with_nonempty_android_capture_and_recovery(self):
        r = self.fixture()
        originals = {p: p.read_bytes() for p in (r / 'metadata').rglob('*') if p.is_file()}
        result = self.execute(r)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archive = self.archive(r)
        self.assertNotIn('PARTIAL', archive.name)
        with tarfile.open(archive, 'r:gz') as tar:
            self.assertTrue(tar.extractfile('r8q-logs-v5/recovery.log').read())
            self.assertTrue(tar.extractfile('r8q-logs-v5/r8q-bootdiag-v5/capture.A1B2C3/boot.log').read())
            self.assertIn(b'collection_state=COMPLETE', tar.extractfile('r8q-logs-v5/COLLECTOR-STATUS.txt').read())
            self.assertTrue(all(not member.issym() and not member.name.startswith('/') for member in tar.getmembers()))
        self.assertEqual(originals, {p: p.read_bytes() for p in (r / 'metadata').rglob('*') if p.is_file()})
        self.assertNotIn('mount [', (r / 'events').read_text())
        self.assertFalse(list((r / 'tmp').glob('r8q-v5-collect.*')))

    def test_missing_capture_completion_or_last_kmsg_is_partial_but_preserves_useful_evidence(self):
        for missing in ('capture', 'last_kmsg', 'completion'):
            r = self.fixture(capture=missing != 'capture')
            if missing == 'last_kmsg': (r / 'proc/last_kmsg').unlink()
            if missing == 'completion': (r / 'metadata/r8q-bootdiag-v5/capture.A1B2C3/COMPLETE.txt').unlink()
            result = self.execute(r)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            archive = self.archive(r)
            self.assertIn('-PARTIAL.tar.gz', archive.name)
            self.assertIn('PARTIAL collection', result.stdout)
            with tarfile.open(archive, 'r:gz') as tar:
                self.assertTrue(tar.extractfile('r8q-logs-v5/recovery.log').read())
                self.assertIn(b'MISSING_OR_PARTIAL', tar.extractfile('r8q-logs-v5/COLLECTOR-STATUS.txt').read())

    def test_metadata_mount_is_readonly_noload_and_only_ours_is_released(self):
        r = self.fixture(mounted=False)
        result = self.execute(r)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = (r / 'events').read_text()
        self.assertIn('ro,noload,nodev,nosuid,noexec', events)
        self.assertIn('umount [', events)
        self.assertNotIn(str(r / 'metadata'), (r / 'proc/mounts').read_text())
        self.assertIn(str(r / 'sdcard'), (r / 'proc/mounts').read_text())
        self.assertNotIn('PARTIAL', self.archive(r).name)

    def test_wrong_metadata_filesystem_is_not_read_or_remounted(self):
        r = self.fixture(fs='f2fs')
        result = self.execute(r)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('-PARTIAL.tar.gz', self.archive(r).name)
        self.assertNotIn('mount [', (r / 'events').read_text())
        with tarfile.open(self.archive(r), 'r:gz') as tar:
            self.assertFalse(any('/capture.' in member.name for member in tar.getmembers()))

    def test_wrong_device_android_mode_or_low_storage_prevents_output(self):
        for flags in ({'device': True}, {'android': True}, {'free': 32767}):
            r = self.fixture(flags=flags)
            result = self.execute(r)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list((r / 'sdcard/Download').iterdir()), [])

    def test_ram_unmounted_and_readonly_storage_cannot_claim_a_saved_archive(self):
        for state in ({'storage_fs': 'tmpfs'}, {'storage_mounted': False}, {'storage_options': 'ro,relatime'}):
            with self.subTest(state=state):
                r = self.fixture(**state)
                result = self.execute(r)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(list((r / 'sdcard/Download').iterdir()), [])
                self.assertNotIn('evidence archive saved', result.stdout)

    def test_symlinked_capture_file_is_skipped_and_original_target_is_not_copied(self):
        r = self.fixture()
        outside = r / 'private.txt'
        outside.write_text('PRIVATE unrelated data')
        capture = r / 'metadata/r8q-bootdiag-v5/capture.A1B2C3'
        (capture / 'linked.txt').symlink_to(outside)
        result = self.execute(r)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('-PARTIAL.tar.gz', self.archive(r).name)
        with tarfile.open(self.archive(r), 'r:gz') as tar:
            self.assertFalse(any(member.name.endswith('linked.txt') for member in tar.getmembers()))
            self.assertNotIn(b'PRIVATE unrelated data', b''.join(tar.extractfile(member).read() for member in tar.getmembers() if member.isfile()))
        self.assertEqual(outside.read_text(), 'PRIVATE unrelated data')

    def test_second_collection_creates_fresh_archive_without_overwrite(self):
        r = self.fixture()
        self.assertEqual(self.execute(r).returncode, 0)
        first = self.archive(r)
        original = hashlib.sha256(first.read_bytes()).hexdigest()
        self.assertEqual(self.execute(r).returncode, 0)
        archives = list((r / 'sdcard/Download').glob('*.tar.gz'))
        self.assertEqual(len(archives), 2)
        self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(), original)

    def test_large_stream_is_bounded_and_honestly_partial(self):
        r = self.fixture()
        (r / 'proc/last_kmsg').write_bytes(b'X' * (4194304 + 1024))
        result = self.execute(r)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archive = self.archive(r)
        self.assertIn('-PARTIAL.tar.gz', archive.name)
        self.assertLess(archive.stat().st_size, 33554432)
        with tarfile.open(archive, 'r:gz') as tar:
            self.assertEqual(tar.getmember('r8q-logs-v5/last_kmsg').size, 4194304)


if __name__ == '__main__':
    unittest.main()
