"""Exercise the real utilization provider and reject the stale missing API."""
from pathlib import Path
import subprocess
import sys
import tempfile

text=(Path(sys.argv[1])/'kernel/sched/fair.c').read_text()
if '__cpu_overutilized(' in text:
    raise ValueError('The removed scheduler API is still referenced')
start=text.index('static int find_energy_efficient_cpu(')
end=text.index('\n}',start)+2
caller=text[start:end]
if caller.count('cpu_overutilized(prev_cpu)')!=1 or 'int delta = 0;' in caller:
    raise ValueError('Expected the actual current provider at the stale zero-delta call')
start=text.index('bool cpu_overutilized(int cpu)')
end=text.index('\n}',start)+2
provider=text[start:end]
program='''#include <assert.h>
#include <stdbool.h>
#define UCLAMP_MAX 1
static int fit_result,observed_cpu,observed_min;
static unsigned long observed_util,observed_max;
static void *cpu_rq(int cpu) { assert(cpu==3); return (void *)1; }
static unsigned long uclamp_rq_get(void *rq,int id) { assert(rq==(void *)1 && id==UCLAMP_MAX);return 700; }
static unsigned long cpu_util(int cpu) { assert(cpu==3);return 600; }
static int util_fits_cpu(unsigned long util,int min,unsigned long max,int cpu) {
 observed_util=util;observed_min=min;observed_max=max;observed_cpu=cpu;return fit_result;
}
'''+provider+'''
int main(void) {
 fit_result=1;assert(cpu_overutilized(3)==false);
 assert(observed_util==600 && observed_min==0 && observed_max==700 && observed_cpu==3);
 fit_result=0;assert(cpu_overutilized(3)==true);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as work:
    source=Path(work)/'sched.c';source.write_text(program)
    exe=Path(work)/'sched'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('Actual uclamp-aware scheduler provider passed both fit and non-fit scenarios')
