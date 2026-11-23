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
static struct unix_address address;
static struct sock peer = {{&address}};
static void check(const char *sender, int priority, const char *tag,
                  const char *text, const char *expected) {
    char bytes[600] = {4};
    int total = logs;
    bytes[11] = priority;
    size_t tag_bytes = strlen(tag) + 1;
    memcpy(bytes + 12, tag, tag_bytes);
    size_t text_bytes = strlen(text) + 1;
    assert(12 + tag_bytes + text_bytes <= sizeof(bytes));
    memcpy(bytes + 12 + tag_bytes, text, text_bytes);
    struct sk_buff skb = {12 + tag_bytes + text_bytes, bytes};
    domain = sender;
    r8q_tee_log(&peer, &skb);
    assert(logs == total + (expected != NULL));
    if (expected) assert(strstr(captured, expected) != NULL);
}
int main(void) {
    const char *ks = "u:r:keystore:s0", *km = "u:r:hal_keymaster_default:s0";
    const char *ready = "Keymaster HAL service is Ready.";
    const char *aidl = "Skipping keymaster compat, this system is AIDL only.";
    current = 42;
    strcpy(address.name->sun_path, "/dev/socket/logdw");
    address.len = offsetof(struct sockaddr_un, sun_path) + strlen(address.name->sun_path) + 1;
    check(ks, 7, "keystore2", "fatal\nreason", "R8QKEYSTORE pid=42 priority=7 tag=keystore2 fatal reason\n");
    check(ks, 4, "keystore2", "ordinary info", NULL);
    check(ks, 4, "keystore2", aidl, "R8QTEE origin=compat ");
    check(km, 4, "samsung", ready, "R8QTEE origin=samsung ");
    check(km, 6, "linker", "CANNOT LINK EXECUTABLE: library missing", "library missing");
    check(km, 6, "hal", "private key contents", NULL);
    check("u:r:vendor_hal_qseecom_default:s0", 6, "QSEEComAPI",
          "QSEECom_start_app private fields failed", "QSEECom_start_app failed\n");
    assert(strstr(captured, "private") == NULL);
    check("u:r:hwservicemanager:s0", 4, "hwservicemanager", "hwservicemanager is ready now.", "origin=hwservicemanager ");
    check("u:r:hwservicemanager:s0", 4, "hwservicemanager", "audio service registered", NULL);
    check("u:r:hwservicemanager:s0", 4, "hwservicemanager", "HIDL is not supported on this device", "HIDL is not supported");
    check("u:r:hwservicemanager:s0", 6, "libvintf", "get manifest error", "get manifest error");
    check("u:r:untrusted_app:s0", 7, "linker", "CANNOT LINK EXECUTABLE", NULL);
    check("u:r:hal_keymaster_default:s0:c2", 4, "samsung", ready, NULL);
    check(km, 3, "samsung", ready, NULL);
    address.name->sun_path[12] = 'x';
    check(km, 4, "samsung", ready, NULL);
    strcpy(address.name->sun_path, "/dev/socket/logdw");
    char bad[20] = {4}; bad[11] = 7;
    struct sk_buff short_record = {14, bad};
    int previous = logs;
    r8q_tee_log(&peer, &short_record);
    assert(logs == previous);
    elapsed = 180;
    check(ks, 7, "keystore2", "late", NULL);
    elapsed = 0;
    for (int i = 0; i < 47; i++) check(ks, 7, "keystore2", "fatal", "R8QKEYSTORE");
    check(ks, 7, "keystore2", "capped", NULL);
    for (int i = 0; i < 46; i++) check(km, 4, "samsung", ready, "origin=samsung ");
    check(km, 4, "samsung", ready, NULL);
    check(ks, 4, "keystore2", aidl, "origin=compat ");
    check("u:r:tee:s0", 6, "linker", "cannot locate symbol from daemon", "origin=qsee-daemon ");
}
'''

if __name__ == '__main__':
    source = (Path(sys.argv[1])/'net/unix/af_unix.c').read_text()
    start = source.index('enum r8q_log_source {')
    end = source.index('static int unix_dgram_sendmsg(', start)
    body = source[end:source.index('static int unix_stream_sendmsg(', end)]
    assert body.index('other = unix_find_other(') < body.index('r8q_tee_log(other, skb)') < body.index('sk_filter(other, skb)')
    assert 'if (!r8q_checked)' in body and body.count('r8q_tee_log(other, skb)') == 1
    with TemporaryDirectory() as temp:
        path = Path(temp)/'test.c'
        binary = Path(temp)/'test'
        path.write_text(STUBS+source[start:end]+TEST)
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(path),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
    print('Verified packet parsing, trusted sender, correct peer and capture bounds.')
