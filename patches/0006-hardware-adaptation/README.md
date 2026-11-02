# Isolated hardware adaptation candidates

Nothing here was flashed or applied to an image by these tools. Root-owned
image generation must preserve file ownership, mode and SELinux labels and
record new partition hashes. These are specific configuration fixes, not a
claim that NFC, charging, brightness or 120 Hz works on a phone.

## Samsung NFC service consolidation

Two auto-loaded files in `/vendor/etc/init` declare the exact same
`vendor.nfc_hal_service`, without `override`:

- `multi.android.hardware.nfc@1.2-service.rc`: the Samsung NXP service plus
  Samsung SLSI service and four hardware-selector triggers, but no interfaces.
- `nxp.android.hardware.nfc@1.2-service.rc`: the same NXP executable with four
  HIDL interface bindings.

AOSP init sorts directory entries and rejects a duplicate service declaration
without `override`. The `multi` definition therefore keeps the service while
the later duplicate cannot contribute its interface bindings. This impairs
init's `ctl.interface_start` service lookup even when the binary is present.

`python3 tools/prepare_hardware_candidate.py` copies the four exact bindings
into the retained NXP service in `multi`, then emits a deletion record for the
now redundant `nxp` RC. It preserves both Samsung executable paths, disabled
flags, user/group, class and all original hardware-selector triggers. The
original first-selected definition did not have `oneshot`; that behavior is
preserved. All ODM Oplus/NXP services and their manifests remain intact.

The manifest pins original and resulting bytes. Replacement metadata is
uid/gid 0, mode 0644, `u:object_r:vendor_configs_file:s0`, read directly from the
original vendor inode/xattr. Four bounded source/overwrite tests pass.
Host `host_init_verifier`, actual init import behavior and phone service startup
still need to be checked. This does not fix the separate missing
`libpnscr2_aidl.so` dependency in the Oplus NFC extension.

## Optional charger declaration consolidation

`python3 tools/prepare_charger_candidate.py` emits a separate delete-only plan
for the legacy `odm/etc/init/vendor.oplus.hardware.charger@1.0-service.rc`.
Its three services (`oplus_charger_hal_service`, `wlschgd`, `ufcsd`) are already
defined in the earlier V3 RC. The V3 file is an exact superset of the legacy
file, except the chosen charger executable and two added `chown` commands.
The tool proves that equivalence over pinned bytes. The V3 binary and AIDL3
manifest exist in the original ODM. Two fixture tests pass.

This retains all currently selected V3 services and every distinct action.
It does not establish that any Oplus charging implementation matches Samsung
hardware. Keep this plan separate until whole-tree init import review and
host verification confirm the expected selection.

Other apparent duplicates were reviewed: audio and Qualcomm RIL definitions
use explicit `override`, so they are not treated as accidental duplicates.

## Optional brightness bridge

The original vendor bridge hardcodes `screen_brightness * 255 / 8191`.
The donor product overlay declares an integer maximum of 4095, while the
Samsung vendor overlay declares 255. A fixed ColorOS setting scale cannot be
assumed for HyperOS; effective overlay selection and integer conversion also
remain runtime questions.

`optional-brightness/brightness_sync.sh` is a separate, un-applied alternative
that reads normalized `cmd display get-brightness 0` and the actual panel's
`max_brightness`. It validates both inputs before converting, writes only on
change, and produces no write value for invalid/unknown results. It does not
set shell properties, change permissions or replace the init service domain.
Three test groups cover 24 valid/invalid cases under POSIX sh and real mksh.

The donor services.jar contains `get-brightness` and the display shell class;
the standard AOSP command returns a normalized float for an explicit display
ID. This is class/string/API evidence, not execution of the Xiaomi method.
Runtime command behavior, normalized luminance mapping and slider response
must be confirmed before enabling this optional change. The replacement must
preserve original uid/gid/mode and `u:object_r:vendor_file:s0`.

## Display overlay source, blocked on signing/idmap validation

`overlay-source` contains a new narrow 120 Hz peak-default overlay. It does not
rewrite the original signed APKs, force a fixed refresh mode, alter brightness
calibration or invent a hole-punch geometry. Compile it against the exact donor
framework resources, sign with a permitted platform/overlay key, and validate
the idmap/resource resolution and partition precedence before packaging it.

The actual donor framework and existing product overlay carry the same Xiaomi
MIUI signer certificate. That certificate does not provide its private key.
Changing `resources.arsc` inside either existing APK would invalidate its
signature; no such edit is performed. No test key, lower SDK or disabled
overlayable check is used to pretend a replacement is accepted.

`display-evidence.json` records the signer metadata and Samsung brightness
resources. The Samsung vendor overlay has no physical cutout path, so this
candidate deliberately leaves cutout changes pending actual panel geometry.
