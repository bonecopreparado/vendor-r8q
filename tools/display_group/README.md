# SurfaceFlinger DisplayMode group width correction

The received ARM64 library compares a candidate's **int32 group** to one byte
of the default mode's group. Equal groups such as 1080 therefore compare as
1080 versus 56. A different group 56 can also falsely compare equal to 1080.
The change restores a 32-bit load on the default side. It does not remove the
group check, the refresh-rate ranges, the DPI/resolution check, or the fatal
assertion. It does not force a particular refresh rate.

This directory contains an **offline recipe**, not a recovery installer or ROM.
The OEM libraries and private logs are not redistributed. The separate netd
failure caused by the installed kernel's missing NFLOG support remains open.
KernelSU and SUSFS have not been changed.

## Exact input and output

| Item | Value |
| --- | --- |
| Installed path in crash | `/system_ext/lib64/libsurfaceflinger.so` |
| Size | 13,826,216 bytes, unchanged |
| Input SHA256 | `5c472e0e217b054a95b207ccfa4cca8737b2a6e5ce5d0e07aa303a1965f6f5be` |
| Output SHA256 | `f11986fff4ce9d9f1b59d282722d529b8f847f78bac4e4f0a308fe80d911abd6` |
| Original GNU Build ID | `37802932c7e56f8bdcec511be7bb1e90` |
| Instruction VA / file offset | `0x49b954` / `0x49b954` for this ELF only |
| Before | `08 c1 40 39`: `ldrb w8, [x8, #0x30]` |
| After | `08 31 40 b9`: `ldr w8, [x8, #0x30]` |

The GNU Build ID stays the original linker identifier after the byte patch;
it is not a digest of the patched file. Use the output SHA256 to distinguish
the candidate. Only byte offsets `0x49b955` and `0x49b957` change.

## Offline use by the image builder

```sh
python3 tools/display_group/patch_surfaceflinger.py original.so candidate.so
python3 tools/display_group/patch_surfaceflinger.py candidate.so restored.so --reverse
```

Both directions require the exact known whole-file SHA256, size, ELF architecture,
GNU Build ID, executable segment mapping and instruction context. Every output
must be a new file. The source file is preserved. No Android binary is launched.

The installed `system_ext` is EROFS and cannot be updated by `adb push` into its
mounted directory. Image-builder integration must add this replacement to the
existing policy/mapping plan for the correct P1r2 image, then rebuild it using
`tools/rebuild_erofs_candidate.py` **with `--legacy-kernel-symlinks`**. Preserve
the other operations already in that plan. Inside the image the target is
`/lib64/libsurfaceflinger.so`, not `/system_ext/lib64/libsurfaceflinger.so`.

The replacement operation has this form; `replacement_file` must be a real
candidate under the project root, with the exact SHA256 above:

```json
{
  "op": "replace",
  "path": "/lib64/libsurfaceflinger.so",
  "old_sha256": "5c472e0e217b054a95b207ccfa4cca8737b2a6e5ce5d0e07aa303a1965f6f5be",
  "replacement_file": "candidates/display-group32/libsurfaceflinger.so",
  "sha256": "f11986fff4ce9d9f1b59d282722d529b8f847f78bac4e4f0a308fe80d911abd6"
}
```

The existing EROFS builder compares every resulting inode, file and xattr,
preserves ownership/modes/timestamps/hardlinks and checks old-kernel symlink
layout. Repacking must also regenerate the super/payload/installer hashes.
This review has not rebuilt or flashed that image; no new ROM is announced.

## Verification

Use Python 3.11+ with `unicorn==2.1.4` and `pyelftools==0.32` in a project venv.

```sh
python3 -m unittest discover -s ci-r8q/tests -p test_display_group_patch.py -v
python3 tools/display_group/review_received.py --surfaceflinger original.so --composer composer-service-r8q > received-function-emulation.json
```

Public CI executes the ARM64 three-instruction comparison for 100 int32 pairs
and exercises the patcher's file/ELF/output guards on synthetic ELF fixtures.
It does not need or download private OEM libraries.

The second command requires the exact private files supplied for this review.
It emulates the received composer attribute function and SurfaceFlinger mode
predicate with synthetic object memory. It checks both 60/120 Hz candidates,
different groups, geometry and range rejection, group switching, and low/high/
negative group IDs. The two initial external calls are stubbed, testing the
returned flag as both false and true; PAC instructions are skipped. It is not
a full Android, Binder, display hardware or boot emulation. The report includes
these limitations and exact binary hashes.

## Stage both boot fixes without losing the existing policy changes

After generating and verifying the existing P1r2 policy/mapping plans, run:

```sh
python3 tools/display_group/prepare_image_plans.py --plans patches/0007-policy-integration --output patches/p1r3-boot-fixes
```

This reads the source images without changing them, verifies their complete
SHA256 against the plans, preserves all existing operations/replacement bytes,
and stages the corrected library plus `/vendor/etc/ueventd.rc` in NEW plans.
The bridge imports the existing verified `/vendor/ueventd.rc` and inherits its
metadata. An existing canonical file, unknown vendor init/rules, absent donor
import, conflicting operation or wrong library causes refusal. The original
plan directory is never overwritten. The resulting status deliberately says
`STAGED_IMAGE_PLANS_ONLY_KERNEL_BLOCKED`; these are not images or a flashable
installer. A failed staging invocation must not be consumed by a build.

The future complete-ROM workflow must consume these new plans with the old
kernel symlink compatibility mode and integrate a genuinely linked NFLOG kernel
with complete SUSFS. It must regenerate and verify all images and ZIP hashes.
The old `rebuild_p1_ci.py` workflow still consumes the original plans and is
NOT a delivery path for these boot fixes. Do not rerun it and rename P1r2.

Four policy/hardware input guards in `prepare_p1_plans.py` now use explicit
exceptions instead of Python assertions, so `python -O` cannot skip them.
Integration regression fixtures verify unchanged prior operations, duplicate/
foreign-target rejection, exact imports, path containment and optimized-Python
hash enforcement. They do not replace a full image rebuild or phone test.
