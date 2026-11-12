"""Execute the real RMNET migration predicate with exact patched mask headers.

Host fixtures provide the exported mask storage, CPU-online state and endpoint
RPS state. No scheduler/network device or ARM64 kernel is executed.
"""
from pathlib import Path
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('rmnet_current_compat', ROOT / 'tools/kernel_nflog/current_compat.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
FIXTURES = ROOT / 'tools/kernel_nflog/upstream-current'
HEADER = 'include/linux/cpumask.h'
CALLER = 'techpack/data/drivers/rmnet/shs/rmnet_shs_wq.c'


def function(text, name):
    match = re.search(r'^int ' + re.escape(name) + r'\(', text, re.M)
    if not match:
        raise AssertionError('Missing real RMNET predicate')
    opening = text.index('{', match.start())
    depth, ending = 1, opening + 1
    while depth:
        depth += (text[ending] == '{') - (text[ending] == '}')
        ending += 1
    return text[match.start():ending] + '\n'


def mask_api(text):
    # These are the actual declarations/macros consumed by the driver. The
    # generic cpumask implementation is represented by a checked host bitset.
    start = text.index('extern struct cpumask __cpu_possible_mask;')
    ending = text.index('\n#endif', text.index('#if NR_CPUS > 1', start))
    return text[start:ending + len('\n#endif')] + '\n'


PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
typedef unsigned short u16;
#define MAX_CPUS 8
#define RMNET_SHS_WQ_EP_ACCESS_ERR 0
#define RMNET_SHS_WQ_INVALID_CPU_ERR 1
struct cpumask { unsigned long bits; };
static unsigned int nr_cpu_ids = NR_CPUS;
static bool cpumask_test_cpu(unsigned int cpu, const struct cpumask *mask)
{
    assert(cpu < MAX_CPUS);
    return (mask->bits & (1UL << cpu)) != 0;
}
#define cpumask_bits(maskp) (&(maskp)->bits)
#define cpumask_pr_args(maskp) nr_cpu_ids, cpumask_bits(maskp)
static unsigned int rmnet_shs_crit_err[2];
struct rmnet_shs_wq_ep_s { unsigned int rps_config_msk; };
static unsigned int debug_calls;
static char debug_text[1024];
static void rm_err(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void rm_err(const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    assert(vsnprintf(debug_text, sizeof(debug_text), fmt, args) > 0);
    va_end(args);
    debug_calls++;
}
'''

SUFFIX = r'''
/* Actual exported storage exists in pinned kernel/cpu.c; a nonzero mask is
 * supplied here to ensure the restored API cannot pass as a false stub. */
struct cpumask __cpu_possible_mask, __cpu_online_mask, __cpu_present_mask;
struct cpumask __cpu_active_mask, __cpu_isolated_mask;
int main(void)
{
    struct rmnet_shs_wq_ep_s ep = { .rps_config_msk = 0xffU };
    __cpu_isolated_mask.bits = 1UL;
    assert(cpu_isolated(0));
    __cpu_isolated_mask.bits = 0;
    assert(!cpu_isolated(0));
    assert(!rmnet_shs_wq_check_cpu_move_for_ep(0, 1, NULL));
    assert(rmnet_shs_crit_err[RMNET_SHS_WQ_EP_ACCESS_ERR] == 1);
    assert(!rmnet_shs_wq_check_cpu_move_for_ep(MAX_CPUS, 1, &ep));
    assert(!rmnet_shs_wq_check_cpu_move_for_ep(0, MAX_CPUS, &ep));
    assert(rmnet_shs_crit_err[RMNET_SHS_WQ_INVALID_CPU_ERR] == 2);
#if NR_CPUS > 1
    __cpu_online_mask.bits = 0xffU;
    assert(rmnet_shs_wq_check_cpu_move_for_ep(0, 2, &ep));
    assert(strstr(debug_text, "cpu isolation_mask") != NULL);
    __cpu_isolated_mask.bits = 1UL << 2;
    assert(!rmnet_shs_wq_check_cpu_move_for_ep(0, 2, &ep));
    assert(cpu_isolated(2));
    __cpu_isolated_mask.bits = 0;
    assert(rmnet_shs_wq_check_cpu_move_for_ep(0, 2, &ep));
    ep.rps_config_msk &= ~(1U << 2);
    assert(!rmnet_shs_wq_check_cpu_move_for_ep(0, 2, &ep));
    ep.rps_config_msk |= 1U << 2;
    __cpu_online_mask.bits &= ~(1UL << 2);
    assert(!rmnet_shs_wq_check_cpu_move_for_ep(0, 2, &ep));
    __cpu_online_mask.bits |= 1UL << 2;
    assert(!rmnet_shs_wq_check_cpu_move_for_ep(2, 2, &ep));
#else
    assert(!rmnet_shs_wq_check_cpu_move_for_ep(0, 1, &ep));
    assert(!rmnet_shs_wq_check_cpu_move_for_ep(0, 0, &ep));
#endif
    assert(debug_calls > 0);
    puts("PASS: real isolation mask, RPS, online, same-CPU and invalid endpoint/CPU checks");
}
'''


class Tests(unittest.TestCase):
    def test_existing_exported_mask_provider_is_built_without_smp_conditions(self):
        provider = FIXTURES / 'kernel/cpu.c'
        makefile = FIXTURES / 'kernel/Makefile'
        self.assertEqual(helper.file_sha(provider),
                         'e35c6dc43423ca98f5c85f90c1ab30ecd0080186fff9f37226d844876e112656')
        self.assertEqual(helper.file_sha(makefile),
                         '8eb57c35723d247232cdb96726b575ae181b584060ec9b212241f0e7e5e8ca04')
        top_objects = makefile.read_text().split('\n\n', 1)[1].replace('\\\n', ' ')
        self.assertRegex(top_objects, r'obj-y\s*=\s*[^\n]*\bcpu\.o\b')
        stack, declarations = [], []
        for line in provider.read_text().splitlines():
            if re.match(r'\s*#\s*(if|ifdef|ifndef)\b', line):
                stack.append(line)
            elif re.match(r'\s*#\s*endif\b', line):
                stack.pop()
            if '__cpu_isolated_mask' in line:
                declarations.append(line)
                self.assertEqual(stack, [], line)
        self.assertEqual(declarations, ['struct cpumask __cpu_isolated_mask __read_mostly;',
                                        'EXPORT_SYMBOL(__cpu_isolated_mask);'])

    def git(self, source, *arguments):
        return subprocess.check_output(['git', '-C', str(source), *arguments], text=True).strip()

    def patched(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source, evidence = root / 'kernel', root / 'evidence'
        source.mkdir()
        evidence.mkdir()
        for path in helper.PINS:
            destination = source / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FIXTURES / path, destination)
        self.git(source, 'init', '-q')
        self.git(source, 'config', 'user.name', 'Fixture')
        self.git(source, 'config', 'user.email', 'fixture@example.invalid')
        self.git(source, 'add', '.')
        self.git(source, 'commit', '-qm', 'source fixtures')
        commit = self.git(source, 'rev-parse', 'HEAD')
        with patch.object(helper.audit, 'SOURCE_COMMIT', commit):
            helper.apply(source, evidence, dict(os.environ))
        return source

    def compile(self, header, caller, nr_cpus=8, isolation=False):
        if not shutil.which('cc'):
            self.skipTest('Host cc is required for the extracted RMNET predicate')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        code, executable = root / 'rmnet.c', root / 'rmnet'
        code.write_text(PREFIX + mask_api(header) + function(caller, 'rmnet_shs_wq_check_cpu_move_for_ep') + SUFFIX)
        result = subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                                 '-DNR_CPUS=' + str(nr_cpus), '-DCONFIG_CPU_ISOLATION=' + str(int(isolation)),
                                 str(code), '-o', str(executable)], text=True, capture_output=True)
        return result, executable

    def test_original_predicate_reproduces_missing_mask_api_errors(self):
        result, _ = self.compile((FIXTURES / HEADER).read_text(), (FIXTURES / CALLER).read_text())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('cpu_isolated', result.stderr)
        self.assertIn('__cpu_isolated_mask', result.stderr)

    def test_real_mask_excludes_isolated_cpu_without_losing_other_migration_guards(self):
        source = self.patched()
        for nr_cpus, isolation in ((8, False), (8, True), (1, False)):
            with self.subTest(nr_cpus=nr_cpus, isolation=isolation):
                result, executable = self.compile((source / HEADER).read_text(), (source / CALLER).read_text(),
                                                  nr_cpus, isolation)
                self.assertEqual(result.returncode, 0, result.stderr)
                completed = subprocess.run([str(executable)], check=True, text=True, capture_output=True)
                self.assertIn('real isolation mask', completed.stdout)

    def test_debug_format_matches_real_mask_pointer_and_width(self):
        source = self.patched()
        text = (source / CALLER).read_text()
        self.assertIn('cpu isolation_mask = %*pbl', text)
        self.assertIn('cpumask_pr_args(cpu_isolated_mask)', text)
        self.assertNotIn('current_cpu, dest_cpu, __cpu_isolated_mask,', text)
        self.assertNotIn('housekeeping_cpu(', text)


if __name__ == '__main__':
    unittest.main()
