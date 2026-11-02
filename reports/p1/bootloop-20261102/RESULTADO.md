# P1 first-boot report: recovery logs do not contain the failed boot

The tester reports a reboot approximately two seconds after the Samsung S20 FE
logo, before the HyperOS animation, on two devices. This is a confirmed device
test failure, not a successful Android boot. No causal ROM patch is justified by
the submitted recovery buffers alone.

The submitted files were analysed locally in full; their raw contents include
personal application paths and are deliberately not published here.

## Flash result

In `recovery (2).log`, an initial attempt stops before any writes because the
battery is 33% and discharging (lines 159309-159310). The next attempt, while
charging, completes in 299 seconds. Every image readback matches; OrangeFox
reports installer code 0 (lines 159715-159722).

The subsequent vendor/product/odm mount errors occur before the requested
recovery restart, with the old dm mappings still active. That log ends after
Copy Log, without a recorded reboot or a subsequent Format Data. This does not
prove the testers omitted either step later. Userdata at collection time is
F2FS with metadata encryption, decrypted through dm-4; it is not ext4.

## The libjson message is from recovery

`logcat (1).log` contains 23,097 lines, including 458 repeated pd-mapper linker
failures and recovery activity throughout the same session. The error repeats
approximately every five seconds while OrangeFox remains alive for tens of
minutes. There is no hyper_bpfloader event, fatal init reboot, or kernel panic
in that buffer. Its absence does not exclude such an event in the uncollected
Android boot.

The actual CI P1 vendor inventory and independent local image inspection both
contain the required libraries:

- `/vendor/lib64/libjson.so`: ELF64 AArch64, 45,712 bytes,
  SHA256 `59d05dbe63aa61267252774306b3dc0926127419fd9d6d5dc34a84b3465878e6`.
- `/vendor/lib/libjson.so`: ELF32 ARM, 28,028 bytes,
  SHA256 `0f8fc89f0d14e675edca8752a94a72732006c65f3d7d1406e414339748827bbf`.

`pd-mapper` is ELF64 AArch64 and needs libjson.so. Its original init.target.rc
service has neither critical nor reboot_on_failure. A recovery linker/mount
visibility problem is plausible; this is not proof of a missing P1 blob or of
the Android reboot cause. No library has been replaced and no service disabled.

`dmesg (1).log` covers recovery uptime approximately 2065-2292 seconds and ends
with recovery exporting logs. It is not the kernel buffer from the two-second
failed boot. It does not contain a persisted previous-boot log.

## Next evidence

Return directly to OrangeFox after one failed boot, then preserve pstore/ramoops
and /proc/last_kmsg before another ROM boot or restoration. The phone-only
collector records these sources, bounded recovery context and explicit absence
markers, without changing ROM partitions, clearing logs or formatting userdata.
It cannot recreate a previous boot log that the device did not preserve.

Confirm whether recovery was restarted and Format Data performed after flashing.
The Hyper BPF loader, early mounts, SELinux load and kernel panic remain distinct
hypotheses until failed-boot evidence identifies a stage. Host VINTF findings
remain unresolved and are not silently marked compatible.
