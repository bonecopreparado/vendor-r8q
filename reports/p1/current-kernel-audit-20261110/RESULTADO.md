# Current canonical kernel experiment — 10 November 2026

The supplied canonical source is usable for a separate kernel upgrade
experiment. It is not a reproduction of the shipped Not A.06 kernel.
Source, all three submodules and Android clang are pinned by commit in
`tools/kernel_nflog/audit_current.py`. The shipped configuration is recovered
from the exact previously distributed boot image and pinned by SHA256.

Configuration audit run 42804124525 completed successfully. The upstream
r8q profile changes 720 semantic configuration entries, including NFC, virtual
address size and SUSFS choices. The experiment instead starts with the shipped
configuration, explicitly enables the NFLOG backend and target, keeps existing
hardware/root/SELinux/compatibility settings guarded, and preserves the old
LZ4 zram choice using the current tree's new backend selectors.

## Build failures and narrow corrections

Run 42806727990 stopped before compilation: ARM64 relocation support forces
RELR, whose Kconfig selection also forces Clang LTO. Disabling those entries
cannot survive olddefconfig with this source and linker. The build now uses
the supported ThinLTO choice and bounds link worker counts to two; protected
relocation and address randomization remain enabled.

Run 42808264919 passed all generated-configuration guards and reached real
compilation. It failed assembling the optional BPF debug preloader because
`kernel/bpf/preload/bpf_preload_umd` was never generated. The backported
preloader Makefile uses a `userprogs` build mechanism absent from this 4.19
tree. Its libbpf build is also incomplete, so merely ordering make targets
would not fix it.

Only the newly introduced `CONFIG_BPF_PRELOAD_UMD` debug iterator component is
disabled. Existing BPF syscall/JIT/LSM/cgroup/classifier/action/preload and
usermode-driver configuration entries are protected against changes. This
does not disable Android's network BPF loader or waive NFLOG symbol checks.

The compiler cache stores only the exact verified compiler checkout, outside
fresh kernel/source/output directories. Cache hits are reverified and copied
before use. No previous generated config, kernel object or image is reused.

Run 42935655781 passed configuration guards with the debug UMD disabled and
compiled further. It exposed two incomplete source backports: mq-deadline
still used the old two-argument merge API, and zram writeback called modern
block-device/BIO APIs absent from this 4.19 tree. Two exact, hashed patches
adapt these callers. mq-deadline releases the entire merge list after dropping
its spin lock. Zram retains exclusive backing-device ownership, initializes
device/operation fields through the actual 4.19 API and propagates allocation
failure before chaining a parent BIO. Scheduler and writeback stay enabled.
The build accepts only those two tracked changes to the pinned resulting
bytes. Every other source/submodule change remains an error.

## Remaining device evidence

The latest private logs show that the ueventd bridge lets Keymaster and
userdata preparation proceed. They then show two separate failures: netd's
NFLOG rule rejection and repeated SurfaceFlinger refresh-mode construction
aborts. A kernel providing NFLOG addresses the demonstrated networking
dependency; it does not establish that display initialization will succeed.
BOOTDIAG v4 is available to collect the missing composer modes and targeted
Android logs. No additional Format Data is justified by the current evidence.

The current source deliberately emits ARM64 Image `text_offset=0`, whereas
the shipped Image uses `0x80000`. A successful raw Image build alone does not
validate the old DTB, ramdisk or Samsung bootloader loading path. No Image
header is rewritten to hide that difference, and this workflow produces
offline review artifacts rather than a flashable update.

No phone has booted this experimental kernel. Compilation, packaging and an
actual hardware boot are separate validation steps.
