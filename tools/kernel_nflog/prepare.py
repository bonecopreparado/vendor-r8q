"""Prepare an offline, hash-pinned NFLOG source overlay; never build or flash.

The CLI requires a clean checkout of the exact Android kernel source commit
and a separately pinned config extracted from its shipped boot kernel.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess

HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE / 'source-pins.json').read_text())
BUILTINS = tuple(PINS['required_builtin_config'])
ALLOW_CONFIG_CHANGES = frozenset(BUILTINS)
REQUIRED_SYMBOLS = (
    'nf_log_packet', 'netfilter_log_init', 'nfnetlink_subsys_register',
    'nfnetlink_log_init', 'nfulnl_recv_config', 'nflog_tg_init', 'nflog_tg',
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Expected exactly one reviewed patch context')
    return text.replace(old, new, 1)


def patch_file(path, original):
    pin = PINS['files'][path]
    if len(original) != pin['bytes'] or sha256(original) != pin['sha256']:
        raise ValueError('Source hash differs: ' + path)
    text = original.decode('utf-8')
    if path == 'net/netfilter/Makefile':
        text = replace_once(text,
            'ifdef CONFIG_DEBUG_KERNEL\nnetfilter-objs += nf_log.o\nendif',
            'ifneq ($(filter y m,$(CONFIG_DEBUG_KERNEL) $(CONFIG_NETFILTER_NETLINK_LOG)),)\n'
            'netfilter-objs += nf_log.o\nendif')
        text = replace_once(text,
            'ifdef CONFIG_DEBUG_KERNEL\nobj-$(CONFIG_NETFILTER_NETLINK_LOG) += nfnetlink_log.o\n'
            'obj-$(CONFIG_NETFILTER_NETLINK_OSF) += nfnetlink_osf.o\nendif',
            'obj-$(CONFIG_NETFILTER_NETLINK_LOG) += nfnetlink_log.o\n'
            'ifdef CONFIG_DEBUG_KERNEL\nobj-$(CONFIG_NETFILTER_NETLINK_OSF) += nfnetlink_osf.o\nendif')
        text = replace_once(text,
            'ifdef CONFIG_KERNEL_DEBUG\nobj-$(CONFIG_NETFILTER_XT_TARGET_LOG) += xt_LOG.o\n'
            'obj-$(CONFIG_NETFILTER_XT_TARGET_NFLOG) += xt_NFLOG.o\nendif',
            'ifdef CONFIG_KERNEL_DEBUG\nobj-$(CONFIG_NETFILTER_XT_TARGET_LOG) += xt_LOG.o\nendif\n'
            'obj-$(CONFIG_NETFILTER_XT_TARGET_NFLOG) += xt_NFLOG.o')
    elif path in ('include/net/netfilter/nf_log.h', 'net/netfilter/nf_internals.h'):
        text = replace_once(text, '#ifdef CONFIG_DEBUG_KERNEL',
            '#if defined(CONFIG_DEBUG_KERNEL) || IS_ENABLED(CONFIG_NETFILTER_NETLINK_LOG)')
        if path.endswith('/nf_log.h'):
            # The previously inactive real-prototype branch has a source typo.
            text = replace_once(text, 'const char *fmt, ...)\n\n#else',
                                'const char *fmt, ...);\n\n#else')
    else:
        raise ValueError('Unreviewed patch destination')
    return text.encode('utf-8')


def parse_config(data):
    if len(data) > 1024 * 1024 or b'\0' in data:
        raise ValueError('Unexpected config bounds/content')
    values = {}
    for line in data.decode('utf-8').splitlines():
        match = re.fullmatch(r'(CONFIG_[A-Za-z0-9_]+)=(.+)', line)
        disabled = re.fullmatch(r'# (CONFIG_[A-Za-z0-9_]+) is not set', line)
        if match:
            key, value = match.groups()
        elif disabled:
            key, value = disabled.group(1), 'n'
        elif line.startswith('CONFIG_'):
            raise ValueError('Malformed config assignment')
        else:
            continue
        if key in values:
            raise ValueError('Duplicate config symbol: ' + key)
        values[key] = value
    return values


def require_baseline(values):
    expected = {'CONFIG_MODULES': 'n', 'CONFIG_DEBUG_KERNEL': 'n',
                'CONFIG_NETFILTER': 'y', 'CONFIG_NETFILTER_XTABLES': 'y'}
    for key, value in expected.items():
        if values.get(key) != value:
            raise ValueError('Unexpected shipped config: ' + key)


def prepare_config(original):
    values = parse_config(original)
    require_baseline(values)
    output = []
    replaced = set()
    for line in original.decode('utf-8').splitlines():
        key = next((k for k in BUILTINS if line.startswith(k + '=') or line == '# ' + k + ' is not set'), None)
        if key:
            output.append(key + '=y')
            replaced.add(key)
        else:
            output.append(line)
    output.extend(k + '=y' for k in BUILTINS if k not in replaced)
    result = ('\n'.join(output) + '\n').encode()
    verify_config_delta(original, result)
    return result


def verify_config_delta(original, candidate):
    before, after = parse_config(original), parse_config(candidate)
    require_baseline(before)
    require_baseline(after)
    changes = {k: {'before': before.get(k), 'after': after.get(k)}
               for k in sorted(before.keys() | after.keys()) if before.get(k) != after.get(k)}
    unauthorized = changes.keys() - ALLOW_CONFIG_CHANGES
    if unauthorized:
        raise ValueError('Unreviewed config changes: ' + ', '.join(sorted(unauthorized)))
    if any(after.get(key) != 'y' for key in BUILTINS):
        raise ValueError('All reviewed NFLOG components must be built in')
    return changes


def verify_symbols(nm_text):
    defined = set()
    for line in nm_text.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[-2] in ('T', 't', 'D', 'd', 'B', 'b', 'R', 'r'):
            defined.add(fields[-1])
    missing = [name for name in REQUIRED_SYMBOLS
               if not any(symbol == name or symbol.startswith(name + '.') for symbol in defined)]
    if missing:
        raise ValueError('Missing linked NFLOG/core symbols: ' + ', '.join(missing))
    return list(REQUIRED_SYMBOLS)


def check_checkout(source):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True, env=env).strip()
    if head != PINS['commit']:
        raise ValueError('Kernel checkout is not the exact reviewed commit')
    changed = subprocess.check_output(['git', '-C', str(source), 'diff', '--name-only', 'HEAD', '--'], text=True, env=env)
    if changed.strip():
        raise ValueError('Kernel checkout has tracked source changes')


def create_overlay(source, original_config, output, expected_config_sha256, *, check_git=True):
    source, output = Path(source).resolve(), Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Output already exists; preserving previous work')
    destination = output.resolve()
    if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Overlay output must be separate from source checkout')
    if (not re.fullmatch('[0-9a-f]{64}', expected_config_sha256)
            or expected_config_sha256 != PINS['shipped_config_sha256']
            or sha256(original_config) != expected_config_sha256):
        raise ValueError('Shipped config hash differs')
    if check_git:
        check_checkout(source)
    generated = prepare_config(original_config)
    patches = {}
    for path in PINS['files']:
        selected = source / path
        current = source
        links = False
        for component in Path(path).parts:
            current /= component
            links |= current.is_symlink()
        if not selected.is_file() or links:
            raise ValueError('Expected regular source path: ' + path)
        if not selected.resolve().is_relative_to(source):
            raise ValueError('Source path escapes reviewed checkout')
        patches[path] = patch_file(path, selected.read_bytes())
    report = {
        'status': 'OFFLINE_NFLOG_SOURCE_OVERLAY_NOT_COMPILED_OR_BOOT_TESTED',
        'build_ready': not bool(PINS.get('build_blockers')),
        'build_blockers': PINS.get('build_blockers', []),
        'source_commit': PINS['commit'], 'source_repository': PINS['repository'],
        'source_checkout_modified': False, 'kernel_images_written': False,
        'config_before_sha256': sha256(original_config), 'config_after_sha256': sha256(generated),
        'config_changes': verify_config_delta(original_config, generated),
        'patched_files': {p: {'before_sha256': PINS['files'][p]['sha256'], 'after_sha256': sha256(b)}
                          for p, b in patches.items()},
        'required_linked_symbols': list(REQUIRED_SYMBOLS),
    }
    destination.mkdir(parents=True)
    for path, data in patches.items():
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (destination / 'kernel.config').write_bytes(generated)
    (destination / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--source', type=Path, required=True)
    prep.add_argument('--shipped-config', type=Path, required=True)
    prep.add_argument('--shipped-config-sha256', required=True)
    prep.add_argument('--output', type=Path, required=True)
    check = commands.add_parser('verify-config')
    check.add_argument('--shipped-config', type=Path, required=True)
    check.add_argument('--generated-config', type=Path, required=True)
    symbols = commands.add_parser('verify-symbols')
    symbols.add_argument('--nm', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = create_overlay(args.source, args.shipped_config.read_bytes(), args.output,
                                args.shipped_config_sha256)
    elif args.command == 'verify-config':
        result = verify_config_delta(args.shipped_config.read_bytes(), args.generated_config.read_bytes())
    else:
        result = verify_symbols(args.nm.read_text())
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
