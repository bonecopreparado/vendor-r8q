"""Exercise actual scheduler candidate scan with non-CPU capacity values."""
from pathlib import Path
import subprocess
import sys
import tempfile

text=(Path(sys.argv[1])/'kernel/sched/fair.c').read_text()
def function(signature):
    start=text.index(signature)
    return text[start:text.index('\n}',start)+2]
provider=function('static inline bool fits_capacity(')
scan=function('static void select_cpu_candidates(')
program=r'''
#include <assert.h>
#include <stdbool.h>
#include <limits.h>
typedef struct { unsigned bits; } cpumask_t;
struct rq { unsigned long fits_capacity_threshold; } queues[8];
struct task_struct { cpumask_t cpus_allowed; };
struct sched_domain { cpumask_t span; };
struct perf_domain { struct perf_domain *next; cpumask_t span; };
struct cpuidle_state { unsigned exit_latency; };
static int prefer, boosted, checked;
static unsigned long load[8], capacity[8], clamp_floor;
static struct cpuidle_state state={1};
static struct rq *cpu_rq(int cpu) { assert(cpu>=0 && cpu<8); checked++;return &queues[cpu]; }
static bool uclamp_latency_sensitive(struct task_struct *p) {(void)p;return prefer;}
static bool uclamp_boosted(struct task_struct *p) {(void)p;return boosted;}
static bool cpumask_test_cpu(int cpu,cpumask_t *p) {assert(cpu>=0&&cpu<8);return p->bits&(1u<<cpu);}
static void cpumask_set_cpu(int cpu,cpumask_t *p) {assert(cpu>=0&&cpu<8);p->bits|=1u<<cpu;}
#define perf_domain_span(p) (&(p)->span)
#define sched_domain_span(p) (&(p)->span)
#define for_each_cpu_and(cpu,a,b) for(cpu=0;cpu<8;cpu++) if(cpumask_test_cpu(cpu,a)&&cpumask_test_cpu(cpu,b))
static unsigned long cpu_util_next(int cpu,struct task_struct*p,int dst){(void)p;assert(dst==cpu);return load[cpu];}
static unsigned long capacity_of(int cpu){assert(cpu>=0&&cpu<8);return capacity[cpu];}
static unsigned long capacity_orig_of(int cpu){return capacity_of(cpu);}
static unsigned long uclamp_rq_util_with(struct rq*r,unsigned long u,struct task_struct*p){(void)r;(void)p;return u>clamp_floor?u:clamp_floor;}
static bool idle_cpu(int cpu){return cpu==1;}
static struct cpuidle_state* idle_get_state(struct rq*r){(void)r;return &state;}
'''+provider+'\n'+scan+r'''
int main(void) {
 struct task_struct p={{255}};struct sched_domain sd={{255}};
 struct perf_domain pd={0,{255}};cpumask_t out={0};
 for(int i=0;i<8;i++){capacity[i]=i<4?512:1024;queues[i].fits_capacity_threshold=i<4?400:800;load[i]=100+i;}
 select_cpu_candidates(&sd,&out,&pd,&p,0);assert(out.bits==(1u<<4));assert(checked>8);
 out.bits=0;clamp_floor=900;select_cpu_candidates(&sd,&out,&pd,&p,0);assert(out.bits==0);
 out.bits=0;clamp_floor=0;prefer=1;select_cpu_candidates(&sd,&out,&pd,&p,0);assert(out.bits==(1u<<1));
 out.bits=0;prefer=0;p.cpus_allowed.bits=1u<<7;select_cpu_candidates(&sd,&out,&pd,&p,0);assert(out.bits==(1u<<7));
 return 0;
}
'''
with tempfile.TemporaryDirectory()as work:
    source=Path(work)/'capacity.c';source.write_text(program)
    exe=Path(work)/'capacity'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('Actual CPU candidate scan preserved bounds, capacity choice, uclamp and affinity')
