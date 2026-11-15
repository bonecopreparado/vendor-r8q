"""Offline exact-source overlay and ownership/error-path checks.

C stubs execute extracted real functions, not a kernel or storage device.
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
spec = importlib.util.spec_from_file_location('current_source_compat', ROOT / 'tools/kernel_nflog/current_compat.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
FIXTURES = ROOT / 'tools/kernel_nflog/upstream-current'


def function(text, name):
    match = re.search(r'^(?:static )?(?:int|void|ssize_t) ' + re.escape(name) + r'\(', text, re.M)
    if not match:
        raise AssertionError('Missing real source function: ' + name)
    opening = text.index('{', match.start())
    depth = 1
    ending = opening + 1
    while depth:
        depth += (text[ending] == '{') - (text[ending] == '}')
        ending += 1
    return text[match.start():ending] + '\n'


class Tests(unittest.TestCase):
    def git(self, source, *arguments):
        return subprocess.check_output(['git', '-C', str(source), *arguments], text=True).strip()

    def fixture(self):
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
        (source / 'unrelated.txt').write_text('unchanged\n')
        self.git(source, 'init', '-q')
        self.git(source, 'config', 'user.name', 'Fixture')
        self.git(source, 'config', 'user.email', 'fixture@example.invalid')
        self.git(source, 'add', '.')
        self.git(source, 'commit', '-qm', 'exact source byte fixtures')
        commit = self.git(source, 'rev-parse', 'HEAD')
        return source, evidence, commit

    def apply_fixture(self):
        source, evidence, commit = self.fixture()
        with patch.object(helper.audit, 'SOURCE_COMMIT', commit):
            report = helper.apply(source, evidence, dict(os.environ))
        return source, evidence, report, commit

    def compile(self, source, name, flags=()):
        if not shutil.which('cc'):
            self.skipTest('Host cc is required for real-function ownership fixtures')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        text, executable = root / (name + '.c'), root / name
        text.write_text(source)
        result = subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-O0', *flags,
                                 str(text), '-o', str(executable)], text=True, capture_output=True)
        return result, executable

    def test_unmodified_fixtures_and_patch_bytes_match_exact_pins(self):
        for path, pin in helper.PINS.items():
            with self.subTest(path=path):
                self.assertEqual(helper.file_sha(FIXTURES / path), pin['before_sha256'])
                self.assertEqual(helper.file_sha(helper.PATCH_ROOT / pin['patch']), pin['patch_sha256'])
        self.assertIn('Copyright (C) 2016 Jens Axboe', (FIXTURES / 'block/mq-deadline.c').read_text())
        self.assertIn('This code is released using a dual license strategy: BSD/GPL',
                      (FIXTURES / 'drivers/block/zram/zram_drv.c').read_text())
        self.assertEqual(helper.file_sha(FIXTURES / 'include/linux/cpufreq.h'),
                         'bc7997d40e4e1e3797f8c810ff537de1cba8835fa2bd8adb804d13892ef1bf84')

    def test_reviewed_patches_apply_and_after_bytes_and_report_are_exact(self):
        source, evidence, report, commit = self.apply_fixture()
        for path, pin in helper.PINS.items():
            self.assertEqual(helper.file_sha(source / path), pin['after_sha256'])
        with patch.object(helper.audit, 'SOURCE_COMMIT', commit):
            self.assertEqual(report, helper.expected_report())
            self.assertEqual(helper.verify_applied(source, dict(os.environ)).splitlines(), sorted(helper.PINS))
        self.assertTrue((evidence / 'reviewed-source-overlay.json').is_file())

    def test_wrong_source_commit_or_initial_dirty_tree_is_rejected(self):
        source, evidence, commit = self.fixture()
        with self.assertRaisesRegex(ValueError, 'exact current source commit'):
            helper.apply(source, evidence, dict(os.environ))
        (source / 'unrelated.txt').write_text('dirty\n')
        with patch.object(helper.audit, 'SOURCE_COMMIT', commit):
            with self.assertRaisesRegex(ValueError, 'initially clean'):
                helper.apply(source, evidence, dict(os.environ))

    def test_changed_patch_is_rejected_before_any_source_write(self):
        source, evidence, commit = self.fixture()
        patch_root = source.parent / 'patches'
        shutil.copytree(helper.PATCH_ROOT, patch_root)
        first = next(iter(helper.PINS.values()))['patch']
        with (patch_root / first).open('a') as handle:
            handle.write('\nchanged patch\n')
        with patch.object(helper.audit, 'SOURCE_COMMIT', commit), patch.object(helper, 'PATCH_ROOT', patch_root):
            with self.assertRaisesRegex(ValueError, 'patch hash differs'):
                helper.apply(source, evidence, dict(os.environ))
        self.assertFalse(self.git(source, 'status', '--porcelain'))

    def test_unreviewed_modified_staged_and_changed_after_bytes_fail(self):
        source, evidence, report, commit = self.apply_fixture()
        with patch.object(helper.audit, 'SOURCE_COMMIT', commit):
            (source / 'unrelated.txt').write_text('modified\n')
            with self.assertRaisesRegex(ValueError, 'exact reviewed compatibility files'):
                helper.verify_applied(source, dict(os.environ))
            (source / 'unrelated.txt').write_text('unchanged\n')
            self.git(source, 'add', 'block/mq-deadline.c')
            with self.assertRaisesRegex(ValueError, 'staged source changes'):
                helper.verify_applied(source, dict(os.environ))
            self.git(source, 'reset', '-q', 'HEAD', '--', 'block/mq-deadline.c')
            with (source / 'block/mq-deadline.c').open('a') as handle:
                handle.write('\n/* unreviewed */\n')
            with self.assertRaisesRegex(ValueError, 'patched source bytes differ'):
                helper.verify_applied(source, dict(os.environ))

    def test_mq_merge_batches_release_after_unlock_without_loss_or_double_free(self):
        original = (FIXTURES / 'block/mq-deadline.c').read_text()
        result, _ = self.compile(MQ_PREFIX + function(original, 'dd_insert_request') +
                                 function(original, 'dd_insert_requests') + MQ_SUFFIX, 'mq-before')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('too few arguments', result.stderr)
        source, _, _, _ = self.apply_fixture()
        current = (source / 'block/mq-deadline.c').read_text()
        result, executable = self.compile(MQ_PREFIX + function(current, 'dd_insert_request') +
                                          function(current, 'dd_insert_requests') + MQ_SUFFIX, 'mq-after')
        self.assertEqual(result.returncode, 0, result.stderr)
        run = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
        self.assertIn('multiple-merge/mixed batches', run.stdout)

    def zram_harness(self, text):
        start = text.index('struct zram_work {')
        work = text[start:text.index('};', start) + 2] + '\n'
        writeback = function(text, 'writeback_store')
        start = writeback.index('\t\tbio_init(')
        ending = writeback.index('\n', writeback.index('__bio_add_page(', start))
        setup = writeback[start:ending]
        fragment = ('static int writeback_fragment(struct zram *zram, struct page *page, unsigned long blk_idx)\n'
                    '{\nstruct bio bio; struct bio_vec bio_vec;\n' + setup +
                    '\nreturn submit_bio_wait(&bio);\n}\n')
        return (ZRAM_PREFIX + function(text, 'read_from_bdev_async') + work +
                function(text, 'zram_sync_read') + function(text, 'read_from_bdev_sync') +
                function(text, 'read_from_bdev') + fragment + ZRAM_SUFFIX)

    def test_zram_allocation_failure_chaining_and_read_write_bio_metadata(self):
        original = (FIXTURES / 'drivers/block/zram/zram_drv.c').read_text()
        result, _ = self.compile(self.zram_harness(original), 'zram-before')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('arguments', result.stderr)
        source, _, _, _ = self.apply_fixture()
        current = (source / 'drivers/block/zram/zram_drv.c').read_text()
        result, executable = self.compile(self.zram_harness(current), 'zram-after')
        self.assertEqual(result.returncode, 0, result.stderr)
        run = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
        self.assertIn('allocation failure propagation', run.stdout)

    def test_zram_claim_flags_and_error_return_reach_existing_bio_error_path(self):
        source, _, _, _ = self.apply_fixture()
        current = (source / 'drivers/block/zram/zram_drv.c').read_text()
        self.assertEqual(current.count('blkdev_put(bdev, FMODE_READ | FMODE_WRITE | FMODE_EXCL);'), 2)
        self.assertIn('FMODE_READ | FMODE_WRITE | FMODE_EXCL, zram);', current)
        self.assertNotIn('BLK_OPEN_', current)
        self.assertIn('return read_from_bdev_async(zram, page, entry, parent);', function(current, 'read_from_bdev'))
        # The unchanged caller chain returns negative errors; the request path
        # already reaches bio_io_error, rather than completing failed reads OK.
        self.assertIn('ret = read_from_bdev(', function(current, 'zram_read_page'))
        self.assertIn('return ret;', function(current, 'zram_read_page'))
        self.assertIn('return zram_read_page(', function(current, 'zram_bvec_read'))
        self.assertIn('if (unlikely(ret < 0))', function(current, 'zram_bvec_rw'))
        self.assertIn('bio_io_error(bio);', current)

    def test_max77705_optional_cpu_votes_match_real_provider_and_preserve_other_boosts(self):
        original = (FIXTURES / 'drivers/ccic/max77705_usbc.c').read_text()
        header = (FIXTURES / 'include/linux/cpufreq.h').read_text()
        api = re.search(r'#if defined\(CONFIG_CPU_FREQ_LIMIT_USERSPACE\)\nenum \{.*?\nint set_freq_limit\(unsigned long id, unsigned int freq\);\n#endif',
                        header, re.S).group(0)
        self.assertIn('#ifdef CONFIG_USB_AUDIO_ENHANCED_DETECT_TIME\n\tDVFS_BOOST_HOST_ID', api)
        before = (MAX_PREFIX + api + MAX_BACKEND + function(original, 'max77705_clk_booster_set') +
                  function(original, 'max77705_clk_booster_off') + MAX_SUFFIX)
        result, _ = self.compile(before, 'max77705-before')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DVFS_BOOST_HOST_ID', result.stderr)
        source, _, _, _ = self.apply_fixture()
        current = (source / 'drivers/ccic/max77705_usbc.c').read_text()
        self.assertIn('#ifdef CONFIG_CPU_FREQ_LIMIT_USERSPACE\n#include <linux/cpufreq.h>\n#endif', current)
        for enabled in (False, True):
            with self.subTest(provider=enabled):
                code = (MAX_PREFIX + api + MAX_BACKEND + function(current, 'max77705_clk_booster_set') +
                        function(current, 'max77705_clk_booster_off') + MAX_SUFFIX)
                flags = ('-DCONFIG_CPU_FREQ_LIMIT_USERSPACE=1',) if enabled else ()
                result, executable = self.compile(code, 'max77705-after-' + str(enabled), flags)
                self.assertEqual(result.returncode, 0, result.stderr)
                run = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
                self.assertIn('HMP/DDR/timers retained', run.stdout)

MQ_PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
struct list_head { struct list_head *next, *prev; };
#define LIST_HEAD(name) struct list_head name = { &(name), &(name) }
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define list_first_entry(head, type, member) container_of((head)->next, type, member)
static void INIT_LIST_HEAD(struct list_head *h) { h->next=h->prev=h; }
static int list_empty(struct list_head *h) {return h->next==h;}
static void list_add(struct list_head *n,struct list_head *h){n->next=h->next;n->prev=h;h->next->prev=n;h->next=n;}
static void list_add_tail(struct list_head *n,struct list_head *h){list_add(n,h->prev);}
static void list_del_init(struct list_head *n){n->prev->next=n->next;n->next->prev=n->prev;INIT_LIST_HEAD(n);}
struct deadline_data {int lock;struct list_head dispatch,fifo_list[2];int fifo_expire[2];};
struct elevator_queue{void *elevator_data;};
struct request {struct list_head queuelist;int merge,dir,freed;long fifo_time;struct request *extra;};
struct request_queue {struct elevator_queue *elevator;struct request *last_merge;};
struct blk_mq_hw_ctx {struct request_queue *queue;};
static int jiffies=1,inserted,freed,released_batches;
static struct deadline_data *locked_dd;
static void spin_lock(int *l){assert(*l==0);*l=1;}
static void spin_unlock(int *l){assert(*l==1);*l=0;}
static int rq_data_dir(struct request *r){return r->dir;}
static void blk_req_zone_write_unlock(struct request *r){(void)r;assert(locked_dd->lock==1);}
static bool blk_mq_sched_try_insert_merge(struct request_queue *q,struct request *r,struct list_head *free){
 (void)q;assert(locked_dd->lock==1);
 if(!r->merge)return false;
 list_add(&r->queuelist,free);
 if(r->extra)list_add(&r->extra->queuelist,free);
 return true;
}
static void blk_mq_free_requests(struct list_head *free){
 assert(locked_dd->lock==0);released_batches++;
 while(!list_empty(free)){struct request *r=list_first_entry(free,struct request,queuelist);assert(!r->freed);r->freed=1;freed++;list_del_init(&r->queuelist);}
}
static void blk_mq_sched_request_inserted(struct request *r){(void)r;assert(locked_dd->lock==1);inserted++;}
static bool blk_rq_is_passthrough(struct request *r){(void)r;return false;}
static bool rq_mergeable(struct request *r){(void)r;return true;}
static void deadline_add_rq_rb(struct deadline_data *d,struct request *r){(void)d;(void)r;}
static void elv_rqhash_add(struct request_queue *q,struct request *r){(void)q;(void)r;}
'''

MQ_SUFFIX = r'''
static void run_case(int count,int mask,int extra,int expect_freed,int expect_inserted){
 struct deadline_data dd={0};struct elevator_queue e={.elevator_data=&dd};struct request_queue q={.elevator=&e};struct blk_mq_hw_ctx h={.queue=&q};
 struct request r[5]={0};LIST_HEAD(in);
 INIT_LIST_HEAD(&dd.dispatch);INIT_LIST_HEAD(&dd.fifo_list[0]);INIT_LIST_HEAD(&dd.fifo_list[1]);
 for(int i=0;i<5;i++)INIT_LIST_HEAD(&r[i].queuelist);
 for(int i=0;i<count;i++){r[i].merge=(mask>>i)&1;list_add_tail(&r[i].queuelist,&in);}
 if(extra)r[0].extra=&r[4];
 inserted=freed=released_batches=0;locked_dd=&dd;
 dd_insert_requests(&h,&in,true);
 assert(list_empty(&in));assert(dd.lock==0);assert(freed==expect_freed);assert(inserted==expect_inserted);assert(released_batches==1);
}
int main(void){
 run_case(0,0,0,0,0);
 run_case(2,0,0,0,2);
 run_case(1,1,0,1,0);
 run_case(2,3,1,3,0);
 run_case(3,5,1,3,1);
 puts("PASS: empty/nonmerge/one-merge/multiple-merge/mixed batches; releases happen after scheduler unlock");
}
'''

ZRAM_PREFIX = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#define PAGE_SIZE 4096UL
#define GFP_NOIO 123
#define REQ_OP_READ 0U
#define REQ_OP_WRITE 1U
#define REQ_SYNC 0x100U
#define ZRAM_PARTIAL_IO 1
#define IS_ENABLED(x) (x)
#define WARN_ON_ONCE(x) (x)
#define container_of(ptr,type,member) ((type *)((char *)(ptr)-offsetof(type,member)))
struct block_device { int id; };
struct page { int id; };
struct bio_vec { int unused; };
struct bio { unsigned int bi_opf; struct {unsigned long bi_sector;} bi_iter;
 struct block_device *dev; struct page *page; struct bio *parent;
 unsigned int size; int initialized,pending; };
struct zram { struct block_device *bdev; struct {int bd_reads;} stats; };
struct work_struct { void (*fn)(struct work_struct *); };
#define INIT_WORK_ONSTACK(work,func) ((work)->fn=(func))
static int system_unbound_wq;
static void queue_work(int q, struct work_struct *work){(void)q;work->fn(work);}
static void flush_work(struct work_struct *work){(void)work;}
static void destroy_work_on_stack(struct work_struct *work){(void)work;}
static struct bio allocated,last;
static int fail_alloc,alloc_calls,chained,submitted,wait_result;
static void atomic64_inc(int *v){++*v;}
static struct bio *bio_alloc(int gfp, unsigned int count){
 assert(gfp==GFP_NOIO && count==1);alloc_calls++;
 if(fail_alloc)return NULL;
 memset(&allocated,0,sizeof(allocated));allocated.initialized=1;return &allocated;
}
static void bio_init(struct bio *bio,struct bio_vec *v,unsigned short count){
 assert(v!=NULL && count==1);memset(bio,0,sizeof(*bio));bio->initialized=1;
}
static void bio_set_dev(struct bio *bio,struct block_device *dev){assert(bio->initialized);bio->dev=dev;}
static void __bio_add_page(struct bio *bio,struct page *page,unsigned int bytes,unsigned int offset){
 assert(bio->initialized && bytes==PAGE_SIZE && offset==0);bio->page=page;bio->size=bytes;
}
static void bio_chain(struct bio *bio,struct bio *parent){
 assert(bio->initialized && parent);bio->parent=parent;parent->pending++;chained++;
}
static void submit_bio(struct bio *bio){last=*bio;submitted++;}
static int submit_bio_wait(struct bio *bio){bio->bi_opf|=REQ_SYNC;last=*bio;submitted++;return wait_result;}
'''

ZRAM_SUFFIX = r'''
static void reset(void){
 fail_alloc=alloc_calls=chained=submitted=wait_result=0;
 memset(&allocated,0,sizeof(allocated));memset(&last,0,sizeof(last));
}
int main(void){
 struct block_device dev={.id=7};struct zram zram={.bdev=&dev};struct page page={.id=11};
 struct bio parent={.bi_opf=0x120U,.pending=5};
 reset();
 assert(read_from_bdev(&zram,&page,7,&parent)==0);
 assert(alloc_calls==1 && chained==1 && submitted==1);
 assert(parent.pending==6 && last.parent==&parent && last.dev==&dev);
 assert(last.bi_opf==parent.bi_opf && last.bi_iter.bi_sector==56);
 assert(last.page==&page && last.size==PAGE_SIZE && zram.stats.bd_reads==1);

 reset();parent.pending=5;fail_alloc=1;
 assert(read_from_bdev(&zram,&page,8,&parent)==-ENOMEM);
 assert(alloc_calls==1 && chained==0 && submitted==0 && parent.pending==5);
 assert(zram.stats.bd_reads==2);

 reset();wait_result=-EIO;
 assert(read_from_bdev(&zram,&page,13,NULL)==-EIO);
 assert(alloc_calls==0 && chained==0 && submitted==1);
 assert(last.dev==&dev && last.page==&page && last.size==PAGE_SIZE);
 assert(last.bi_opf==(REQ_OP_READ|REQ_SYNC) && last.bi_iter.bi_sector==104);
 assert(zram.stats.bd_reads==3);

 reset();wait_result=-EIO;
 assert(writeback_fragment(&zram,&page,27)==-EIO);
 assert(submitted==1 && chained==0 && last.dev==&dev && last.page==&page);
 assert(last.bi_opf==(REQ_OP_WRITE|REQ_SYNC) && last.bi_iter.bi_sector==216 && last.size==PAGE_SIZE);
 puts("PASS: async success, allocation failure propagation, sync read and write BIO device/flags/sector");
}
'''



MAX_PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <limits.h>
#include <stdio.h>
#define CONFIG_USB_AUDIO_ENHANCED_DETECT_TIME 1
#define MAX_FREQ 2841600
#define CLK_BOOSTER_OFF_WAIT_MS 5000
#define SYSTEM_RUNNING 1
#define pr_info(...) ((void)0)
#define container_of(ptr,type,member) ((type *)((char *)(ptr)-offsetof(type,member)))
struct work_struct { int unused; };
struct delayed_work {struct work_struct work;};
struct max77705_usbc_platform_data {bool set_booster;struct delayed_work acc_booster_off_work;};
static int system_state,cancelled,scheduled,sched_calls,sched_level,bus_calls,bus_index;
static unsigned int cpu_calls,cpu_frequency;
static unsigned long delay;
static unsigned int bus_hdl=77;
static struct delayed_work *expected_work;
static void cancel_delayed_work_sync(struct delayed_work *work){assert(work==expected_work);cancelled++;}
static void schedule_delayed_work(struct delayed_work *work,unsigned long d){assert(work==expected_work);scheduled++;delay=d;}
static unsigned long msecs_to_jiffies(unsigned long ms){return ms;}
static void sched_set_boost(int on){sched_calls++;sched_level=on;}
static int trans_freq_to_idx(int freq){assert(freq==2736);return 12;}
static void msm_bus_scale_client_update_request(unsigned int handle,int index){assert(handle==bus_hdl);bus_calls++;bus_index=index;}
'''


MAX_BACKEND = r'''
#ifdef CONFIG_CPU_FREQ_LIMIT_USERSPACE
int set_freq_limit(unsigned long id,unsigned int freq){
 assert(id==DVFS_BOOST_HOST_ID);cpu_calls++;cpu_frequency=freq;return -1;
}
#endif
'''


MAX_SUFFIX = r'''
int main(void){
 struct max77705_usbc_platform_data data={0};expected_work=&data.acc_booster_off_work;
 system_state=0;
 max77705_clk_booster_set(&data,1);
 assert(!data.set_booster && cancelled==0 && scheduled==0 && sched_calls==0 && bus_calls==0 && cpu_calls==0);
 system_state=SYSTEM_RUNNING;
 max77705_clk_booster_set(&data,1);
 assert(data.set_booster && cancelled==1 && scheduled==1 && delay==CLK_BOOSTER_OFF_WAIT_MS);
 assert(sched_calls==1 && sched_level==1 && bus_calls==1 && bus_index==12);
#ifdef CONFIG_CPU_FREQ_LIMIT_USERSPACE
 assert(cpu_calls==1 && cpu_frequency==MAX_FREQ);
#else
 assert(cpu_calls==0 && cpu_frequency==0);
#endif
 max77705_clk_booster_set(&data,0);
 assert(data.set_booster && cancelled==2 && scheduled==2 && delay==0);
 max77705_clk_booster_off(&data.acc_booster_off_work.work);
 assert(!data.set_booster && sched_calls==2 && sched_level==0 && bus_calls==2 && bus_index==0);
#ifdef CONFIG_CPU_FREQ_LIMIT_USERSPACE
 assert(cpu_calls==2 && cpu_frequency==UINT_MAX);
#else
 assert(cpu_calls==0 && cpu_frequency==0);
#endif
 max77705_clk_booster_set(&data,0);
 assert(cancelled==3 && scheduled==2);
 assert(sched_calls==2 && bus_calls==2);
 puts("PASS: optional CPU provider branches; HMP/DDR/timers retained");
}
'''


if __name__ == '__main__':
    unittest.main()
