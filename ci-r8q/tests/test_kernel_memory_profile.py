"""Negative checks for the isolated MEMCG/PSI/v1-freezer config experiment."""
from pathlib import Path
import importlib.util
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('memory_kernel_build', ROOT/'tools/kernel_nflog/build_current.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def config(values):
    return ''.join(k+'='+v+'\n' for k,v in values.items()).encode()


class Tests(unittest.TestCase):
    def fixture(self):
        baseline = helper.baseline_bytes(ROOT/'tools/kernel_nflog/shipped-config.gz')
        values = helper.audit.parse_config(baseline)
        values.update(helper.REQUESTED)
        values.update(CONFIG_ZRAM_DEF_COMP='"lz4"', CONFIG_HZ='250')
        for key in helper.REMOVED_NAME_REVIEW: values.pop(key, None)
        return baseline, values

    def test_reviewed_three_transitions_pass_and_remain_explicit(self):
        baseline, values = self.fixture()
        result = helper.config_guards(baseline, config(values))
        self.assertTrue(result['build_config_guards_passed'], result['build_guard_failures'])
        review = result['reviewed_memory_profile_changes']
        self.assertEqual(set(review), {'CONFIG_MEMCG','CONFIG_PSI','CONFIG_CGROUP_FREEZER'})
        self.assertTrue(all(r['before']=='n' and r['after']=='y' for r in review.values()))

    def test_each_required_memory_interface_and_dependency_is_mandatory(self):
        baseline, values = self.fixture()
        for key, wanted in {**helper.MEMORY_PROFILE, **helper.MEMORY_DEPENDENCIES}.items():
            with self.subTest(key=key):
                wrong = 'n' if wanted=='y' else 'y'
                result = helper.config_guards(baseline, config(values | {key:wrong}))
                self.assertIn(key, result['build_guard_failures'])

    def test_missing_selected_page_counter_and_kmem_are_not_paper_success(self):
        baseline, values = self.fixture()
        for key in ('CONFIG_PAGE_COUNTER','CONFIG_MEMCG_KMEM'):
            changed = dict(values); changed.pop(key)
            self.assertIn(key, helper.config_guards(baseline,config(changed))['build_guard_failures'])

    def test_weakening_requested_cannot_disable_the_independent_memory_contract(self):
        baseline, values = self.fixture()
        for key in ('CONFIG_MEMCG','CONFIG_PSI','CONFIG_CGROUP_FREEZER'):
            with self.subTest(key=key), patch.dict(helper.REQUESTED,{key:'n'}):
                result = helper.config_guards(baseline, config(values | {key:'n'}))
                self.assertIn(key, result['build_guard_failures'])

    def test_memory_exemption_never_hides_susfs_nflog_or_hardware_regression(self):
        baseline, values = self.fixture()
        for key in ('CONFIG_KSU_SUSFS','CONFIG_KSU_SUSFS_SUS_PATH','CONFIG_NETFILTER_XT_TARGET_NFLOG',
                    'CONFIG_MODULES','CONFIG_USB_DWC3_MSM','CONFIG_SECURITY_SELINUX'):
            old = values[key]
            wrong = 'n' if old=='y' else 'y'
            result = helper.config_guards(baseline, config(values | {key:wrong}))
            self.assertIn(key, result['build_guard_failures'], key)

    def test_preexisting_tracing_and_ashmem_choices_are_preserved_by_request(self):
        baseline, _ = self.fixture()
        old = helper.audit.parse_config(baseline)
        new = helper.audit.parse_config(helper.request_config(baseline))
        for key in ('CONFIG_FTRACE','CONFIG_TRACING_SUPPORT','CONFIG_ASHMEM','CONFIG_MODULES'):
            self.assertEqual(new.get(key),old.get(key),key)
        self.assertNotIn('CONFIG_MEMFD_ASHMEM_SHIM', helper.REQUESTED)

    def test_memory_experiment_preserves_selinux_controls_including_forced_permissive(self):
        baseline, values = self.fixture()
        keys = ('CONFIG_SECURITY_SELINUX', 'CONFIG_DEFAULT_SECURITY_SELINUX',
                'CONFIG_SECURITY_SELINUX_DEVELOP', 'CONFIG_SECURITY_SELINUX_BOOTPARAM',
                'CONFIG_SECURITY_SELINUX_DISABLE', 'CONFIG_SECURITY_SELINUX_PERMISSIVE')
        requested = helper.audit.parse_config(helper.request_config(baseline))
        old = helper.audit.parse_config(baseline)
        for key in keys:
            with self.subTest(key=key):
                self.assertEqual(old.get(key), requested.get(key))
                wrong = 'n' if values.get(key, 'n') == 'y' else 'y'
                self.assertIn(key, helper.config_guards(baseline, config(values | {key: wrong}))['build_guard_failures'])

    def test_link_proof_requires_defined_memory_providers(self):
        nm = '\n'.join('ffff0000 D '+s for s in helper.REQUIRED_SYMBOLS)
        self.assertEqual(set(helper.defined_symbols(nm)),helper.REQUIRED_SYMBOLS)
        for symbol in helper.MEMORY_LINK_SYMBOLS:
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                helper.defined_symbols(nm.replace(' D '+symbol,' U '+symbol))

    def test_old_actual_embedded_image_configuration_is_refused(self):
        # The trusted shipped baseline has the same missing three interfaces;
        # it cannot pass merely by retaining SUSFS and NFLOG.
        baseline, _ = self.fixture()
        before = helper.audit.parse_config(baseline)
        result = helper.config_guards(baseline, config(before))
        self.assertTrue({'CONFIG_MEMCG','CONFIG_PSI','CONFIG_CGROUP_FREEZER'} <= result['build_guard_failures'].keys())


if __name__=='__main__': unittest.main()
