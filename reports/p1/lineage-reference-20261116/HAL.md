# HAL/vendor audit of the supplied Lineage references

Read-only reference analysis. No main project file or release was changed.
Exact branch pins are in `reference-pins.json`; selected source snapshots and
security prebuilt module declarations are saved beside this report.

## Security backend selection

The Samsung HIDL Keymaster service explicitly constructs
`skeymaster::CreateSKeymasterDevice(SecurityLevel::TRUSTED_ENVIRONMENT)` and
registers the default instance. It does not request StrongBox. See
`LineageOS/android_hardware_samsung` at
`336e05afdc6ea3b82660a7aaa03a7d30b233ca06`,
`hidl/keymaster/service.cpp` lines 40-49. The same service.cpp, Android.bp and
init rc are byte-identical at lineage-24.0 commit
`5a5a5d94b48ae64efaced925eb6f3f45201ed5b6`.

The build file links the selected Samsung implementation before
`libkeymaster4`, with an explicit comment that this permits injecting custom
libcrypto. `hidl/keymaster/Android.bp` lines 20-25 must retain that order.
Common device configuration selects `libskeymaster4device` (security agent
has the corresponding device-tree evidence).

The current real Vendor manifest advertises default+StrongBox, and has a
Samsung default service plus a QTI StrongBox service. Upstream common
manifest advertises Keymaster default only. This is a genuine configuration
difference, but deleting the optional StrongBox service does not repair a
missing mandatory TEE and would be a separate product-feature decision.
Current logs establish failures of both QTI StrongBox and QTI Gatekeeper;
they do not establish the factory path of the current Samsung default
Keymaster executable. Inspect that executable and actual dependencies before
replacing it.

Do **not** disable QTI Gatekeeper merely because the Lineage common product
also builds its MDFPP service. The pinned TheMuppets common vendor makefile
still copies QTI Gatekeeper init rc (line 20), includes its implementation
(line 232), `gatekeeper.mdfpp` (234), and its default executable (450).
Its QSEE service and daemon remain selected too (456, 475). The current
manifest's Gatekeeper default and MDFPP instances therefore are not by
themselves evidence of duplicate ownership. The MDFPP wrapper distinguishes
its instance using its backend's `is_mdfpp` extension.

## ABI constraints for a rebuilt wrapper

TheMuppets common Android.bp at lineage-23.2
`688e9c611ee3ea991990243234325468f9c88546` declares:

- `libskeymaster4device`: line 8292, including `libcrypto-v33`, HIDL Keymaster
  4.0/4.1, libkeymaster messages/portable, and Samsung helper libraries.
- `gatekeeper.mdfpp`: line 5106, including `libQSEEComAPI` and `libcrypto-v33`.
- QTI Gatekeeper implementation: line 5029, including libhidltransport and
  libhwbinder.
- QTI Keymaster implementation: line 7620, using unsuffixed `libcrypto`.

The corresponding module blocks are byte-identical in lineage-24.0 commit
`9991284b746f6cb7d0406bd4cbb28d86bfb451ee` even though other Android.bp
content changed. These generated prebuilt rules describe upstream-patched
binaries, not necessarily the current ColorOS Vendor's DT_NEEDED. Do not
copy patched blobs or claim that the current Vendor has libcrypto-v33 based
only on these rules. Verify actual exports and runtime library selection.

If the current service is proved to be a generic HIDL passthrough binary,
a narrow vendor implementation shim exporting HIDL_FETCH_IKeymasterDevice
and forwarding the exact Samsung TEE factory could avoid a full Android
build. That is conditional on actual ELF/factory-path evidence, symbol/ABI
validation and the preserved secure backend. It is not a fix if the service
already calls that factory directly. Plain NDK headers do not provide the
complete platform HIDL service source environment.

Renaming the rebuilt service to the Lineage `.samsung` executable name also
requires its correct entrypoint label. The supplied actual Vendor's
`vendor_file_contexts` lines 40-42 recognize the existing unsuffixed
Keymaster paths but contain no `.samsung` service rule. Reusing the reviewed
old executable path/label, or explicitly provisioning
`hal_keymaster_default_exec` and checking all matching rules, avoids adding
another init domain-transition failure.

## Firmware: keep the existing R2 repair

All keymaster/Gatekeeper/QSEE/IPA blob Git SHAs in TheMuppets common are
unchanged from the supplied 23.2 branch to 24.0. No updated signed firmware
fix is obtained by switching these branches.

In particular its IPA UC b00/b02 match the original generic Vendor code
(35,572-byte b02); b01/MDT/ELF contain the newer generic re-signing. Actual
device APNHLOS has a different 35,212-byte UC code and Samsung-rooted signing,
already verified for R2. Upstream reference firmware must not overwrite the
R2 device-stock source or remove its exact stock checks.

## NFC: complete interface migration, not an XML-only edit

The supplied r8q `device.mk` at `27bf887e7cbcda29aa047bd4fcd1760e515cd921`
lines 43-55 selects AIDL `android.hardware.nfc-service.nxp` and
`android.hardware.nfc-service.sec-sku`, with per-SKU NXP/SLSI config paths.
Lines 65-68 select NXP and Thales SKU secure-element services. These also
depend on additional repos beyond the eight supplied trees.

The legacy `android_hardware_samsung_nfc` tree at
`51a20495c915cabe0be8060f6cfc0ce194244d72` exports HIDL INfc@1.2/default.
The SLSI tree at `88490b4408246e6c10ef1a6942844796f66dee5e` exports AIDL
INfc/default; its 23.2 and 24.0 branches are exactly the same commit.
The legacy Samsung NFC repository has **no lineage-24.0 branch** (GitHub
branch lookup returns 404). Thus simply changing every clone to 24.0 fails.

The port currently selects HIDL 1.2 Samsung/NXP executables with matching
manifest entries and hardware selectors. Replacing only their rc/XML with
the AIDL references would advertise an interface the existing binaries do
not provide. A migration must carry binaries, dependencies, manifests,
SELinux, SKU selection and secure-element selection together. No NFC-specific
boot crash is established by the supplied logs, so this is lower priority
than restoring the TEE service path.

## Result and practical next steps

No additional standalone HAL config change is sufficiently proved to ship
from this sub-audit alone. The useful concrete changes are the parent/security
agent's Samsung Keymaster/MDFPP integration once the actual binary contracts
are verified, while keeping QTI default Gatekeeper where selected upstream.
The reference pins, ABI/link-order guard and entrypoint label check should
be part of the build/review evidence. Keep R2's authenticated device firmware
and metadata repairs, and validate another hardware boot before claiming
that the remaining LMKD or TEE failures are resolved.
