# Offline NFLOG kernel source plan

This folder prepares a reviewed source overlay only. It does not compile a
kernel, open a phone, write a kernel image, change boot sections or flash a
partition. **A replacement kernel is currently blocked by missing provenance
for the shipped KernelSU integration.** No config guard may be relaxed to
get a build past that blocker.

## Exact inputs and provenance gap

- Kernel base: `Lazy-Encrypted/not_samsung.sm8250-4.19`, commit
  `a1182f3932cfefaa9f262135290ecf58bd19c6aa` (`fs: update ksu hooks`). Its
  Makefile version 4.19.325, `localversion-st=-st11-rc`, and defconfig
  `CONFIG_LOCALVERSION="-not:A.06"` match the running kernel's release.
- Audited raw kernel SHA256:
  `d64c9c8856b7a30acb0fcc262d931f48a062a2077fcd9357a1974667aa37880e`.
  It is an uncompressed ARM64 Image of 37,652,496 bytes. Source P1 boot SHA256:
  `4283ccbecbf3087bbd520dce1e50e5e449b1f70c4d959e8ee7f24b3ebfde9301`.
- Exact embedded shipped config SHA256:
  `ce4b98d368058f4d5fd2c5c3380d53813a10f57c72544838548c61759bceab4a`.
  The extraction/input identity was verified in project CI run 42430975057.
  The recovery kernel is different and must not supply this baseline config.
- Shipped config has `CONFIG_MODULES=n`, `CONFIG_DEBUG_KERNEL=n`,
  `CONFIG_NETFILTER_NETLINK=y`, with the NFLOG backend/target disabled. An
  `nfnetlink_log.ko` from another kernel cannot repair a kernel with modules
  disabled. No module mixing is proposed.
- Shipped config also enables KernelSU, KSU extras, allowlist workaround and
  multiple SUSFS features. Android kernel logs identify KSU version 33333,
  branch `susfs-rksu-master`, SUSFS v2.0.0; **they provide no exact KSU commit**.
  The public base has KSU hook references and `fs/susfs.c`, but no root-level
  gitlink/.gitmodules, no KernelSU directory/integration in the inspected
  driver/security/kernel paths or Kconfig entry points. Its `build.sh`,
  `not.sh` and `.github/workflows/build.yml` contain no KSU setup/checkout.
  `.gitlab-ci.yml` only imports generic Linux CIP pipelines. A branch/version
  hint shared by multiple forks does not identify the exact built source.

Before a release build, obtain the full source/build recipe from the kernel
maintainer: exact KSU repository and commit, integration/setup patch bytes,
any additional uncommitted kernel changes and the original generated config.
Do not silently drop `CONFIG_KSU*`, replace them with a current branch or
disable SUSFS to make the build succeed. A strict olddefconfig comparison
should expose the missing symbols. Config parity is necessary but does not
prove the reconstructed source is otherwise identical.

## Toolchain pin candidate

The kernel banner and embedded config name Android Clang build 11889484,
version 18.0.1 based on r522817. A matching public prebuilt revision is:

- Official repository:
  `https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86`
- Readable mirror:
  `https://github.com/msft-mirror-aosp/platform.prebuilts.clang.host.linux-x86`
- Commit: `5a1f5d58aa30f70047f18cf5fc077a3dd391589c`.
- Directory: `clang-r522817`. At this revision `BUILD_INFO` has build ID
  11889484 and `AndroidVersion.txt` has 18.0.1 based on r522817.
- `bin/clang-18`: Git blob `5f9bb95cd5b0c3c7ff9f7579af87b54ed4395190`,
  135,214,616 bytes. This is an identity candidate; executable SHA256 has not
  yet been measured locally. Clone at the exact commit with Git modes and
  symlinks preserved, verify its objects and record SHA256 for every actually
  executed tool, then verify `clang --version` and `ld.lld --version`.

The original script instead downloads an unpinned GitLab branch `18` of
ThankYouMario's standalone Clang repository. The GitHub mirror of that
standalone repository currently has only `master`, so a moving-branch clone
is not sufficient provenance. The original script's make arguments are:

```text
O=out ARCH=arm64 CC=clang LD=ld.lld AS=llvm-as AR=llvm-ar NM=llvm-nm
OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump STRIP=llvm-strip
CROSS_COMPILE=aarch64-linux-gnu- CROSS_COMPILE_ARM32=arm-linux-gnueabi-
LLVM=1 LLVM_IAS=1
```

No `CLANG_TRIPLE` is set by that script. It uses these defconfig fragments:
`vendor/kona-not_defconfig vendor/samsung/kona-sec-not.config
vendor/samsung/r8q.config vendor/not/no_werror.config vendor/not/no_lto.config`.
Those identify the recipe, but a guarded rebuild must start from the audited
**embedded config**, not regenerate a guessed config from those fragments.
GNU cross tools and host-tool versions must also be recorded; the old script
only installs `gcc-aarch64-linux-gnu` and does not pin those packages.

For a baseline reproducibility experiment the observed build metadata is
`KBUILD_BUILD_USER=runner`, `KBUILD_BUILD_HOST=runnervmmtnos`,
`KBUILD_BUILD_VERSION=1`, timestamp `Sat Jan 17 21:34:11 -03 2026`.
Use fixed recorded build metadata and SOURCE_DATE_EPOCH when comparing
baseline binaries. A future patched build should be identified honestly as
modified, for example with a recorded `LOCALVERSION=-r8q-nflog1`; this does
not require changing the `.config` or boot command line. Exact build
reproduction is not yet established, and that suffix does not resolve the
missing external-source provenance.

## Targeted source changes

Changing only NFLOG `.config` entries is insufficient in this kernel base:

1. Kbuild excludes `nf_log.o` and `nfnetlink_log.o` unless DEBUG_KERNEL is set.
2. `xt_NFLOG.o` is behind a different `CONFIG_KERNEL_DEBUG` guard.
3. `nf_log.h` turns packet/trace logging into no-op inline stubs without
   DEBUG_KERNEL. Its dormant real `nf_log_trace` prototype lacks a semicolon.
4. `nf_internals.h` makes `netfilter_log_init()` a no-op under the same guard.

The overlay admits the real core, backend and target when NFLOG is enabled,
fixes that prototype terminator, and keeps unrelated logging/debug gates.
It never enables DEBUG_KERNEL. The exact original file sizes, SHA256 and
Git blob identities are pinned in `source-pins.json`. Copies under `upstream/`
retain their GPL-2.0 SPDX headers; `upstream/COPYING` contains GPLv2.

The config planner enables only `NETFILTER_NETLINK_LOG` and
`NETFILTER_XT_TARGET_NFLOG`; their NETFILTER_NETLINK dependency is already
built in for the real shipped config. The allowlist includes that dependency
only so its requirement can be verified. All other symbol values must remain
unchanged, including DEBUG_KERNEL, MODULES, KSU/SUSFS, FTRACE and SELinux.

The future guarded flow, after the missing source is resolved, is:

```text
python3 tools/kernel_nflog/prepare.py prepare --source EXACT_CLEAN_CHECKOUT \
  --shipped-config EXTRACTED_SHIPPED_CONFIG \
  --shipped-config-sha256 ce4b98d368058f4d5fd2c5c3380d53813a10f57c72544838548c61759bceab4a \
  --output NEW_EXTERNAL_OVERLAY_DIRECTORY
```

This produces three source overlay files, `kernel.config` and `report.json`
without modifying the checkout. Its current report explicitly has
`build_ready=false`. Do not execute a kernel build from that report.

Once source parity is proven, apply only those three source changes to a
separate build checkout, copy the config into a fresh external `O=` directory,
run `olddefconfig` using the pinned actual compiler, and run:

```text
python3 tools/kernel_nflog/prepare.py verify-config \
  --shipped-config EXTRACTED_SHIPPED_CONFIG --generated-config BUILD_CONFIG
```

Fail on any symbol delta outside the three NFLOG/dependency names. Build
only raw `Image`/`vmlinux`, not dtbo or combined DTBs, and record full logs.
Run the same config check on `.config` extracted back from the built Image.
Use `llvm-nm --defined-only vmlinux` and `verify-symbols --nm NM_OUTPUT` to
require linked core, backend and NFLOG target/init symbols; enabled config
values alone do not prove Kbuild included them. Retain System.map, config,
source diff, tool hashes and all image hashes as build evidence.

Use the separate reviewed boot-repack helper to preserve ramdisk, cmdline,
DTB, DTBO and non-kernel boot sections. Do not use the upstream AnyKernel ZIP
for this project: its script unconditionally writes vbmeta and dtbo. No boot
success or even a compiled kernel is claimed by this source plan.

## Verification performed here

The focused host tests evaluate actual GNU Make variable expansion and C
preprocessor branches, check pinned input/hash/path rules, config allowlists,
source preservation, required symbol rejection and KSU-loss rejection.
They perform no kernel compilation, mounting, flashing or Android execution.
