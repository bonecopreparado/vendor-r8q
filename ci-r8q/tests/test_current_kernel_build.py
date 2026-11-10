"""Pure guards for the current-source compile experiment; no compiler or phone."""
from pathlib import Path
import importlib.util
import struct
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('current_kernel_build', ROOT / 'tools/kernel_nflog/build_current.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def config(values):
    return ''.join(key + '=' + value + '\n' for key, value in values.items()).encode()


class Tests(unittest.TestCase):
    def fixtures(self):
        baseline = helper.baseline_bytes(ROOT / 'tools/kernel_nflog/shipped-config.gz')
        before = helper.audit.parse_config(baseline)
        after = dict(before)
        after.update(helper.REQUESTED)
        after['CONFIG_ZRAM_DEF_COMP'] = '"lz4"'
        after['CONFIG_HZ'] = '250'
        for key in helper.REMOVED_NAME_REVIEW:
            after.pop(key, None)
        return baseline, after

    def test_exact_baseline_pin_and_requested_changes_are_bounded(self):
        baseline, _ = self.fixtures()
        before = helper.audit.parse_config(baseline)
        requested = helper.audit.parse_config(helper.request_config(baseline))
        changed = {key for key in requested if before.get(key) != requested[key]}
        self.assertLessEqual(changed, helper.REQUESTED.keys())
        self.assertEqual(requested['CONFIG_COMPAT'], before['CONFIG_COMPAT'])
        self.assertEqual(requested['CONFIG_KSU'], 'y')
        self.assertEqual(requested['CONFIG_RELR'], 'y')
        self.assertEqual(requested['CONFIG_THINLTO'], 'y')
        self.assertEqual(requested['CONFIG_ZRAM_BACKEND_LZ4'], 'y')

    def test_reviewed_removed_names_pass_only_with_actual_driver(self):
        baseline, after = self.fixtures()
        result = helper.config_guards(baseline, config(after))
        self.assertTrue(result['build_config_guards_passed'], result['build_guard_failures'])
        self.assertIn('CONFIG_SENSORS_FINGERPRINT_QCOM', result['reviewed_removed_name_mappings'])
        after.pop('CONFIG_SENSORS_GW9558X')
        result = helper.config_guards(baseline, config(after))
        self.assertFalse(result['build_config_guards_passed'])
        self.assertIn('CONFIG_SENSORS_GW9558X', result['build_guard_failures'])

    def test_unsupported_lto_mode_or_hardware_loss_cannot_be_silently_accepted(self):
        baseline, after = self.fixtures()
        for key, value in [('CONFIG_COMPAT', 'n'), ('CONFIG_SECURITY_SELINUX', 'n'),
                           ('CONFIG_USB_DWC3_MSM', 'n'), ('CONFIG_NETFILTER_XT_TARGET_NFLOG', 'n'),
                           ('CONFIG_RELR', 'n'), ('CONFIG_LTO_CLANG', 'n'), ('CONFIG_THINLTO', 'n'), ('CONFIG_NOMOUNT', 'y')]:
            with self.subTest(key=key):
                modified = {**after, key: value}
                result = helper.config_guards(baseline, config(modified))
                self.assertIn(key, result['build_guard_failures'])

    def test_loss_of_susfs_or_other_unreviewed_ksu_feature_fails(self):
        baseline, after = self.fixtures()
        for key in ('CONFIG_KSU_SUSFS', 'CONFIG_KSU_SUSFS_SUS_PATH'):
            with self.subTest(key=key):
                modified = dict(after)
                modified.pop(key)
                self.assertIn(key, helper.config_guards(baseline, config(modified))['build_guard_failures'])

    def test_old_config_lz4_choice_requires_new_backend_to_survive_kconfig(self):
        baseline, after = self.fixtures()
        after['CONFIG_ZRAM_DEF_COMP'] = '"lzo-rle"'
        after['CONFIG_ZRAM_BACKEND_LZ4'] = 'n'
        result = helper.config_guards(baseline, config(after))
        self.assertIn('CONFIG_ZRAM_DEF_COMP', result['build_guard_failures'])
        self.assertIn('CONFIG_ZRAM_BACKEND_LZ4', result['build_guard_failures'])

    def image(self, offset=0, flags=10, memory_size=4096):
        result = bytearray(64)
        struct.pack_into('<QQQ', result, 8, offset, memory_size, flags)
        result[56:60] = b'ARM\x64'
        return bytes(result)

    def test_zero_load_offset_is_reported_without_claiming_old_dtb_compatibility(self):
        result = helper.image_header(self.image(), 1024)
        self.assertEqual(result['text_offset'], 0)
        self.assertEqual(result['shipped_old_text_offset'], 0x80000)
        self.assertFalse(result['old_bootloader_dtb_compatibility_confirmed'])

    def test_image_magic_offset_endian_page_and_bounds_are_validated(self):
        cases = [(self.image(offset=0x80000), 1024), (self.image(flags=11), 1024),
                 (self.image(flags=8), 1024), (self.image(memory_size=512), 1024),
                 (self.image()[:60], 1024)]
        for data, size in cases:
            with self.subTest(data=data.hex(), size=size), self.assertRaises(ValueError):
                helper.image_header(data, size)

    def test_nflog_names_in_undefined_references_do_not_pass(self):
        defined = '\n'.join('ffff0000 T ' + name for name in helper.REQUIRED_SYMBOLS)
        self.assertEqual(set(helper.defined_symbols(defined)), helper.REQUIRED_SYMBOLS)
        with self.assertRaises(ValueError):
            helper.defined_symbols('\n'.join('                 U ' + name for name in helper.REQUIRED_SYMBOLS))
        with self.assertRaises(ValueError):
            helper.defined_symbols(defined.replace(' T nflog_tg_init', ' U nflog_tg_init'))


if __name__ == '__main__':
    unittest.main()
