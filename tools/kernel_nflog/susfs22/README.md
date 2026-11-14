# SUSFS 2.2 / NFLOG full-kernel compile experiment

This is source work for an **offline compile**, not a boot image or release.
The requested SUSFS feature remains enabled. No no-SUSFS profile is accepted.
The original five r8q compatibility overlays, pinned compiler, protected config
comparison and linked NFLOG symbol checks remain active.

Reference: `JackA1ltman/NonGKI_Kernel_Build_2nd`, commit
`bf3b496646c77147444faff1cc55b58a07b7160a`,
`Patches/Patch/susfs_patch_to_4.19.patch` (SUSFS v2.2.0).
This revision supplies actual name lookup/readdir/map/AVC consumers and a real
deferred SUS_PATH worker missing from the earlier incomplete reference. It does
not add the conflicting ReSukiSU manual exec/SELinux hooks. The relevant
KernelSU integration remains pinned at sKernelSU `7d46da2ae166570c14b5336a5f5fe3336aa99f07`.
The reference is adapted specifically to canonical r8q kernel commit
`a265508933bbecb682e45e3b956d95bf4426d60b`.

`pins.json` records the reference and exact before/after hashes for 21 paths.
Three paths are genuine new source/header files. The derived patch must apply
without fuzz to the exact source; a mismatched existing/new file is rejected.
Canonical `security/selinux/avc.c` was independently bound to upstream Git blob
`b5931072a1e7164802dde9301b94ded8408f1f9e` (33,360 bytes).

Adaptations preserve this tree's fs_context mount API, mmap_read_lock/pagewalk
API, two-argument access_ok, and existing libperfmgr redirect fallback. The
newuname hook uses only `struct new_utsname`; old ABI structures are untouched.
Explicit SUSFS uname settings take precedence over the existing process-specific
fake-release adjustment. The reference's erroneous `version="default"` handling
now copies the real UTS version; the custom-version copy is null-terminated.

Mount ID ownership fixes beyond the reference:

* A borrowed ID is marked immediately during allocation, before any later
  clone operation can fail and call its cleanup path.
* A clone receiving a newly allocated ID clears an inherited borrowed-ID flag;
  only a clone actually borrowing the old ID restores that flag.
* `mnt_free_id` skips borrowed IDs. Namespace-copy intent is propagated.

`test_ownership.py` extracts the actual patched ownership flag definition,
free function, allocation marker and clone statements, compiles them with
focused host stubs and exercises normal/new/borrowed IDs plus early error
cleanup. This does not execute the kernel on the host. The memory-access hook
also rechecks the VMA at each new address rather than caching the first VMA
across reads that cross mapping boundaries.

`compile_experiment.py` combines the original overlay with this patch and
checks every original/resulting file, exact tracked changes and the three new
untracked files. A full link must define real SUSFS core/API/worker symbols as
well as NFLOG. Artifacts remain explicitly unflashable; boot/dtbo compatibility,
SUSFS runtime semantics and hardware behavior still require review/testing.
The existing production boot packager does not accept this new source record.

Kernel-derived source retains the kernel's GPLv2 license; the full license is
included in `../upstream-current/COPYING`. This README records the reference
and local adaptations; it does not replace upstream copyright notices.

The second full compile built the SUSFS/namei/namespace/AVC objects and reached
the MMC driver. Its direct internal `__WARN_printf` call is now the public
`WARN(1, ...)` API, which is valid with CONFIG_BUG both enabled and disabled.
The existing timeout completion, MMC event log and power-register dump are
unchanged. This additional source repair is included in the pinned 21 paths.
