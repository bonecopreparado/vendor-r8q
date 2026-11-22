INSTRUCTIONS='''HyperOS4 R8Q P1r5 - ONE COMPLETE EXPERIMENTAL ROM ZIP

For Galaxy S20 FE Snapdragon r8q SM-G780G / SM-G781B only.
Hardware boot is NOT confirmed. Keep a working Samsung stock restoration kit.

This is the complete ROM, including R2 Samsung IPA/IPA UC firmware and Vendor
label repairs, the compiled MEMCG/PSI/v1-freezer kernel with KernelSU/SUSFS and
NFLOG preserved, the existing scheduler/display/ueventd fixes and V6 diagnostics.
No separate R2, R3, ENABLE ZIP, payload directory or installer creation is needed.
SELinux options are preserved; this build does not force permissive.

PREPARE BEFORE FLASHING
- Back up personal files and keep restoration files outside internal storage.
- Unlocking the bootloader, installing compatible TWRP/OrangeFox and preparing
  disabled vbmeta are separate prerequisites. The installer requires existing
  AVB flags=3 and does not write vbmeta, the bootloader or recovery.
- Coming from stock does not mean the old P1r4 ROM must be installed first.
  This ZIP installs the complete Super, DTBO and boot itself.
- Save the full ROM-FILE.zip on internal storage, exFAT SD or USB OTG.
  FAT32 cannot hold a file above 4 GiB. Do not use a truncated copy or extract
  the ROM into parts. Verify its SHA256 against the release checksum.
- Charge to at least 50%, or keep the device charging with at least 20%.
  The exact reviewed Samsung APNHLOS firmware profile is checked read-only.
  A different firmware version aborts before flashing; send recovery.log.

FLASH
1. Boot TWRP/OrangeFox and install ROM-FILE.zip without extracting it.
2. Wait for all payload checks, writes and fresh storage readbacks to finish.
3. Require the final P1r5 success message. On any error remain in recovery and
   send /tmp/recovery.log. Do not bypass guards or boot a partial installation.
4. Reboot RECOVERY once so it reloads the new logical partition mappings.
5. Reboot System once and record whether boot animation/setup is reached.

DATA
The ZIP never formats or repairs userdata, metadata, EFS or Persist. It also
does not fix stock-to-port encryption/data incompatibility by itself. Preserve
files first; any clean-data preparation must be a deliberate separate recovery
operation after backup. Do not repeat Format Data as a speculative boot fix.

LOGS
If stuck/restarting, allow about three minutes and return directly to recovery.
Extract ONLY extras/R8Q-BOOTDIAG-V6-COLLECT-ONLY.zip from the downloaded ROM,
or download it from the release assets, then install it after the boot attempt.
Send its .tar
privately, plus recovery.log and fresh last_kmsg/pstore if collection fails.
R8QTRACE writes init milestones and late-fs wait/mount checkpoints to last_kmsg. No separate ENABLE is needed.

WHAT IS VERIFIED
All source and payload hashes; actual kernel Image/configuration/link symbols;
R2 firmware bytes and Vendor labels baked into Super; independent LP readback;
native ZIP64 reads; flushed writes and O_DIRECT storage readback in recovery.
These checks do not establish a successful Android boot or working hardware.
Known VINTF/legacy HAL findings and the unconfirmed LMKD camopt crash remain.
'''
