# The ueventd bridge clears the first userspace blocker

The privately received logs-v4-completo.zip contains three captures. N9PDXU
is the earlier failed-Keymaster baseline; s9h2B9 and wh7rSp are later boots.
The installed canonical import is byte-identical to the reviewed 150-byte
bridge, SHA256 a62d17938582b2205610749a6ede6989b173aa08e6e995ebefc1ff7339ee21b8.
The unchanged payload alone does not identify which installer revision ran.

In both new captures, Keymaster registers, shared-secret negotiation succeeds,
userdata is mounted and user0 filesystem/key preparation completes. Qseecom
open failures and spcom EACCES are absent. The previous encryptFstab wait is
therefore cleared. Reformatting data is not a justified response to the new
stage. No successful Android UI boot is claimed.

## Two later failures

SurfaceFlinger repeatedly aborts while constructing available refresh-rate
modes: no modes match even after the render range is ignored. Its recorded
initial policy already spans zero through FLT_MAX. The latest kernel segment
launches SurfaceFlinger at 14.421 s and every approximately five seconds
afterward. A prior segment continues such restarts beyond 319 s. No actual
zygote/app_process exec is recorded. The latest attempt ends after 38.859 s,
and its bootloader summary records a manual seven-second reset-key hold.

The reference RefreshRateSelector implementation filters HWC modes by
resolution, DPI, group and peak FPS before generating frame-rate modes.
Actual HWC mode fields are absent from the current warning-only capture.
Changing a frequency threshold or disabling frame-rate override is not yet
supported by those data; that would not repair every invalid-mode cause.
The reference is LineageOS/android_frameworks_native lineage-24.0, not proof
that Xiaomi's proprietary binary is identical.

Separately, ip6tables-restore rejects StrictController NFLOG rules; netd then
reports failure to initialize iptables rules. The FORTIFY destroyed-mutex
abort occurs during exit/destructor cleanup after that failure. It is not
evidence to bypass libc mutex checks. Neither a firewall flush nor an unrelated
BPF/property bypass is a correction for the demonstrated missing NFLOG target.

## Exact boot/kernel input audit

CI run 42430975057 reproduces the exact shipped boot SHA256 4283cc...fde9301
from the pinned public 931453816-byte r8q source ZIP, without reconstructing
vendor/odm or downloading the HyperOS donor. Its raw ARM64 kernel SHA256 is
d64c9c8856b7a30acb0fcc262d931f48a062a2077fcd9357a1974667aa37880e.
Embedded IKCONFIG SHA256 is ce4b98d368058f4d5fd2c5c3380d53813a10f57c72544838548c61759bceab4a.
MODULES and DEBUG_KERNEL are disabled; NETFILTER_NETLINK is built in while
NETFILTER_NETLINK_LOG and NETFILTER_XT_TARGET_NFLOG are disabled. A separately
loaded module is therefore not a repair for this shipped kernel.

The matching base source at a1182f3932cfefaa9f262135290ecf58bd19c6aa also
gates required NFLOG build/header paths behind debug symbols and contains a
dormant prototype typo. The prepared offline overlay addresses those exact
paths, retains DEBUG_KERNEL=n and changes only the two missing NFLOG symbols.
Host Make/C-preprocessor tests exercise those branches; a strict config check
rejects dropping KernelSU/SUSFS settings to force a build through.

Kernel reproduction also requires the exact external KernelSU integration.
The first inspected public source/recipes omit that source despite the
shipped config enabling it. The user has since supplied the canonical
notkernel-oss repository for further inspection. No replacement kernel is
compiled or published from an incomplete integration. Full source/build
pins remain required, including any additional uncommitted build changes.

## Diagnostic v4

v4 is a one-file atomic runtime upgrade requiring the exact existing v3 rc
and script on the reviewed vendor. It keeps that asynchronous init rc and
the ROM, kernel, display properties, firewall and keys unchanged. A separate
metadata namespace preserves all previous v3 evidence and retains at most
three new private captures, each below 2 MiB, requiring at least 12 MiB free.

Independent probes begin at +8 and +20 seconds after service start. They
list binderized HAL interfaces, select only an exact whitelisted composer
instance, then request its bounded debug dump. A separately bounded, named
AIDL fallback never dumps all services or restarts a HAL. The capture also
reads selected display properties/sysfs and the Android kernel config,
modules and netfilter targets. Missing sources/tools/timeouts have explicit
status files; a missing dump does not prove the HAL is absent. OEM release
dumps can still omit fields, so hardware evidence remains necessary.

Targeted logcat filters replace the broad warning filter which previously
filled with DSP errors. Process probes select by executable, catching vold
even when its main thread is renamed, and omit private vdc arguments.
Logcat itself is bounded to 90 seconds/1000 lines; that is not a hard service
wall-clock deadline. Allow approximately two minutes for collection.
RESTORE-V3 restores the exact older runtime, preserving every saved log.

Twelve runtime and seven upgrade tests pass locally. The source plan has ten
host tests and boot-preservation helper six tests. Release CI reruns these
35 focused tests using real mksh for the shell fixtures before publication.
These checks do not execute the OEM init, HAL or Android kernel on a phone.
No raw private logs are included in the repository or published assets.
