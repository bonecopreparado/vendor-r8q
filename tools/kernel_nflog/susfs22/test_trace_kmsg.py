"""Exercise the actual patched devkmsg routine with stubbed kernel permissions."""
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


STUBS = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>

typedef uint32_t u32;
struct kiocb { int unused; };
struct iov_iter { const char *data; size_t count; bool readable; };
static int current, logs, marks;
static long now;
typedef int atomic_t;
#define ATOMIC_INIT(value) (value)
#define atomic_read(p) (*(p))
#define atomic_inc_return(p) (++*(p))
#define LOGLEVEL_WARNING 4
#define simple_strtoul strtoul
#define ktime_get_boottime_seconds() (now)
static void r8q_mount_mark(const char *message) { assert(message); marks++; }
static u32 caller_sid;
static const char *caller_context;
static char captured[520];
#define task_pid_nr(task) (task)
#define iov_iter_count(iter) ((iter)->count)

static void security_task_getsecid(int task, u32 *secid)
{
    assert(task == current);
    *secid = caller_sid;
}

static int security_secid_to_secctx(u32 secid, char **context, u32 *length)
{
    assert(secid == caller_sid);
    if (!caller_context)
        return -EINVAL;
    *context = (char *)caller_context;
    *length = strlen(caller_context) + 1;
    return 0;
}

static void security_release_secctx(char *context, u32 length)
{
    assert(context == caller_context && length == strlen(caller_context) + 1);
}

static bool copy_from_iter_full(char *dest, size_t length, struct iov_iter *iter)
{
    if (!iter->readable)
        return false;
    memcpy(dest, iter->data, length);
    return true;
}

#define pr_warn(...) (logs++, snprintf(captured, sizeof(captured), __VA_ARGS__))
'''

TEST = r'''
static void check(const char *message, const char *expected)
{
    struct iov_iter input = {message, strlen(message), true};
    int previous_logs = logs;
    int previous_marks = marks;

    assert(devkmsg_write(NULL, &input) == (ssize_t)input.count);
    assert(logs == previous_logs + (expected != NULL));
    assert(marks == previous_marks + (expected && strstr(expected, "R8QTRACE")==expected));
    if (expected)
        assert(!strcmp(captured, expected));
}

int main(void)
{
    current = 1;
    check("<4>R8QTRACE late-fs", "R8QTRACE late-fs\n");
    check("<3>other init log", NULL);
    check("<4>R8QTRACE test\nextra", NULL);

    current = 43;
    caller_sid = 44;
    caller_context = "u:r:vendor_init:s0";
    check("<4>R8QTRACE vendor mount-all:end", "R8QTRACE vendor mount-all:end\n");
    check("<4>R8QTRACE late-fs", NULL);
    caller_context = "u:r:vendor_init:s0:c0";
    check("<4>R8QTRACE vendor spoof", NULL);
    caller_context = "u:r:shell:s0";
    check("<4>R8QTRACE vendor spoof", NULL);
    caller_context = "u:r:vold:s0";
    check("<3>vold: metadata error\n", "R8QVOLD origin=vold pid=43 vold: metadata error\n");
    check("<6>vold: verbose", NULL);
    check("<3>vdc: wrong domain", NULL);
    caller_context = "u:r:vdc:s0";
    check("<7>vdc: wait for service", "R8QVOLD origin=vdc pid=43 vdc: wait for service\n");
    now = 180;
    check("<3>vdc: late", NULL);
    now = 0;
    current = 1;
    check("<3>init: Service vold exited", "R8QVOLD origin=init pid=1 init: Service vold exited\n");
    check("<3>init: unrelated error", NULL);
    current = 43;
    caller_context = NULL;
    check("<4>R8QTRACE vendor invalid-context", NULL);

    struct iov_iter too_long = {"short", 513, true};
    struct iov_iter unreadable = {"short", 100, false};
    int previous_logs = logs;
    assert(devkmsg_write(NULL, &too_long) == 513 && logs == previous_logs);
    assert(devkmsg_write(NULL, &unreadable) == 100 && logs == previous_logs);
    current = 1;
    assert(devkmsg_write(NULL, &unreadable) == -EFAULT && logs == previous_logs);
}
'''


def main(tree):
    source = (tree / 'kernel/printk/printk.c').read_text()
    begin = source.index('static bool r8qtrace_context(')
    end = source.index('static ssize_t devkmsg_read(', begin)
    with TemporaryDirectory() as temp:
        test = Path(temp) / 'trace-test.c'
        binary = Path(temp) / 'trace-test'
        test.write_text(STUBS + source[begin:end] + TEST)
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                        str(test), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    print('Init and vendor_init trace isolation checks passed.')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
