# R8Q port audit

This branch builds tools and review evidence, not a complete or boot-tested ROM.
No device writes are performed by CI.

The shell installer previously used byte offsets in signed 32-bit shell arithmetic
and numeric tests. Real mksh reproduces both reported symptoms: a negative skip
at 2 GiB and a repeated 4096-byte prefix discard at 4 GiB. P0r7 keeps offsets out
of those operations and preserves all hashes and target guards.

CI runs the regression tests, builds a modern secilc and matching policy-capability
checker from SELinuxProject commit `6423998bc7b154da7f9fe726cfda9ace774dfa94`,
then compares exact original and isolated candidate CIL inputs. Every bundle file
is pinned by hash. All policy capabilities, including `functionfs_seclabel`, must
survive compilation and serialization. The candidate is also checked against
neverallow assertions. The raw compiler failure remains in the artifact. When
`--baseline ci-r8q/baselines/neverallows-v1.json` is supplied, a separate
regression gate accepts only unchanged or reduced reviewed diagnostics and
fails on new findings, unknown/truncated output, failed init compilation or
lost capabilities. The baseline contains 335 regular records and three extended
ioctl records that the older summary parser omitted. A passing gate always
retains `boot_ready: false` and a `NOT_BOOT_READY` status.

Run the unit tests directly from a clean source checkout:

```sh
python3 -m unittest discover -s ci-r8q/tests -v
```

The required small P0r7 assets and their fixed `pins.json` are source files and
must be committed together. Tests do not regenerate pins or build a Windows
kit before loading them; those steps would hide a missing-source regression.

The isolated policy changes do not modify any ROM image and are not declared safe
for deployment merely because compilation succeeds. VINTF/context/kernel/runtime
work remains. Files from devices and personal recovery/logcat logs are not included.

Tools/audit artifacts are not recovery installers and must never be flashed.
Use the current root README and the release manifest to distinguish downloadable
installers, source tools and diagnostic evidence. Mirror availability does not
change validation results or prove that the ROM boots.
