# P1r1 storage failure review

The submitted recovery log identifies `/external_sd` as exFAT (line 1148).
The kernel log also detects exFAT. FAT32's per-file limit therefore does not
explain this attempt. This does not establish that the download, copy, or SD
read was correct: the tester's complete-file SHA256 is still missing.

The installer checked `super-000.gz` through `super-011.gz` and stopped on an
outer-ZIP CRC mismatch in `super-012.gz`, before its partition write phase.
The later recovery message `installer code = 0` conflicts with the updater's
failure; it does not override the CRC failure or prove a successful flash.
The submitted dmesg and logcat are from recovery, not the failed Android boot.

## Confirmed source defects repaired

* The ZIP reader rejected otherwise valid ZIP64 archives between 2 and 4 GiB
  when the writer included ZIP64 end records before the classic values reached
  their maximum. The parser now recognizes these records and cross-checks the
  non-sentinel classic fields. A false locator inside a normal central-directory
  comment is not treated as ZIP64. This defect does not explain the published
  5.38 GB P1r1 CRC failure: the reader already parsed its directory and other
  members successfully.
* CRC errors now identify member, data offset, member size, total archive size,
  and expected/observed CRC. Installer wording no longer presents every reader
  error as an exclusive SHA256 mismatch. Rejection and pre-write checks remain.
* Failed packaging could leave a partial ZIP under the final installable name.
  Packaging now uses `.zip.partial` and publishes the final name only after
  validation. Existing outputs and success sidecars are preserved and rejected;
  failure cleanup removes only files created by the current invocation.
* Final metadata verification now compares manifest, instructions, license and
  notice bytes as well as the installer, helper and all image payloads.

## Verification scope

The storage-checks workflow builds the static Android API 29 AArch64 reader and
actually extracts data under qemu-aarch64. It tests offsets around 2 GiB, crossing
4 GiB, exactly 0xffffffff, and above 5 GiB; a long CRC stream; mutations before
and after 4 GiB; truncation; duplicate/missing members; and inconsistent headers.
The same fixtures run under the host undefined-behavior sanitizer. A separate
run rebuilds the pinned published P1r1 helper, requires its exact padded SHA256,
and explicitly records its known 2 GiB rejection instead of hiding it.

Real mksh tests include corruption of the outer ZIP after packaging, truncated
EOCD and changed helper bytes, with assertions that no mock partition changes.
Fault-injection tests cover failed second pass, changed metadata with a valid
CRC, stale/symlink sidecars, interrupted staging and late report-write failure.
No ROM build or release is triggered by the storage-audit branch. The next ROM
build workflow includes the ARM64 boundary checks before image reconstruction.

QEMU validates the reader executable, not the phone's storage driver or boot.
The current ROM and its hashes are unchanged. No new confirmed Android boot
blocker was established by this review. Known VINTF FCM/kernel/HAL findings and
possible early-init reboot paths remain; no services or checks were disabled.

## Next tester check, entirely on the phone

The already published P1r1 is `HyperOS4-R8Q-P1r1-SINGLE-EXPERIMENTAL.zip`,
5,387,889,291 bytes, SHA256:

`2c5678dc3f17a4de421b20e80382715fbb67be394f2468212cf606529a355e0a`

In OrangeFox Terminal, read the complete file:

```sh
sha256sum "/external_sd/Download/HyperOS4-R8Q-P1r1-SINGLE-EXPERIMENTAL.zip"
```

If the hash differs, obtain a fresh copy and verify it before installation.
If it matches but installation still fails, copy to internal storage, verify
the copy again and retry with the same integrity checks. A repeatable correct
hash plus repeatable CRC failure on internal storage needs further reader/
recovery investigation. Do not bypass CRC/SHA checks. Formatting the card is
not justified by the evidence. After a successful install, a failed Android
boot requires the previously supplied boot-log collector immediately upon
returning to recovery.
