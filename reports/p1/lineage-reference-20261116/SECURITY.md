# Lineage security/config reference audit

Read-only audit against the actual P1r4 Vendor config capture, the tracked
source-baseline properties and the port's proposed fstab. No changes were made
to the shared port workspace, files on the phone, or published branches.

## Pinned references

- r8q 23.2: `27bf887e7cbcda29aa047bd4fcd1760e515cd921`
- sm8250-common 23.2: `7a4f1a3feaada10fef3d5afcc4f212817fcd4f84`
- r8q 24.0: `47316f913bd4684417442f7eb975ef1f280227d8`
- sm8250-common 24.0: `576897d7c84c391b326ebd8b109062e0219b3096`

Selected fetched texts are retained under this directory, separated by branch.

## Findings that prevent unsafe changes

1. **QTI Gatekeeper + Samsung MDFPP is intentional coexistence.** Common
   `common.mk` builds the Samsung MDFPP adapter while the proprietary common
   Vendor makefile also installs the QTI default Gatekeeper. The device
   manifest explicitly supports both `default` and `mdfpp`. Removing QTI on
   sight would remove a legitimate companion. The current real Vendor already
   has both declarations and an explicit MDFPP init interface.
2. **The current security selectors already match upstream.** Both branches
   use `ro.hardware.gatekeeper=mdfpp` and `ro.hardware.keystore=mdfpp`. The
   tracked baseline has those exact values. The current capture omitted root
   build.prop, so this establishes the reviewed baseline, not runtime values.
3. **The upstream Keymaster fix is a compiled adapter, not a property toggle.**
   Common `common.mk` builds `android.hardware.keymaster@4.0-service.samsung`
   backed by `libskeymaster4device`. The current Vendor has its stock Samsung
   binary explicitly configured as `IKeymasterDevice/default`; it separately
   advertises StrongBox. The upstream main manifest advertises default only.
   Replacing the stock service requires library/ABI/build validation. Removing
   StrongBox alone does not repair a failed default TEE and is not proposed.
4. **The common Keymaster policy is not missing wholesale.** Actual Vendor CIL
   lines 15631-15633 already grant Samsung Keymaster's QTI binder call and the
   SPCom/TEE listener property reads. Blindly appending the same .te permissions
   would not establish a fix. Published R2 fixes the proven root/context labels.
5. **The Lineage fstab is not compatible as a wholesale replacement.** Both
   branches use EROFS Vendor and FBEv2 with a metadata-encryption keydirectory.
   This port uses ext4 Vendor and legacy ICE. Moving that crypto configuration
   requires a separate migration/key/data decision; do not change it to silence
   early mount or service errors. The physical APNHLOS/modem firmware mounts
   and `firmware_file` contexts agree with the reviewed port.

## Android 17 branch differences

On 24.0, `configs/manifest.xml` moved to `vintf/manifest.xml`; its contents are
byte-identical. Gatekeeper adapter/rc and the Keymaster .te rules are unchanged.
r8q BoardConfig, device.mk and variant init are also unchanged in sampled files.

Material common changes: legacy ION build implementation enabled, removal of
`PRODUCT_ENABLE_UFFD_GC`, audio/C2 modernization and moving cache to first-stage
mount. These are build/hardware integration clues, not runtime property fixes
for the prebuilt HyperOS libraries. Parent/kernel and HAL audits own those paths.

Useful pinned upstream locations:

- [24.0 common.mk lines187-218](https://github.com/LineageOS/android_device_samsung_sm8250-common/blob/576897d7c84c391b326ebd8b109062e0219b3096/common.mk#L187): Gatekeeper, legacy ION and Samsung Keymaster selection.
- [24.0 vendor.prop lines160-168](https://github.com/LineageOS/android_device_samsung_sm8250-common/blob/576897d7c84c391b326ebd8b109062e0219b3096/vendor.prop#L160): MDFPP selectors.
- [24.0 fstab lines38-51](https://github.com/LineageOS/android_device_samsung_sm8250-common/blob/576897d7c84c391b326ebd8b109062e0219b3096/init/fstab.qcom#L38): EROFS, metadata encryption, first-stage cache and firmware mounts.
- [24.0 main manifest](https://github.com/LineageOS/android_device_samsung_sm8250-common/blob/576897d7c84c391b326ebd8b109062e0219b3096/vintf/manifest.xml#L29): explicit Gatekeeper/default+mdfpp and Keymaster/default.
- [23.2 MDFPP service.cpp](https://github.com/LineageOS/android_device_samsung_sm8250-common/blob/7a4f1a3feaada10fef3d5afcc4f212817fcd4f84/gatekeeper/service.cpp#L23): backend module determines instance registration.

## Concrete proposed guard

`proposed/tools/audit_r8q_security_reference.py` implements a read-only static
contract: reject changed/conflicting module selectors, a missing mandatory
default TEE, ambiguous init registrations, incompatible current filesystem or
crypto migration, and wrong/read-write firmware partition mounts. It accepts
valid QTI/MDFPP coexistence and records StrongBox without disabling it. It pins
both source branches and hashes the relevant config inputs.

`proposed/ci-r8q/tests/test_r8q_security_reference.py` contains seven behavioral
fixtures. All pass. Running the tool against the captured real Vendor configs,
tracked baseline build.prop and current candidate fstab also passes. The result
is `security-contract-final.json`; it deliberately does not claim runtime boot,
merged VINTF resolution or successful binary registration.

No new flashable runtime patch is justified by these configuration differences
alone. Retain R2 and use the kernel/ABI investigations for the next concrete fix.
