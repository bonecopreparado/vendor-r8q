# IPA authentication failure in the retained P1r4 boots

The four retained Android boots stop in the IPA worker after PAS_INIT_IMAGE
fails, followed by `ipa_assert`. The previous scheduler fault signature is
absent from these attempts. The new fix is experimental: hardware boot has
not been tested or confirmed.

The current recovery capture reports `G781BXXSIHYJ2`. Earlier conversation
references to G780G must not be used to choose firmware for this device.

## Evidence and interpretation

- All seven files in the submitted Vendor archive match the submitted SHA256
  manifest. The MDT is exactly its ELF header/program headers plus b01, and
  the split files match the corresponding ELF ranges.
- Direct kernel firmware requests fail with EACCES, then take the userspace
  firmware fallback. PAS_INIT_IMAGE returns secure-world error `-3145797`;
  its Linux error is `-22`, and the IPA driver raises the first fatal Oops.
- The private APNHLOS read-only extraction contains the same executable code
  segments b00/b02/b03/b04 as Vendor, but different authentication metadata,
  signatures and certificate chain in b01/MDT. APNHLOS uses Samsung
  Attestation CA / Samsung Root CA; Vendor uses the generic SecTools CA/root.
- All three signatures in the Samsung chain and the stock MBN RSA-PSS/SHA256
  signature verified offline. The derived ELF preserves every byte outside
  its existing b01 authentication segment. See `offline-verification.json`.
- A SecTools **leaf subject name alone is insufficient** to identify trust:
  the stock Samsung leaf also has that name. The issuer/root chain, metadata
  and hashes distinguish the files. TheMuppets' common Vendor reference also
  uses a generic chain and is not a substitute for this device's APNHLOS.
- The physical APNHLOS/modem submounts precede the recovery's Vendor mount.
  Thus the old recovery path can be hidden by the parent Vendor mount; its
  absence there does not establish that Android has no firmware partition.

These observations make the fallback selecting a differently authenticated
IPA the leading explanation for the current crash. The addon tests that
explanation by replacing the Vendor authentication files with the matching
device-stock versions. Waiting longer or formatting Data does not repair
the fatal kernel exception. Further boot failures may remain after this one.

The old successful kernel also uses SDFAT and shows the same shortname and
volume-size warnings. Those messages do not establish a new FAT regression.
The kernel memcpy/memcpy_toio difference remains unproven and is not changed
by this fix. IPA assertions and firmware authentication are retained.

## Recovery addon

`tools/package_ipa_stock_fix.py` creates
`R8Q-P1r4-IPA-STOCK-FIX-EXPERIMENTAL.zip`. This is an addon for the installed
P1r4, not a full ROM. It includes no firmware blobs; the device supplies its
own stock b01/MDT through a verified temporary **read-only** APNHLOS mount.

Preflight requires recovery/root, Snapdragon r8q, G780G/G781B bootloader
family, logical ext4 Vendor, the reviewed init and code file hashes, regular
files on the same filesystem with expected ownership/mode and readable
labels, sufficient free space, and battery >=50% or a charging state. The
device-stock firmware must match the exact reviewed SHA256 hashes. A
different stock version aborts before any writable Vendor remount.

It stages signed b01/MDT and updates the same authentication region in the
existing ELF, validates all three expected hashes, backs up the originals
inside Vendor, and renames the staged files into place. Hash readback and
sync follow. Detected activation/sync failures restore the originals; the
original read-only mount mode is restored. Power interruption still can
require recovery; a verified partial state can resume with its original
backup present. An already-correct state is accepted without more writes.

No kernel/SUSFS, APNHLOS, bootloader, Data, Metadata, EFS or Persist content is
changed. Raw user logs and firmware captures are not published.

## Validation

Nine host fixture tests execute the actual installer with mocked mount,
property and SELinux utilities and regular files rather than block devices:

- Install, original backup, idempotence and both original mount modes.
- Stock/Vendor/code/init drift refusal before writable remount.
- Device, recovery, battery, charging and TWRP guards.
- Restoration after a mid-activation failure and a later sync failure.
- Writable-remount, label and free-space failure handling.
- Refusal of symlinks and partial state without a valid backup.
- Resume with a valid original backup.
- ZIP CRC, SHA256, script permission and absence of binary payloads.

Offline certificate/MBN verification used the actual supplied files. Host
tests and file readback do not prove Android boot. Reboot recovery first,
then System once; collect a fresh last_kmsg/recovery.log if boot still fails.

The mksh CI pass also checks the shell actually used by Android. An initial
fixture run exposed its built-in `hash` alias shadowing a same-name helper;
the installer helper is now named `file_sha256` to avoid that collision.
