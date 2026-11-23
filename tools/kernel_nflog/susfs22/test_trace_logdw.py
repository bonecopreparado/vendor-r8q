"""Exercise the actual kernel hook with the Android packed text datagram."""
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

STUBS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/un.h>
typedef uint32_t u32;
typedef int atomic_t;
struct unix_address { int len; struct sockaddr_un name[1]; };
struct unix_sock { struct unix_address *addr; };
struct sock { struct unix_sock unix; };
struct sk_buff { size_t len; const char *data; };
static int current, logs, elapsed;
static const char *domain = "u:r:keystore:s0";
static char captured[600];
#define ATOMIC_INIT(i) (i)
#define atomic_read(p) (*(p))
#define atomic_inc_return(p) (++*(p))
#define ktime_get_boottime_seconds() (elapsed)
#define unix_sk(p) (&(p)->unix)
#define smp_load_acquire(p) (*(p))
#define min_t(type,x,y) ((type)(x) < (type)(y) ? (type)(x) : (type)(y))
#define task_tgid_nr(i) (i)
#define security_task_getsecid(who,id) do { assert((who)==42); *(id)=7; } while (0)
static int security_secid_to_secctx(u32 sid, char **ctx, u32 *length) {
    assert(sid == 7);
    *ctx = (char *)domain;
    *length = strlen(domain) + 1;
    return 0;
}
static void security_release_secctx(char *context, u32 length) {
    assert(context == domain && length == strlen(domain) + 1);
}
static int skb_copy_bits(const struct sk_buff *skb, int from, char *data, size_t bytes) {
    assert(from == 0 && bytes <= skb->len);
    memcpy(data, skb->data, bytes);
    return 0;
}
#define pr_warn(...) (logs++, snprintf(captured, sizeof(captured), __VA_ARGS__))
'''

TEST = r'''
int main(void) {
    struct unix_address address = {0};
    struct sock peer = {{&address}};
    char packet[] = "\4" "\0\0\0\0\0\0\0\0\0\0" "\7" "keystore2\0" "fatal\nreason";
    struct sk_buff skb = {sizeof(packet), packet};
    current = 42;
    strcpy(address.name->sun_path, "/dev/socket/logdw");
    address.len = offsetof(struct sockaddr_un, sun_path) + strlen(address.name->sun_path) + 1;
    r8q_keystore_log(&peer, &skb);
    assert(logs == 1 && !strcmp(captured, "R8QKEYSTORE pid=42 priority=7 tag=keystore2 fatal reason\n"));
    packet[11] = 4;
    r8q_keystore_log(&peer, &skb);
    packet[11] = 7;
    domain = "u:r:untrusted_app:s0";
    r8q_keystore_log(&peer, &skb);
    domain = "u:r:keystore:s0";
    address.name->sun_path[12] = 'x';
    r8q_keystore_log(&peer, &skb);
    strcpy(address.name->sun_path, "/dev/socket/logdw");
    skb.len = 14;
    r8q_keystore_log(&peer, &skb);
    skb.len = sizeof(packet);
    elapsed = 180;
    r8q_keystore_log(&peer, &skb);
    assert(logs == 1);
    elapsed = 0;
    for (int i = 0; i < 60; i++)
        r8q_keystore_log(&peer, &skb);
    assert(logs == 48);
}
'''

if __name__ == '__main__':
    source = (Path(sys.argv[1])/'net/unix/af_unix.c').read_text()
    start = source.index('static atomic_t r8q_keystore_messages')
    end = source.index('static int unix_dgram_sendmsg(', start)
    with TemporaryDirectory() as temp:
        path = Path(temp)/'test.c'
        binary = Path(temp)/'test'
        path.write_text(STUBS+source[start:end]+TEST)
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(path),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
    print('Verified packet parsing, trusted sender, correct peer and capture bounds.')
