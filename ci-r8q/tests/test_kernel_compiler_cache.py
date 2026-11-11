"""Local Git fixtures for compiler cache guards; no downloads or compiler runs."""
from pathlib import Path
import hashlib
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('kernel_compiler_cache', ROOT / 'tools/kernel_nflog/compiler_cache.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class Tests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        seed = root / 'seed'
        seed.mkdir()
        selected = seed / helper.audit.CLANG_DIRECTORY
        (selected / 'bin').mkdir(parents=True)
        binary = selected / 'bin/clang-18'
        binary.write_bytes(b'test compiler bytes\n')
        binary.chmod(0o755)
        (selected / 'bin/clang').symlink_to('clang-18')
        (seed / 'README').write_text('local fixture\n')
        self.git(seed, 'init', '-q')
        self.git(seed, 'config', 'user.name', 'Fixture')
        self.git(seed, 'config', 'user.email', 'fixture@example.invalid')
        self.git(seed, 'remote', 'add', 'origin', helper.audit.CLANG_REPO)
        self.git(seed, 'add', '.')
        self.git(seed, 'commit', '-qm', 'fixture')
        self.git(seed, 'sparse-checkout', 'init', '--cone')
        self.git(seed, 'sparse-checkout', 'set', helper.audit.CLANG_DIRECTORY)
        commit = self.git(seed, 'rev-parse', 'HEAD')
        blob = self.git(seed, 'hash-object', binary)
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        self.enterContext(patch.object(helper.audit, 'CLANG_COMMIT', commit))
        self.enterContext(patch.object(helper.audit, 'CLANG_BLOB', blob))
        self.enterContext(patch.object(helper, 'CLANG_SHA256', digest))
        work, output = root / 'work', root / 'output'
        work.mkdir()
        output.mkdir()
        return root, seed, work, output

    def git(self, path, *args):
        return subprocess.check_output(['git', '-C', str(path), *map(str, args)], text=True).strip()

    def identity(self, path, env):
        binary = path / helper.audit.CLANG_DIRECTORY / 'bin/clang-18'
        env['PATH'] = str(binary.parent) + os.pathsep + env.get('PATH', '')
        self.assertEqual(self.git(path, 'hash-object', binary), helper.audit.CLANG_BLOB)
        return {'repository': helper.audit.CLANG_REPO, 'commit': helper.audit.CLANG_COMMIT,
                'clang_git_blob': helper.audit.CLANG_BLOB,
                'clang_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}

    def checkout(self, seed):
        def create(repo, commit, destination, logs, name, env, sparse=None):
            self.assertEqual(repo, helper.audit.CLANG_REPO)
            self.assertEqual(commit, helper.audit.CLANG_COMMIT)
            self.assertEqual(sparse, helper.audit.CLANG_DIRECTORY)
            shutil.copytree(seed, destination, symlinks=True)
        return create

    def prepare(self, cache, destination, output, work, identity=None):
        env = dict(os.environ)
        result = helper.prepare_compiler(destination, output, env, identity or self.identity,
                                         cache=cache, work=work, output=output)
        return result, env

    def test_miss_then_hit_verify_identity_and_copy_without_git_or_hardlinks(self):
        root, seed, work, output = self.fixture()
        cache = root / 'cache/compiler'
        with patch.object(helper.audit, 'checkout', side_effect=self.checkout(seed)) as checkout:
            result, env = self.prepare(cache, work / 'clang', output, work)
            self.assertEqual(checkout.call_count, 1)
        self.assertFalse(result['cache']['hit'])
        self.assertTrue((cache / '.git' / helper.MARKER).is_file())
        self.assertFalse((work / 'clang/.git').exists())
        compiler = Path(helper.audit.CLANG_DIRECTORY) / 'bin/clang-18'
        copied, original = work / 'clang' / compiler, cache / compiler
        self.assertNotEqual(copied.stat().st_ino, original.stat().st_ino)
        self.assertTrue((work / 'clang' / compiler.parent / 'clang').is_symlink())
        self.assertNotIn(str(cache), env['PATH'])
        before = (cache / '.git' / helper.MARKER).read_bytes()
        with patch.object(helper.audit, 'checkout') as checkout:
            hit, _ = self.prepare(cache, work / 'clang2', output, work)
            checkout.assert_not_called()
        self.assertTrue(hit['cache']['hit'])
        self.assertEqual(before, (cache / '.git' / helper.MARKER).read_bytes())

    def test_existing_work_destination_is_preserved(self):
        root, seed, work, output = self.fixture()
        destination = work / 'clang'
        destination.mkdir()
        (destination / 'keep').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.prepare(root / 'cache', destination, output, work)
        self.assertEqual((destination / 'keep').read_text(), 'keep')

    def test_cache_must_be_separate_and_not_a_symlink(self):
        root, seed, work, output = self.fixture()
        (root / 'linked').symlink_to(seed, target_is_directory=True)
        for cache in (work / 'cache', output / 'cache', root, root / 'linked'):
            with self.subTest(cache=cache), self.assertRaises(ValueError):
                self.prepare(cache, work / 'clang', output, work)

    def test_changed_origin_head_sparse_and_dirty_tree_fail_before_binary_callback(self):
        root, seed, work, output = self.fixture()
        changes = (
            lambda selected: self.git(selected, 'remote', 'set-url', 'origin', 'https://example.invalid/other'),
            # sparse-checkout init enables worktreeConfig in current Git.
            # Mutate the effective setting, not an overridden shared value.
            lambda selected: self.git(selected, 'sparse-checkout', 'disable'),
            lambda selected: self.git(selected, 'sparse-checkout', 'set', 'other'),
            lambda selected: (selected / 'README').write_text('dirty'),
            lambda selected: (selected / 'unexpected').write_text('untracked'),
            lambda selected: self.git(selected, 'update-index', '--assume-unchanged', helper.audit.CLANG_DIRECTORY + '/bin/clang-18'),
        )
        for i, change in enumerate(changes):
            selected = root / ('bad-' + str(i))
            shutil.copytree(seed, selected, symlinks=True)
            change(selected)
            with self.subTest(change=i), self.assertRaises((ValueError, subprocess.CalledProcessError)):
                helper.verify_checkout(selected, os.environ)

    def test_escape_and_absolute_symlinks_are_rejected(self):
        root, seed, work, output = self.fixture()
        selected = seed / helper.audit.CLANG_DIRECTORY
        for target in ('../../README', str(selected / 'bin/clang-18')):
            link = selected / 'bin/escape'
            link.symlink_to(target)
            with self.subTest(target=target), self.assertRaises(ValueError):
                helper._links(seed)
            link.unlink()

    def test_failed_real_identity_never_publishes_cache_marker_or_directory(self):
        root, seed, work, output = self.fixture()
        cache = root / 'cache/compiler'
        def invalid(path, env):
            result = self.identity(path, env)
            result['clang_sha256'] = '0' * 64
            return result
        with patch.object(helper.audit, 'checkout', side_effect=self.checkout(seed)):
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                self.prepare(cache, work / 'clang', output, work, identity=invalid)
        self.assertFalse(cache.exists())
        self.assertFalse((work / 'clang').exists())

    def test_cache_marker_is_checked_but_never_replaces_reverification(self):
        root, seed, work, output = self.fixture()
        cache = root / 'cache/compiler'
        with patch.object(helper.audit, 'checkout', side_effect=self.checkout(seed)):
            self.prepare(cache, work / 'clang', output, work)
        (cache / helper.audit.CLANG_DIRECTORY / 'bin/clang-18').write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            self.prepare(cache, work / 'clang2', output, work)
        self.assertFalse((work / 'clang2').exists())

    def test_no_cache_path_uses_exact_checkout_and_verification(self):
        root, seed, work, output = self.fixture()
        with patch.object(helper.audit, 'checkout', side_effect=self.checkout(seed)):
            result, env = self.prepare(None, work / 'clang', output, work)
        self.assertFalse(result['cache']['enabled'])
        self.assertTrue((work / 'clang/.git').is_dir())


if __name__ == '__main__':
    unittest.main()
