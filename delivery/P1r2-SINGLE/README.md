# P1r2 complete recovery ZIP

P1r2 packages the same reviewed P1r1 mapping experiment for S20 FE Snapdragon
r8q G781B/G780G, with the corrected ZIP64 reader and packaging safeguards.
It is an experimental boot test, not a stable ROM or a confirmed bootloop fix.

Changes since the distributed P1r1:

* Accept valid ZIP64 end records written before the classic 32-bit fields
  overflow, and reject conflicting legacy/ZIP64 values.
* Report failed member offsets/sizes and expected/observed CRC; retain all
  pre-write integrity checks and partition readback checks.
* Stage incomplete builds as `.zip.partial`, preserve existing outputs, and
  compare all metadata and payloads before publishing a final ZIP.
* Run ARM64 boundary fixtures before building. Read all 22 payloads from the
  actual final ZIP with the exact packaged Android helper under QEMU, checking
  byte counts, native CRC and SHA256 before attestation or upload.

The 23 system_ext/product mapping omissions remain. System/platform mappings,
main policy CILs, kernel, boot and DTBO keep their previously reviewed content.
The early-boot review found filesystem support and direct library providers
for init, apexd, vold, hyper_bpfloader, servicemanager and surfaceflinger; it did
not establish a new causal fix. Known VINTF FCM/kernel/HAL issues remain, and
runtime service/ABI behavior requires failed-boot evidence from the phone.

The last P1r1 report stopped at `super-012.gz` CRC before writing partitions.
That card was exFAT, so FAT32's 4 GiB limit does not explain that attempt. The
tester has not yet supplied the complete ZIP SHA256. The native reader bug
fixed here was independently reproduced on other ZIP64 layouts; it does not
establish the cause of that CRC failure.

## Phone-only installation

Use the GoFile link published in this build's GitHub prerelease. Download the
one complete `HyperOS4-R8Q-P1r2-SINGLE-EXPERIMENTAL.zip` and compare its SHA256
with the matching release sidecar. Keep it compressed. GitHub source archives
and Actions evidence artifacts are not recovery ROM ZIPs.

Use internal storage or a filesystem supporting files larger than 4 GiB.
Charge to at least 50%, keep the confirmed restoration ROM and backups on
external storage, then select the full ZIP in OrangeFox. The packaged English
instructions cover the existing clean-install procedure and exporting logs
before a separate manual Format Data; the installer itself does not format data.

If the updater stops on a failed integrity check, save recovery.log and do not
bypass the check. If flash completes but Android restarts, return straight to
recovery and use the existing read-only collector before another boot/restore:

https://github.com/bonecopreparado/vendor-r8q/releases/download/r8q-bootlog-collector-2-1/R8Q-BOOTLOG-COLLECTOR.zip

The collector is separate from the ROM and produces diagnostic logs, not a
boot correction. The full ROM, SHA256, English instructions and ARM64 readback
report are published only after the build checks succeed.
