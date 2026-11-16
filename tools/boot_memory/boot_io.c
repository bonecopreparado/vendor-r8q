/* SPDX-License-Identifier: MIT
 * Exact-size r8q boot I/O. This helper never repacks images or changes mappings.
 */
#define _GNU_SOURCE
#define _FILE_OFFSET_BITS 64
#include <errno.h>
#include <fcntl.h>
#include <linux/fs.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define BOOT_BYTES ((off_t)67108864)
#define BUFFER_BYTES ((size_t)1048576)
#define BUFFER_ALIGN ((size_t)4096)

#ifdef R8Q_TEST_REGULAR_FILES
static const char build_marker[] = "R8Q_BOOTIO_TEST_REGULAR_FILES_V1";
#define FRESH_FLAGS 0
#else
static const char build_marker[] = "R8Q_BOOTIO_PRODUCTION_BLOCK_ONLY_V1";
#define FRESH_FLAGS O_DIRECT
#endif

static void fail(const char *what)
{
    int saved = errno;
    fprintf(stderr, "r8q-bootio: %s: %s\n", what, strerror(saved));
    exit(1);
}

static void reject(const char *what)
{
    errno = EINVAL;
    fail(what);
}

static int open_regular(const char *path, int flags, int require_boot_size,
                        struct stat *record)
{
    int fd = open(path, flags | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) fail("open regular source/backup");
    if (fstat(fd, record) < 0) fail("stat regular source/backup");
    if (!S_ISREG(record->st_mode)) reject("expected a regular file");
    if (require_boot_size && record->st_size != BOOT_BYTES)
        reject("regular image must be exactly 67108864 bytes");
    return fd;
}

static int open_boot(const char *path, int flags, struct stat *record)
{
    uint64_t length = 0;
    int fd = open(path, flags | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) fail("open boot device");
    if (fstat(fd, record) < 0) fail("stat boot device");
    if (S_ISBLK(record->st_mode)) {
        if (ioctl(fd, BLKGETSIZE64, &length) < 0) fail("boot size ioctl");
#ifdef R8Q_TEST_REGULAR_FILES
    } else if (S_ISREG(record->st_mode)) {
        length = (uint64_t)record->st_size;
#endif
    } else {
        reject("boot target must be a block device");
    }
    if (length != (uint64_t)BOOT_BYTES)
        reject("boot device must be exactly 67108864 bytes");
    return fd;
}

static unsigned char *buffer_alloc(void)
{
    void *buffer = NULL;
    int rc = posix_memalign(&buffer, BUFFER_ALIGN, BUFFER_BYTES);
    if (rc) {
        errno = rc;
        fail("aligned buffer allocation");
    }
    return buffer;
}

static void pread_exact(int fd, unsigned char *buffer, size_t length,
                        off_t offset)
{
    size_t done = 0;
    while (done != length) {
        ssize_t count = pread(fd, buffer + done, length - done,
                              offset + (off_t)done);
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) fail("read image/device");
        if (!count) {
            errno = EIO;
            fail("unexpected end of image/device");
        }
        done += (size_t)count;
    }
}

static void pwrite_exact(int fd, const unsigned char *buffer, size_t length,
                         off_t offset)
{
    size_t done = 0;
    while (done != length) {
        ssize_t count = pwrite(fd, buffer + done, length - done,
                               offset + (off_t)done);
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) fail("write boot device");
        if (!count) {
            errno = EIO;
            fail("zero-byte boot write");
        }
        done += (size_t)count;
    }
}

static void stdout_exact(const unsigned char *buffer, size_t length)
{
    size_t done = 0;
    while (done != length) {
        ssize_t count = write(STDOUT_FILENO, buffer + done, length - done);
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) fail("write fresh-read output");
        if (!count) {
            errno = EIO;
            fail("zero-byte fresh-read output");
        }
        done += (size_t)count;
    }
}

static void flush_boot(int fd, const struct stat *record)
{
    if (fdatasync(fd) < 0) fail("boot fdatasync");
    if (S_ISBLK(record->st_mode)) {
        if (ioctl(fd, BLKFLSBUF, 0) < 0) fail("boot flush/invalidate ioctl");
    }
}

static void close_checked(int fd)
{
    /* Linux may already have closed the descriptor on EINTR: do not retry. */
    if (close(fd) < 0) fail("close file/device");
}

int main(int argc, char **argv)
{
    struct stat source_stat, target_stat;
    unsigned char *buffer;
    int source, target;
    off_t offset;
    if (argc == 2 && !strcmp(argv[1], "--version")) {
        puts(build_marker);
        return 0;
    }
    if (argc == 3 && !strcmp(argv[1], "--check")) {
        target = open_boot(argv[2], O_RDONLY, &target_stat);
        close_checked(target);
        return 0;
    }
    if (argc == 3 && !strcmp(argv[1], "--sync-file")) {
        source = open_regular(argv[2], O_RDWR, 0, &source_stat);
        if (fdatasync(source) < 0) fail("backup fdatasync");
        close_checked(source);
        return 0;
    }
    if (argc == 3 && !strcmp(argv[1], "--sync-directory")) {
        source = open(argv[2], O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
        if (source < 0) fail("open backup directory");
        if (fsync(source) < 0) fail("backup directory fsync");
        close_checked(source);
        return 0;
    }
    if (argc == 3 && !strcmp(argv[1], "--read")) {
        target = open_boot(argv[2], O_RDONLY | FRESH_FLAGS, &target_stat);
        buffer = buffer_alloc();
        for (offset = 0; offset < BOOT_BYTES; offset += (off_t)BUFFER_BYTES) {
            pread_exact(target, buffer, BUFFER_BYTES, offset);
            stdout_exact(buffer, BUFFER_BYTES);
        }
        free(buffer);
        close_checked(target);
        return 0;
    }
    if (argc == 4 && !strcmp(argv[1], "--write")) {
        source = open_regular(argv[2], O_RDONLY, 1, &source_stat);
        target = open_boot(argv[3], O_RDWR, &target_stat);
        if (source_stat.st_dev == target_stat.st_dev &&
            source_stat.st_ino == target_stat.st_ino)
            reject("source and target must be distinct");
        buffer = buffer_alloc();
        for (offset = 0; offset < BOOT_BYTES; offset += (off_t)BUFFER_BYTES) {
            pread_exact(source, buffer, BUFFER_BYTES, offset);
            pwrite_exact(target, buffer, BUFFER_BYTES, offset);
        }
        if (fstat(source, &source_stat) < 0) fail("recheck source size");
        if (source_stat.st_size != BOOT_BYTES)
            reject("source size changed during boot write");
        flush_boot(target, &target_stat);
        free(buffer);
        close_checked(source);
        close_checked(target);
        return 0;
    }
    fprintf(stderr, "usage: r8q-bootio --version | --check BLOCK | --read BLOCK | --write IMAGE BLOCK | --sync-file FILE\n");
    return 2;
}
