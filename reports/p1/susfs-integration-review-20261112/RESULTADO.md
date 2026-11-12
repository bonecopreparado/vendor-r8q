# SUSFS remains required; no replacement kernel is ready

The user explicitly selected keeping SUSFS on 11 November. The proposed
`--without-susfs` experiment was not executed or published. The previously
distributed boot image remains unchanged.

## Confirmed compile repairs

The exact canonical kernel is
`notkernel-oss/not_samsung.sm8250-4.19@a265508933bbecb682e45e3b956d95bf4426d60b`.
The reviewed source overlay now contains five files: mq-deadline, zram,
MAX77705, cpumask.h and RMNET SHS. Original/resulting bytes and patch hashes
are pinned in `tools/kernel_nflog/current_compat.py`.

The latest completed kernel build, run 42939649373, passed configuration guards
and compiled the earlier corrected paths. It exposed RMNET's use of a removed
CPU-isolation accessor and the absent SUSFS integration. The RMNET correction
restores access to the real mask still defined/exported by kernel/cpu.c, keeps
online/RPS/destination checks, and fixes a structure passed to a scalar debug
format. Four new host tests and nine existing source-overlay tests pass. They
exercise the actual extracted source functions, including single-CPU and SMP
configurations. They do not establish a successful kernel link or phone boot.

## Why a header is insufficient

Pinned sKernelSU commit `7d46da2ae166570c14b5336a5f5fe3336aa99f07` calls real
SUSFS operations when CONFIG_KSU_SUSFS is enabled. The canonical kernel does
not contain include/linux/susfs.h or fs/susfs.c. Its normal build recipe does
not supply them. A fabricated header, empty functions or disabling the feature
would not preserve the requested behavior.

The inspected SUSFS 2.2 reference is
`FebriCahyaa/ci-build@fe00899748e93b3e12cfbb3b317e3902b528617b`,
`patches/root-manager/resukisu/4.19/susfs-0101-susfs-v2.2.0-backport.patch`.
Its fetched-content SHA256 is
`8cae0e456197ba0d685e7d85ee19305fc85695b4661153691bcc92449f095bf6`.
An unmodified application check fails in eight files. Adapting context lets a
scratch candidate apply, but does not make that candidate complete or correct:

- Manual exec/open and SELinux hooks target a different root integration and
  conflict with the pinned KSU syscall-table implementation/private state.
- The candidate has SUS_PATH declarations without effective lookup filtering,
  and lacks required modern directory enumeration and map-reporting consumers.
- Mount-namespace flag propagation and borrowed mount-ID ownership are
  incomplete. Freeing an ID that the clone does not own requires correction,
  rather than accepting compilation as proof of valid behavior.
- Deferred SUS_PATH work and AVC-spoof consumers still require real integration.

These are reasons to keep this scratch candidate out of the production overlay.
No SUSFS reference patch has been installed into a published kernel or applied
to a tester's phone. Older inspected SUSFS sources also lack the sdcard monitor
API used by this KSU pin; changing versions needs an explicit compatibility
review. A displayed version string or enabled Kconfig option does not prove
that the corresponding hooks work.

## Available next device evidence

BOOTDIAG V5 is available at
https://github.com/bonecopreparado/vendor-r8q/releases/tag/r8q-bootdiag-v5-2-1 .
It keeps the existing kernel/SUSFS and adds a bounded native composer dump plus
a phone-only recovery collector. CI run 43204717476 passed 28 mksh fixtures,
the pinned ARM64 build, ELF checks, inventory reporting and exact ZIP attestation.
The new native executable and recovery collector still need a real OrangeFox
test. These diagnostics address the missing HAL evidence behind SurfaceFlinger's
refresh-mode abort; they are separate from the unresolved NFLOG kernel change.

Next kernel work must complete and review the SUSFS consumers and ownership
rules, then link the full kernel with the guarded shipped feature configuration.
No successful Android boot or new flashable kernel is claimed.
