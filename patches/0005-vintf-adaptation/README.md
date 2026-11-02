# Additive VINTF metadata candidates

These are **candidate inputs, not a flashable patch**. No ROM image has been
changed by these scripts. No HAL is removed, no vendor version is raised and no
existing framework requirement is deleted.

## Existing VNDK30 provider

`candidate/system_ext/etc/vintf/manifest/r8q-vndk30.xml` adds a framework declaration
for the factory `com.android.vndk.v30` component already present in the donor.
The existing VNDK34 declaration is retained. The vendor continues to require
VNDK30, and the original source image/APEX remains unchanged.

`prepare_vndk30_candidate.py` verifies the exact APEX payload hash and every
VNDK core/SP provider named in its lists: **287 ARM and 287 ARM64 ELFs**, including
the `hw/` implementation. ISA-specific compiler-runtime names are checked only
for their matching architecture. `candidate/evidence.json` records the library
lists, file hashes, ELF architecture and limits. LLNDK libraries outside this
APEX are explicitly not claimed validated by this inventory. Factory presence
does not prove activation or linker namespace operation on a phone.

## Existing SELinux 30.0 mapping interface

The framework actually contains `30.0.cil` and compat mapping files for system,
system_ext and product. The matrix's listed minimum of 31.0 did **not** mean those
mapping files were absent. The policy audit bundle includes them in the actual
composition; the isolated repaired CIL candidate compiles with these inputs.

`prepare_sepolicy30_candidate.py` verifies all five original mapping files
against their pinned hashes, then adds only `<sepolicy-version>30.0` to the
framework matrix. It preserves every other byte, the real vendor interface
30.0, the binary kernel policy version 30, FCM levels and all HAL requirements.
This entry **must accompany coherent final CIL and app-context corrections**;
it is not permitted to advertise support with the unchanged original P0 CIL,
which fails compilation. Mapping presence plus candidate compilation does not
prove complete semantic or runtime correctness. Open assertion findings and
kernel policy-load validation remain separate gates.

## Optional FCM4 reference diagnostic

`reference/aosp-android10-fcm4-hal.xml` is the unmodified AOSP hardware/interfaces
HAL matrix from tag `android-10.0.0_r47`, commit
`2083ef1548be73bb8f002a98de8e1105fae85831`, SHA256
`a407c2e8e947054a8a85f167d679d2af3e0c87096f415de6a153725c957aa130`.
Source: https://android.googlesource.com/platform/hardware/interfaces/+/2083ef1548be73bb8f002a98de8e1105fae85831/compatibility_matrices/compatibility_matrix.4.xml
Mirror: https://github.com/aosp-mirror-neo/platform_hardware_interfaces/blob/2083ef1548be73bb8f002a98de8e1105fae85831/compatibility_matrices/compatibility_matrix.4.xml

It is not copied into the production candidate overlay. That source XML omits
the kernel fragments appended during the original Android build. Adding it only
provides a diagnostic of legacy HAL declarations and cannot establish that an
Android17 framework supplies the complete Android10/FCM4 compatibility contract.
Its AOSP source remains under its original Apache-2.0 terms, not the project's
MIT grant.

For example, this Android10 reference requires audio/effect HIDL 5.0, whereas
the current Samsung manifest advertises 6.0. An older matrix cannot simply be
treated as the complete current vendor contract. Differences in other HIDL
minor versions require the actual tool's compatibility semantics, not numeric
comparison alone. No target FCM level is raised by these candidates.

The CLI's deprecation/unused-HAL checks also remain distinct from the OEM
runtime compatibility path. The Mi10 donor already had target4, sepolicy30.0
and VNDK30 declarations. No execution of its OEM libvintf behavior on a phone
has been demonstrated; these host checks do not supply that missing proof.

## Validation

`python3 patches/0005-vintf-adaptation/test_candidates.py -v` checks source
mutation rejection, exact single-entry policy changes, unchanged requirements,
mapping identities and ELF architecture checks.

With the reviewed official Android17 host binary and its `lib64` directory:

```
python3 patches/0005-vintf-adaptation/run_host_variants.py \
  --checkvintf /path/to/otatools/bin/checkvintf \
  --out /path/to/new/results \
  --include-legacy-fcm4-diagnostic
```

The runner verifies the exact official binary, unpacks the pinned P0 metadata,
uses the actual 4.19.325 kernel and runs three separate variants. It never
rewrites the original inputs or calls a successful host check proof of boot.
