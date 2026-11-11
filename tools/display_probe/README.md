# Read-only composer dump probe — offline build review

The v4 shell diagnostic uses `lshal debug`, which calls `IBase::debug(fd, ...)`.
That is distinct from `IComposer::dumpDebugInfo()`. The AOSP composer reference
implements the latter without overriding the former, so a successful empty
`lshal debug` output does not prove there is no useful HWC debug dump.
The exact OEM binary may behave differently; no v4 HAL capture has been
received to settle that question.

This small client calls the existing binderized default composer's inherited
2.1 `dumpDebugInfo()` method, which returns the implementation's text dump.
It never calls `createClient`, opens a composer HAL implementation directly,
changes display modes/properties or sends an init restart request. HIDL composer
has only one client; making another client to query mode attributes could
interfere with SurfaceFlinger and is deliberately excluded.

Before lookup the client requires HWBINDER transport and an already registered
`android.hardware.graphics.composer@2.1::IComposer/default`. Lookup uses
`tryGetService("default", false)` without retry/wait. The service must be remote.
There remains a race: if the HAL disappears after the registered-service check,
hwservicemanager's lookup may request a lazy-service start. This code cannot
promise that no HAL can ever be started by the service manager. `getStub=false`
alone is also not a substitute for the transport check.

The program imposes an alarm after four seconds and caps its stdout, including
the status header, below 128 KiB. A diagnostic wrapper must still impose an
external timeout and output cap. The stdout cap limits saved/output data,
not the allocation performed while receiving the HIDL response. The program
must not be treated as a security boundary against a malicious composer.

Exit codes: `0` dump returned; `2` empty OEM dump; `3` truncated dump; `64`
unexpected arguments; `65` unexpected transport/local service; `69` service
unavailable or not already registered; `70` Binder/HIDL transaction failure;
`74` stdout write failure. A default SIGALRM termination commonly appears as
shell status `142`; external `timeout` may instead return `124`.

## Why the dump helps and what it can omit

The CAF SM8250 reference `DisplayBase::Dump()` prints the config count, active
config index, dimensions, DPI, minimum/maximum/current FPS and vsync period.
That can reveal invalid or inconsistent data behind SurfaceFlinger's fatal
refresh-mode selection. It does not necessarily list every HWC config/group
or optional VRR fields. An empty/incomplete OEM dump is a diagnostic result,
not a justification to invent FPS values or bypass SurfaceFlinger's checks.

## Build inputs and ABI

Run from a complete project checkout:

```sh
python3 -m unittest discover -s ci-r8q/tests -p test_composer_dump_build.py -v
python3 tools/display_probe/build_probe.py
```

The helper uses a fresh work/output directory and these pinned inputs:

* VNDK30 mirror `msft-mirror-aosp/platform.prebuilts.vndk.v30`, commit
  `3cb31a86382b624e1167c8c08b835873d9970f34`, sparse `arm64` checkout.
* Official Android NDK r27c Linux archive, revision `27.2.12479018`,
  663,987,688 bytes, published SHA1
  `090e8083a715fdb1a3e402d0763c388abb03fb4e` from the `android/ndk` r27c release.
  The helper also records the verified archive's SHA256 in its evidence.

The NDK supplies the compiler, Bionic sysroot and runtime builtins. HIDL,
utils and **platform libc++** headers/stubs come from the pinned VNDK30
snapshot. `-nostdinc++ -nostdlib++` avoids accidentally mixing NDK libc++'s
`std::__ndk1` ABI with platform `std::__1` used by the HIDL libraries.

The helper compiles a PIE for Android API30 ARM64, rejects unexpected ELF
architecture/interpreter/runtime search paths/NEEDED libraries, and confirms
that the HIDL lookup's undefined symbol uses the platform STL ABI. Libraries
from the VNDK snapshot are link-time inputs only. **No platform/vendor library
is bundled, installed or replaced.** Any compiler, linker or ELF inspection
failure retains the log and prevents claiming a successful build.

The proposed workflow only uploads offline evidence and the small ELF. It does
not publish a diagnostic ZIP or touch the ROM. The initial version has not yet
been compiled in CI or run on the phone. A build that passes ELF checks still
requires checking the actual phone's library availability/linker namespace and
SELinux execution context before integrating the executable under a reviewed
vendor diagnostic path. Running from `/data/local/tmp` can select a different
linker namespace and is not an equivalent test.

## Source basis

* `LineageOS/android_frameworks_native`, `lineage-24.0`,
  `cmds/lshal/Lshal.cpp`: `emitDebugInfo` calls `base->debug(...)`.
* `LineageOS/android_hardware_interfaces`, `lineage-18.1`,
  `graphics/composer/2.1/IComposer.hal` and
  `graphics/composer/2.1/utils/hal/include/composer-hal/2.1/Composer.h`:
  `dumpDebugInfo` is independent of `IBase::debug` and of `createClient`.
* `LineageOS/android_system_libhidl`, `lineage-18.1`,
  `transport/ServiceManagement.cpp`: non-retrying lookup and transport fallback.
* `LineageOS/android_hardware_qcom_display`, `lineage-18.1-caf-sm8250`,
  `composer/hwc_session.cpp`, `composer/hwc_display.cpp`,
  `sdm/libs/core/display_base.cpp`: read-only text dump contents.

These sources explain the probe design; they do not prove the proprietary
Samsung/Qualcomm implementation is byte-identical to the references.
