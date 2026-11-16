"""Execute actual patched memcg IDR writers with lock-order checking host stubs.

This checks registration/error cleanup, not kernel concurrency or lockdep.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

text=(Path(sys.argv[1])/'mm/vmscan.c').read_text()


def function(signature):
    start=text.index(signature)
    return text[start:text.index('\n}',start)+2]


declaration='static DECLARE_RWSEM(shrinker_rwsem);'
if text.count(declaration)!=1:raise ValueError('Expected one actual memcg lifetime rwsem')
program=r'''#include <assert.h>
#include <errno.h>
#include <stddef.h>
#define CONFIG_MEMCG_KMEM 1
#define SHRINKER_MEMCG_AWARE 1
#define GFP_KERNEL 0
#define BUG_ON(x) assert(!(x))
struct semaphore { int held; };
#define DECLARE_RWSEM(x) struct semaphore x = {0}
struct list {int unused;};
struct shrinker {int flags,id;struct semaphore del_rwsem;struct list list;};
#define SHRINKER_REGISTERING ((struct shrinker *)~0UL)
static struct {struct shrinker *slots[8];} shrinker_idr;
static int shrinker_nr_max,shrinker_lock,spin_held,expand_error;
static struct list shrinker_list;
'''+declaration+r'''
static void down_write(struct semaphore *s) {assert(!spin_held);assert(!s->held);s->held=1;}
static void up_write(struct semaphore *s) {assert(s->held);s->held=0;}
static void init_rwsem(struct semaphore *s) {s->held=0;}
static void spin_lock(int *s) {(void)s;assert(!spin_held);spin_held=1;}
static void spin_unlock(int *s) {(void)s;assert(spin_held);spin_held=0;}
static void list_add_tail_rcu(struct list *a,struct list *b) {(void)a;(void)b;assert(spin_held);}
static int memcg_expand_shrinker_maps(int id) {(void)id;assert(shrinker_rwsem.held);return expand_error;}
static int idr_alloc(void *idr,struct shrinker *value,int lo,int hi,int gfp) {
 (void)idr;(void)lo;(void)hi;(void)gfp;assert(shrinker_rwsem.held);
 for(int i=0;i<8;i++)if(!shrinker_idr.slots[i]){shrinker_idr.slots[i]=value;return i;}
 return -ENOMEM;
}
static void idr_remove(void *idr,int id) {(void)idr;assert(shrinker_rwsem.held);shrinker_idr.slots[id]=NULL;}
static void idr_replace(void *idr,struct shrinker *value,int id) {
 (void)idr;assert(shrinker_rwsem.held);assert(shrinker_idr.slots[id]==SHRINKER_REGISTERING);shrinker_idr.slots[id]=value;
}
'''
for signature in ('static int prealloc_memcg_shrinker(', 'static void unregister_memcg_shrinker(',
                  'void register_shrinker_prepared('):
    program+='\n'+function(signature)+'\n'
program+=r'''
int main(void) {
 struct shrinker s={.flags=SHRINKER_MEMCG_AWARE};
 for(int i=0;i<1000;i++) {
  assert(!prealloc_memcg_shrinker(&s));assert(shrinker_idr.slots[s.id]==SHRINKER_REGISTERING);
  register_shrinker_prepared(&s);assert(shrinker_idr.slots[s.id]==&s);
  unregister_memcg_shrinker(&s);assert(!shrinker_idr.slots[s.id]);assert(!shrinker_rwsem.held);
 }
 /* Failure to expand maps removes the temporary ID and releases the lock. */
 shrinker_nr_max=0;expand_error=1;assert(prealloc_memcg_shrinker(&s)==-ENOMEM);
 assert(!shrinker_idr.slots[0]);assert(!shrinker_rwsem.held);expand_error=0;
 for(int i=0;i<8;i++)shrinker_idr.slots[i]=SHRINKER_REGISTERING;
 assert(prealloc_memcg_shrinker(&s)==-ENOMEM);assert(!shrinker_rwsem.held);
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='r8q-shrinker-test-')as work:
    p=Path(work)/'shrinker.c';p.write_text(program);exe=Path(work)/'shrinker'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',p,'-o',exe],check=True)
    subprocess.run([exe],check=True)
print('Actual memcg registration/IDR cleanup statements passed host lock-order checks; not kernel concurrency proof')
