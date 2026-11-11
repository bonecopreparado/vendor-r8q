// SPDX-License-Identifier: Apache-2.0
// Read-only HIDL diagnostic. Never create a second composer client.
#include <android/hardware/graphics/composer/2.1/IComposer.h>
#include <android/hidl/manager/1.0/IServiceManager.h>
#include <hidl/ServiceManagement.h>

#include <algorithm>
#include <cerrno>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <string>
#include <unistd.h>

using android::hardware::graphics::composer::V2_1::IComposer;
using android::hidl::manager::V1_0::IServiceManager;
using android::hardware::hidl_string;
using android::hardware::hidl_vec;

namespace {
constexpr size_t kStdoutLimit = 128 * 1024;
constexpr size_t kBodyLimit = kStdoutLimit - 256;
constexpr unsigned kDeadlineSeconds = 4;
constexpr const char* kRegisteredName =
    "android.hardware.graphics.composer@2.1::IComposer/default";

int fail(const char* stage, int result) {
    std::fprintf(stderr, "R8QCOMPOSER_ERROR stage=%s exit=%d\n", stage, result);
    return result;
}

bool writeAll(const char* bytes, size_t length) {
    while (length) {
        const ssize_t count = ::write(STDOUT_FILENO, bytes, length);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) return false;
        bytes += count;
        length -= static_cast<size_t>(count);
    }
    return true;
}
}  // namespace

int main(int argc, char**) {
    if (argc != 1) return fail("unexpected-arguments", 64);
    // The wrapper must impose its own timeout too. A hung synchronous Binder
    // transaction must not keep a boot diagnostic process alive indefinitely.
    ::signal(SIGPIPE, SIG_IGN);
    ::alarm(kDeadlineSeconds);

    auto manager = android::hardware::defaultServiceManager();
    if (manager == nullptr) return fail("hwservicemanager-unavailable", 69);

    auto transport = manager->getTransport(IComposer::descriptor, "default");
    if (!transport.isOk()) return fail("transport-query", 70);
    if (static_cast<IServiceManager::Transport>(transport) !=
        IServiceManager::Transport::HWBINDER) {
        return fail("binderized-transport-required", 65);
    }

    bool registered = false;
    auto listed = manager->list([&](const hidl_vec<hidl_string>& names) {
        for (const auto& name : names) {
            if (name == kRegisteredName) registered = true;
        }
    });
    if (!listed.isOk()) return fail("registered-list-query", 70);
    if (!registered) return fail("composer-not-already-registered", 69);

    // Non-retrying lookup, no getService wait and no getStub/passthrough request.
    // A service could disappear after list(); hwservicemanager can then request
    // a lazy-service start during get(). This race cannot be excluded here.
    auto composer = IComposer::tryGetService(std::string("default"), false);
    if (composer == nullptr) return fail("composer-lookup", 69);
    if (!composer->isRemote()) return fail("remote-composer-required", 65);

    bool called = false;
    bool writeOk = true;
    size_t originalBytes = 0;
    size_t writtenBytes = 0;
    auto result = composer->dumpDebugInfo([&](const hidl_string& dump) {
        if (called) {
            writeOk = false;
            return;
        }
        called = true;
        originalBytes = dump.size();
        writtenBytes = std::min(originalBytes, kBodyLimit);
        char header[256];
        const int headerLength = std::snprintf(
            header, sizeof(header),
            "R8QCOMPOSER_DUMP version=1 interface=2.1 instance=default "
            "original_bytes=%zu body_bytes=%zu truncated=%d\n",
            originalBytes, writtenBytes, originalBytes > writtenBytes ? 1 : 0);
        writeOk = headerLength > 0 && static_cast<size_t>(headerLength) < sizeof(header)
            && writeAll(header, static_cast<size_t>(headerLength))
            && writeAll(dump.c_str(), writtenBytes);
    });
    if (!result.isOk()) return fail("dump-transaction", 70);
    if (!called) return fail("dump-callback-absent", 70);
    if (!writeOk) return fail("stdout-write", 74);
    if (originalBytes == 0) return fail("empty-hal-dump", 2);
    if (originalBytes != writtenBytes) return fail("dump-truncated", 3);
    return 0;
}
