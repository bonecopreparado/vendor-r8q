# HyperOS R8Q port research and tooling

## Current build: P1r2 (experimental, boot unconfirmed)

The latest distributed build is **P1r2**, from commit
[`a036e2ed34f82eab1cf6bea34b8ae8c81b6a0fa8`](https://github.com/bonecopreparado/vendor-r8q/tree/a036e2ed34f82eab1cf6bea34b8ae8c81b6a0fa8).
The tools below on `main` are the historical P0 baseline. Reviewing only that
baseline does not establish the contents of the published P1r2 images.

- [Current status and unresolved issues](STATUS.md)
- [P1r2 release, full ZIP link and SHA256](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r2-single-experimental-1-1)
- [P1r2 build and verification](https://github.com/bonecopreparado/vendor-r8q/actions/runs/41570865668)
- [Comparison with the external P0 review](reports/review-20261103/RESULTADO.md)

The specific duplicate SELinux declaration and nine invalid context references
reported for P0 were corrected in the P1 composition. The actual P1r2 CIL
compiled on the host with all six capabilities; 2,879 contexts passed.
This does not prove policy loading or Android boot on a phone. BPF and the
known VINTF/kernel/HAL issues still need runtime evidence.

## Historical P0 baseline documentation

This repository contains the installer source, audit tools, pinned input
identities and validation evidence for an experimental HyperOS port to the
Samsung Galaxy S20 FE Snapdragon: **SM-G781B and SM-G780G (`r8q`)**. It does
not contain a complete ROM, a complete vendor tree, or a confirmed working port.
It does not support the Exynos SM-G780F.

**Historical P0 status: compatibility work in progress; boot is unconfirmed. Do not
start another flash test from the historical P0 downloads while the current
SELinux, VINTF and kernel checks remain unresolved.** A passing installer test
or CI job is not approval of the ROM composition for a device test.

The composition under investigation uses the Mi 10 (`umi`) HyperOS donor,
Samsung R8Q hardware support and the existing ColorOS-port vendor/ODM base.
Large source images and externally maintained releases are separate inputs.
The small vendor baseline in this repository contains only selected files for
comparison. It cannot replace the complete vendor image.

## What the validation proves

| Check | What a pass demonstrates | What still needs evidence |
| --- | --- | --- |
| Payload SHA256, gzip integrity and raw image SHA256 | Input bytes match the pinned images | Framework/vendor compatibility |
| Flash readback | Bytes read through the block interface match after checked fsync/sync; reads may use kernel cache | Independent cache-bypassing verification, power-loss durability, kernel boot and Android startup |
| Installer regression tests | Covered cases behave as expected in mock partitions | The actual recovery and device runtime |
| SELinux compile and assertion baseline | The recorded candidate compiles and has no new baseline findings | Correct labels, access decisions and kernel policy load |
| VINTF host checks | The provided composition satisfies the particular checks reported | OEM runtime behavior, hardware services and boot |

The SELinux candidate has compiled without removing policy capabilities, but
its assertion audit has recorded 335 ordinary neverallow diagnostic records
(334 distinct texts), plus three extended ioctl neverallow diagnostics that
the previous parser omitted. Those diagnostics are not a count of proven
runtime bugs. Comparing the complete findings against a baseline keeps new
regressions visible; it does not clear known findings or make the candidate
ready for release. Original P0 images have not been updated merely because an
isolated candidate policy compiled.

Framework/vendor metadata differences, including VNDK and sepolicy interface
versions, must be assessed using the actual partition composition and kernel.
Changing declared versions or deleting requirements to obtain a green check
does not establish support. Device testing follows review of those results.

The official Android 17/API37 host `checkvintf` has now executed against the
actual P0 metadata and its embedded 4.19.325 kernel configuration. The full
checks returned **INCOMPATIBLE** with and without the kernel. See the
[recorded result](reports/audit-20261101/checkvintf/RESULTADO.md) and
[reviewed tool lock](ci-r8q/pins/official-otatools.json). The exact policy
context checker also rejected nine references in P0. Those nine were corrected
in P1/P1r2; the P0 files and reports below remain historical. VINTF/kernel/HAL
findings are still unresolved in the current build. See STATUS.md for scope.

## Repository layout

| Path | Contents |
| --- | --- |
| [`tools/`](tools/) | Metadata reproduction, installer generation and audit tools |
| [`ci-r8q/`](ci-r8q/) | Pinned audit inputs, regression fixtures, CI helpers and unit tests |
| [`delivery/`](delivery/) | Installer templates, manifests and historical preparation tools |
| [`reports/`](reports/) | Recorded validation evidence, with the scope and limits of each check |
| [`patches/`](patches/) | Isolated, non-shipping experiments and review material |

The original P0 image and chunk identities are recorded in
[`delivery/Revisao-P0r5-Windows/p0r5-assets/chunks.json`](delivery/Revisao-P0r5-Windows/p0r5-assets/chunks.json).
The READY payload identities and generation provenance are recorded in
[`delivery/Ready-P0r7/payload-identities.json`](delivery/Ready-P0r7/payload-identities.json)
and [`delivery/Ready-P0r7/PROVENANCE.md`](delivery/Ready-P0r7/PROVENANCE.md).

## Downloads and testers

An audit/tools bundle is not a recovery installer. In particular, historical
archives named `Auditoria-R8Q-*.zip` must never be selected in OrangeFox Install.
The tester log that selected an audit bundle explains the reported
`Invalid zip file format` before an installer was launched.

The historical small `*-READY.zip` files are installer scripts that require
22 external `.gz` payloads. Their small size does not mean they contain a ROM.
Distribution fixes and shell arithmetic fixes do not change the underlying
P0 images or prove boot. Use only the exact build and matching payloads listed
in a reviewed release; verify the installer's own published SHA256 as well as
the payload checks. Keep a working restoration ROM and backups outside the
partitions being written.

Current developer checks use temporary mock partition files and do not flash a
phone. See [`ci-r8q/README.md`](ci-r8q/README.md) for their implementation and
evidence. A release's explicit readiness status takes precedence over the
mere presence of a ZIP or a successful build workflow.

## Licenses

Original project tooling, installer code, tests and documentation use the
[MIT license](LICENSE). Firmware, vendor/ODM files, extracted policy/configs,
kernel/recovery binaries and third-party code keep their own terms and are
excluded from that grant. The copied CPython gzip module retains the full PSF
license and upstream notice; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
