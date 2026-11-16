# Security R2: verified Vendor metadata defects after the first IPA repair

The first IPA addon made measurable progress. Three retained new Android
boots report `IPA FW loaded successfully`, without the previous IPA assertion.
Older failures are still present earlier in the persistent kernel ring and
must not be attributed to the new attempts.

The new attempts fail to authenticate `ipa_uc` and reach Android services.
The latest kernel console ends with a normal reboot commanded by init near
31.56 seconds. Pmsg records Keymaster/Gatekeeper aborts with
`QSEECom_start_app failed`, failed QSEE hardware-service lookups against
`default_android_hwservice`, and repeated Keystore failures to obtain the
mandatory TEE. These are concrete boot blockers; waiting or formatting Data
does not repair their service/firmware setup.

## File contents and labels are separate checks

The first attempted Vendor collection was the recovery's RAM tree, with a
zero-byte context file and missing firmware. It was not evidence that the ROM
contained an empty database. Its tar errors were also prefixed to the gzip
stream by `adb exec-out`; subsequent collection used a regular RAM archive
and `adb pull` instead.

A separate read-only mount of the verified logical Vendor provided the real
files. Their init and hardware-service database hashes match the reviewed
P1r4. The QSEE, engmode and vaultkeeper context entries are present and name
valid types. A subsequent `ls -Z` capture establishes these metadata defects:

| Target | Observed label type | Required label type |
| --- | --- | --- |
| Vendor filesystem root | `vendor_apex_file` | `vendor_file` |
| `vendor_hwservice_contexts` | `vendor_configs_file` | `hwservice_contexts_file` |
| `vendor_file_contexts` | `vendor_configs_file` | `file_contexts_file` |
| `vendor_property_contexts` | `vendor_configs_file` | `property_contexts_file` |
| `vendor_seapp_contexts` | `vendor_configs_file` | `seapp_contexts_file` |
| `vndservice_contexts` | `vendor_configs_file` | `vndservice_contexts_file` |

The Vendor etc directories are already `vendor_configs_file`, and
`vendor_service_contexts` already has its specific service-context type.
Both ueventd rule files retain `vendor_file`; their contents are preserved.

Android's context loader tests readability before selecting Vendor context
files. Hwservicemanager is allowed to read `hwservice_contexts_file`. A correct
mapping file that cannot be traversed/read therefore can leave runtime
lookups using the generic default. This is consistent with the observed
denials. Correcting the root and exact context/policy-file labels addresses
the metadata problem without introducing broad allow rules or permissive
domains. All target context strings passed the existing compiled candidate
policy's context check; the report records those results.

## IPA UC must be replaced as a coherent set

The device-stock IPA UC has a Samsung Attestation CA / Samsung Root CA chain.
All three certificate signatures and its MBN RSA-PSS/SHA256 signature verified
offline. Its MDT equals b00+b01. Its b02 code is 35,212 bytes, compared with
35,572 in Vendor: this is not just a certificate replacement. R2 replaces all
four split files and constructs a matching 47,500-byte ELF from the actual
ELF program headers. Whole-file digests guard every prepared result.

The earlier IPA fws correction is included, so the same R2 ZIP accepts a
reviewed P1r4 both before and after the first addon. Firmware binaries are
not distributed: the installer reads this device's APNHLOS read-only and
accepts only the exact reviewed stock hashes.

## Recovery behavior and validation

The script identifies logical ext4 Vendor and can mount it privately when
the recovery's `/vendor` is only its RAM stub. It requires recovery/root,
r8q/G780G or G781B bootloader family, matching init/context/firmware contents,
known original labels and file metadata, sufficient free space, and charge
>=50% or a charging state. It validates all stock inputs before writable
remount and prepares everything in RAM.

Before changes it saves the original bytes, digest manifest and label
manifest in `firmware/.r8q-security-r2-backup`. This records the actual
pre-installation state, including an already-applied first addon. It stages
files, activates replacements, changes only the listed labels, syncs and
checks results. Detected activation, label or final sync failures restore
the saved bytes/labels. Re-running validates and retains the original backup.
Original read-only mount mode is restored and private mounts are released.
Power interruption still can require recovery; CI does not prove boot.

Eleven recovery fixture tests execute the real rendered script, covering
original/R1 starting states, idempotence, automatic Vendor mounting, failure
restoration, guard refusals, corrupt backups, charging and read-only state.
CI runs these under mksh, the Android shell implementation. Four additional
real ext4 fixtures verify targeted labels, unchanged file bytes/other inode
metadata, source/output guards, symlink refusal and the full-builder hook.
The six existing rebuild-orchestrator checks also remain required.

`tools/vendor_security/image_labels.py` repairs a separate, pinned image copy
and requires clean read-only fsck before and after. It changes the specified
SELinux xattrs while preserving other inode metadata and file bytes. Future
P1r4 image reconstruction now invokes this after the original content/tree
verification and before composition/super hashing. Its evidence binds the
prelabel build report to the checked new Vendor hash; only the derived
intermediate is replaced. Extracted source images remain preserved.

No full ROM or kernel has been rebuilt by this addon workflow. No raw user
logs or firmware captures are published. Kernel/SUSFS, policy allow rules,
Data, Metadata, EFS, Persist, bootloader and APNHLOS contents are unchanged.

## Remaining uncertainty

Pmsg also contains two `lmkd` SIGSEGVs in camera-optimization threads, without
a complete stack. Their cause and whether restoring Vendor access changes
them remain unknown. R2 does not claim to fix them or establish successful
Android boot. A new test should collect last_kmsg, recovery.log and pstore;
the restored metadata may also let the existing V6 diagnostics capture more.
