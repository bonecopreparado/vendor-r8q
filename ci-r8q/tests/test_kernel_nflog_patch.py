"""Host-only NFLOG overlay checks; no kernel build, mounts or phone access."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / 'tools/kernel_nflog'
spec = importlib.util.spec_from_file_location('kernel_nflog_prepare', AREA / 'prepare.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
CONFIG = b'''# Linux/arm64 kernel config fixture
CONFIG_LOCALVERSION="-not:A.06"
# CONFIG_MODULES is not set
# CONFIG_DEBUG_KERNEL is not set
CONFIG_NETFILTER=y
CONFIG_NETFILTER_XTABLES=y
CONFIG_NETFILTER_NETLINK=y
# CONFIG_NETFILTER_NETLINK_LOG is not set
# CONFIG_NETFILTER_XT_TARGET_NFLOG is not set
# CONFIG_FTRACE is not set
CONFIG_SECURITY_SELINUX=y
CONFIG_ESOC_MDM_4x=y
'''


class Tests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / 'source'
        shutil.copytree(AREA / 'upstream', source)
        return root, source

    def overlay(self, source, config, destination, expected=None):
        # The CLI has no config-pin bypass. Tiny fixtures replace its constant
        # explicitly in tests; real builds must use the audited shipped hash.
        expected = expected or helper.sha256(config)
        with patch.dict(helper.PINS, {'shipped_config_sha256': helper.sha256(CONFIG)}):
            return helper.create_overlay(source, config, destination, expected, check_git=False)

    def test_upstream_gpl_fixtures_match_all_original_hashes(self):
        for path, pin in helper.PINS['files'].items():
            data = (AREA / 'upstream' / path).read_bytes()
            self.assertEqual(len(data), pin['bytes'])
            self.assertEqual(helper.sha256(data), pin['sha256'])
            self.assertIn(b'SPDX-License-Identifier: GPL-2.0', data.splitlines()[0])

    def test_overlay_preserves_checkout_and_changes_only_two_missing_nflog_config_symbols(self):
        root, source = self.fixture()
        before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
        report = self.overlay(source, CONFIG, root / 'overlay')
        self.assertEqual(report['config_changes'], {
            'CONFIG_NETFILTER_NETLINK_LOG': {'before': 'n', 'after': 'y'},
            'CONFIG_NETFILTER_XT_TARGET_NFLOG': {'before': 'n', 'after': 'y'},
        })
        self.assertEqual(before, {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()})
        self.assertEqual(set(report['patched_files']), set(helper.PINS['files']))
        self.assertEqual(helper.parse_config((root / 'overlay/kernel.config').read_bytes())['CONFIG_ESOC_MDM_4x'], 'y')
        self.assertFalse(report['kernel_images_written'])
        self.assertFalse(any(p.suffix in ('.img', '.ko') or p.name == 'Image' for p in (root / 'overlay').rglob('*')))

    def test_config_pin_drift_and_source_drift_abort_before_output_creation(self):
        root, source = self.fixture()
        with self.assertRaisesRegex(ValueError, 'config hash'):
            self.overlay(source, CONFIG + b'# modified\n', root / 'output')
        self.assertFalse((root / 'output').exists())
        p = source / 'net/netfilter/Makefile'
        p.write_bytes(p.read_bytes() + b'# drift\n')
        with self.assertRaisesRegex(ValueError, 'Source hash'):
            self.overlay(source, CONFIG, root / 'output')
        self.assertFalse((root / 'output').exists())

    def test_source_symlink_and_existing_or_nested_output_are_refused(self):
        root, source = self.fixture()
        path = source / 'net/netfilter/Makefile'
        outside = root / 'outside'; outside.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'regular source'):
            self.overlay(source, CONFIG, root / 'output')
        root, source = self.fixture()
        for destination in (source / 'new-output', source, source.parent):
            with self.assertRaises(ValueError):
                self.overlay(source, CONFIG, destination)

    def test_duplicate_config_unexpected_debug_modules_and_unrelated_drift_are_refused(self):
        for bad in (CONFIG + b'CONFIG_NETFILTER=y\n',
                    CONFIG.replace(b'# CONFIG_DEBUG_KERNEL is not set', b'CONFIG_DEBUG_KERNEL=y'),
                    CONFIG.replace(b'# CONFIG_MODULES is not set', b'CONFIG_MODULES=y')):
            with self.assertRaises(ValueError):
                helper.prepare_config(bad)
        good = helper.prepare_config(CONFIG)
        with self.assertRaisesRegex(ValueError, 'Unreviewed config changes'):
            helper.verify_config_delta(CONFIG, good.replace(b'# CONFIG_FTRACE is not set', b'CONFIG_FTRACE=y'))
        with self.assertRaisesRegex(ValueError, 'built in'):
            helper.verify_config_delta(CONFIG, good.replace(b'CONFIG_NETFILTER_NETLINK_LOG=y', b'CONFIG_NETFILTER_NETLINK_LOG=m'))

    def test_exact_commit_and_clean_source_are_required_by_cli_checkout_guard(self):
        with patch.object(helper.subprocess, 'check_output', return_value='wrong\n'):
            with self.assertRaisesRegex(ValueError, 'exact reviewed commit'):
                helper.check_checkout(Path('/fixture'))

    def test_shipped_kernel_su_and_susfs_options_cannot_be_silently_dropped(self):
        baseline = CONFIG + b'CONFIG_KSU=y\nCONFIG_KSU_SUSFS=y\n'
        revised = helper.prepare_config(baseline)
        self.assertIn(b'CONFIG_KSU=y\n', revised)
        self.assertIn(b'CONFIG_KSU_SUSFS=y\n', revised)
        missing_external_config = revised.replace(b'CONFIG_KSU=y\n', b'').replace(b'CONFIG_KSU_SUSFS=y\n', b'')
        with self.assertRaisesRegex(ValueError, 'Unreviewed config changes'):
            helper.verify_config_delta(baseline, missing_external_config)
        with patch.object(helper.subprocess, 'check_output', side_effect=[helper.PINS['commit'] + '\n', 'fs/exec.c\n']):
            with self.assertRaisesRegex(ValueError, 'tracked source changes'):
                helper.check_checkout(Path('/fixture'))

    @unittest.skipUnless(shutil.which('make'), 'GNU Make needed for actual Kbuild variable evaluation')
    def test_kbuild_evaluation_includes_backend_and_target_without_enabling_any_debug_option(self):
        original = (AREA / 'upstream/net/netfilter/Makefile').read_bytes()
        revised = helper.patch_file('net/netfilter/Makefile', original)
        def evaluate(data, enabled):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'Makefile'
                path.write_bytes(data + b"\n.PHONY: probe\nprobe:\n\t@printf '%s\\n' 'CORE=$(netfilter-objs)' 'BUILTIN=$(obj-y)'\n")
                return subprocess.check_output(['make', '-rR', '--no-print-directory', '-f', str(path), 'probe',
                    'CONFIG_NETFILTER=y', 'CONFIG_NETFILTER_NETLINK=y',
                    'CONFIG_NETFILTER_NETLINK_LOG=' + enabled, 'CONFIG_NETFILTER_XT_TARGET_NFLOG=' + enabled], text=True)
        broken, repaired = evaluate(original, 'y'), evaluate(revised, 'y')
        for name in ('nf_log.o', 'nfnetlink_log.o', 'xt_NFLOG.o'):
            self.assertNotIn(name, broken)
            self.assertIn(name, repaired)
            self.assertNotIn(name, evaluate(revised, 'n'))
        self.assertNotIn('xt_LOG.o', repaired)
        self.assertNotIn('nfnetlink_osf.o', repaired)

    @unittest.skipUnless(shutil.which('cpp'), 'Host C preprocessor needed; no compilation occurs')
    def test_preprocessor_selects_real_logger_and_init_paths_when_debug_is_off(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('linux/netfilter.h', 'linux/netfilter/nf_log.h', 'linux/list.h', 'linux/skbuff.h', 'linux/netdevice.h'):
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('/* fixture header */\n')
            def preprocess(path, enabled):
                body = helper.patch_file(path, (AREA / 'upstream' / path).read_bytes()).decode()
                unit = root / 'probe.c'
                unit.write_text('#define IS_ENABLED(option) (option)\n#define CONFIG_NETFILTER_NETLINK_LOG ' + enabled + '\n' + body)
                return subprocess.check_output(['cpp', '-P', '-I', str(root), str(unit)], text=True)
            logger = preprocess('include/net/netfilter/nf_log.h', '1')
            init = preprocess('net/netfilter/nf_internals.h', '1')
            self.assertNotIn('static inline void nf_log_packet', logger)
            self.assertRegex(logger, r'void nf_log_trace\([^;{}]*\);')
            self.assertNotIn('static inline int __init netfilter_log_init', init)
            self.assertIn('int __init netfilter_log_init(void);', init)
            self.assertIn('static inline void nf_log_packet', preprocess('include/net/netfilter/nf_log.h', '0'))
            self.assertIn('static inline int __init netfilter_log_init', preprocess('net/netfilter/nf_internals.h', '0'))

    def test_linked_symbol_verifier_rejects_config_only_or_undefined_stubs(self):
        good = '\n'.join('0000000000001000 T ' + name for name in helper.REQUIRED_SYMBOLS)
        self.assertEqual(helper.verify_symbols(good), list(helper.REQUIRED_SYMBOLS))
        for name in ('nfnetlink_log_init', 'nflog_tg_init', 'nf_log_packet'):
            with self.subTest(missing=name):
                bad = good.replace('0000000000001000 T ' + name, '                 U ' + name)
                with self.assertRaisesRegex(ValueError, 'Missing linked'):
                    helper.verify_symbols(bad)


if __name__ == '__main__':
    unittest.main()
