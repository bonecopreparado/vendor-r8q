"""Verified cache of the exact compiler checkout, never kernel build outputs.

Integration::

    prepared = prepare_compiler(clang, evidence, env, verify_toolchain,
                                cache=compiler_cache, work=work, output=evidence)
    report['toolchain'] = prepared['toolchain']
    report['compiler_cache'] = prepared['cache']

The identity callback is build_current.verify_toolchain. Cache validation uses
a private environment; only validation of the fresh copy updates the caller's
PATH. A build therefore reads its private compiler copy, never the cache.
"""
from pathlib import Path
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_current as audit

CLANG_SHA256 = '19823dc3473e9fc514d5c37f11afc1e7d76f9d519257448445a929e46086ffd9'
MARKER = 'r8q-compiler-cache.json'
SCHEMA = 1


def cache_key():
    return 'r8q-clang-v1-linux-x64-' + audit.CLANG_COMMIT + '-' + audit.CLANG_BLOB


def _related(first, second):
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def _layout(destination, cache, work, output):
    destination, work, output = (Path(path).absolute() for path in (destination, work, output))
    if destination.exists() or destination.is_symlink():
        raise ValueError('Compiler destination already exists; previous files are preserved')
    if not work.is_dir() or work.is_symlink() or not output.is_dir() or output.is_symlink():
        raise ValueError('Expected existing regular work/output directories')
    work, output = work.resolve(), output.resolve()
    destination = destination.resolve()
    if not destination.is_relative_to(work) or destination == work or _related(destination, output):
        raise ValueError('Compiler destination must be inside fresh work and separate from output')
    if cache is not None:
        cache = Path(cache).absolute()
        if any(path.is_symlink() for path in (cache, *cache.parents)):
            raise ValueError('Compiler cache path must not traverse symbolic links')
        cache = cache.resolve()
        if _related(cache, work) or _related(cache, output):
            raise ValueError('Compiler cache must be separate from work/output')
    return destination, cache, work, output


def _readonly_git_env(env):
    private = dict(env, GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0', GIT_NO_LAZY_FETCH='1')
    for key in ('GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE',
                'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES'):
        private.pop(key, None)
    return private


def _git(root, env, *args):
    return audit.output(['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null',
                         '-C', root, *args], env)


def _links(root):
    selected = root / audit.CLANG_DIRECTORY
    if selected.is_symlink() or not selected.is_dir():
        raise ValueError('Expected regular pinned sparse compiler directory')
    selected = selected.resolve()
    for path in selected.rglob('*'):
        if path.is_symlink():
            target = Path(os.readlink(path))
            if target.is_absolute():
                raise ValueError('Compiler cache contains an absolute symbolic link')
            try:
                resolved = path.resolve(strict=True)
            except (FileNotFoundError, RuntimeError) as error:
                raise ValueError('Compiler cache contains an invalid symbolic link') from error
            if not resolved.is_relative_to(selected):
                raise ValueError('Compiler symbolic link escapes the copied compiler directory')


def verify_checkout(root, env):
    """Read-only Git/layout checks, before executing any cached binary."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or (root / '.git').is_symlink() or not (root / '.git').is_dir():
        raise ValueError('Expected independent regular compiler Git checkout')
    private = _readonly_git_env(env)
    if Path(_git(root, private, 'rev-parse', '--show-toplevel')).resolve() != root.resolve():
        raise ValueError('Compiler cache is not its own Git work tree')
    head = _git(root, private, 'rev-parse', 'HEAD')
    origin = _git(root, private, 'remote', 'get-url', 'origin')
    if head != audit.CLANG_COMMIT or origin.rstrip('/') != audit.CLANG_REPO.rstrip('/'):
        raise ValueError('Compiler cache Git HEAD/origin differs from exact pins')
    if _git(root, private, 'config', '--bool', 'core.sparseCheckout') != 'true':
        raise ValueError('Compiler cache is not a sparse checkout')
    if _git(root, private, 'config', '--bool', 'core.sparseCheckoutCone') != 'true':
        raise ValueError('Compiler cache does not use reviewed cone sparse checkout')
    if _git(root, private, 'sparse-checkout', 'list').splitlines() != [audit.CLANG_DIRECTORY]:
        raise ValueError('Compiler cache sparse directory differs')
    # The selected directory must contain materialized, normally tracked files,
    # not assume-unchanged/skip-worktree entries that could conceal modifications.
    entries = _git(root, private, 'ls-files', '-v', '--', audit.CLANG_DIRECTORY).splitlines()
    if not entries or any(not entry.startswith('H ') for entry in entries):
        raise ValueError('Compiler cache has hidden/unmaterialized selected files')
    dirty = _git(root, private, 'status', '--porcelain=v1', '--untracked-files=all', '--ignore-submodules=none')
    if dirty:
        raise ValueError('Compiler cache Git work tree/index is dirty')
    _links(root)
    return {'repository': origin, 'commit': head, 'tree': _git(root, private, 'rev-parse', 'HEAD^{tree}'),
            'sparse_directory': audit.CLANG_DIRECTORY, 'git_clean': True}


def _identity(root, env, verify_identity):
    # The callback verifies the Git blob, byte count, real banner, linker and
    # options. Require the known SHA256 here as well; metadata alone cannot pass.
    identity = verify_identity(root, env)
    if identity.get('clang_sha256') != CLANG_SHA256 or identity.get('clang_git_blob') != audit.CLANG_BLOB:
        raise ValueError('Compiler identity callback did not confirm pinned SHA256/Git blob')
    if identity.get('commit') != audit.CLANG_COMMIT or identity.get('repository', '').rstrip('/') != audit.CLANG_REPO.rstrip('/'):
        raise ValueError('Compiler identity callback returned different source pins')
    return identity


def _marker_value():
    return {'schema': SCHEMA, 'cache_key': cache_key(), 'repository': audit.CLANG_REPO,
            'commit': audit.CLANG_COMMIT, 'sparse_directory': audit.CLANG_DIRECTORY,
            'clang_git_blob': audit.CLANG_BLOB, 'clang_sha256': CLANG_SHA256}


def _check_marker(root):
    marker = root / '.git' / MARKER
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 4096:
        raise ValueError('Compiler cache verification marker is absent or invalid')
    try:
        value = json.loads(marker.read_text())
    except (ValueError, UnicodeError) as error:
        raise ValueError('Malformed compiler cache verification marker') from error
    if value != _marker_value():
        raise ValueError('Compiler cache marker differs from current exact pins')


def prepare_compiler(destination, evidence, env, verify_identity, *, cache=None, work, output):
    """Populate/verify a pinned cache, then copy compiler files into fresh work.

    `evidence` receives fetch logs on a cache miss. `verify_identity(path, env)`
    must perform actual compiler verification and may update that env's PATH.
    Existing cache/destination files are never deleted or repaired in place.
    Cache hits are read-only. No hard links are used for compiler binaries.
    """
    destination, cache, work, output = _layout(destination, cache, work, output)
    evidence = Path(evidence).resolve()
    if not evidence.is_relative_to(output) or not evidence.is_dir():
        raise ValueError('Compiler evidence directory must be inside the output directory')
    if cache is None:
        audit.checkout(audit.CLANG_REPO, audit.CLANG_COMMIT, destination, evidence,
                       'clang', env, sparse=audit.CLANG_DIRECTORY)
        git_identity = verify_checkout(destination, env)
        identity = _identity(destination, env, verify_identity)
        return {'toolchain': identity, 'cache': {'enabled': False, 'hit': False, **git_identity}}

    hit = cache.exists()
    if hit:
        _check_marker(cache)
        git_identity = verify_checkout(cache, env)
        _identity(cache, _readonly_git_env(env), verify_identity)
    else:
        cache.parent.mkdir(parents=True, exist_ok=True)
        # A failed fetch/verification never becomes a restorable cache directory.
        with tempfile.TemporaryDirectory(prefix='.r8q-clang-cache-', dir=cache.parent) as temporary:
            staging = Path(temporary) / 'checkout'
            audit.checkout(audit.CLANG_REPO, audit.CLANG_COMMIT, staging, evidence,
                           'clang-cache', env, sparse=audit.CLANG_DIRECTORY)
            git_identity = verify_checkout(staging, env)
            _identity(staging, _readonly_git_env(env), verify_identity)
            marker = staging / '.git' / MARKER
            marker.write_text(json.dumps(_marker_value(), indent=2) + '\n')
            if cache.exists() or cache.is_symlink():
                raise ValueError('Compiler cache appeared concurrently; preserving both checkouts')
            staging.rename(cache)

    # Copy only the selected directory, not the large Git object store. Git
    # hash-object works outside a repository, so verify_identity still verifies
    # real bytes. Relative internal symlinks stay inside this private copy.
    destination.mkdir(parents=True)
    shutil.copytree(cache / audit.CLANG_DIRECTORY, destination / audit.CLANG_DIRECTORY,
                    symlinks=True, copy_function=shutil.copy2)
    _links(destination)
    identity = _identity(destination, env, verify_identity)
    return {'toolchain': identity,
            'cache': {'enabled': True, 'hit': hit, 'key': cache_key(), 'path': str(cache),
                      'copied_git_object_store': False, 'binary_copy_uses_hardlinks': False,
                      'cache_read_only_during_build': True, 'verified_clang_sha256': CLANG_SHA256,
                      **git_identity}}
