# Keymaster access failure and a blocked encryption command

The private logs-v3.zip capture is usable: its boot.log contains both process
snapshots and 1500 selected Android logcat records. At both snapshots, vdc
is waiting in `cryptfs encryptFstab`, in a Binder ioctl. Keystore2 begins its
TRUSTED_ENVIRONMENT KeyMint compatibility request and the service manager
reports that the default Keymaster 4.0 instance has not registered. Keymaster
and StrongBox cannot open qseecom and abort/fail their trustlet connection.
spcom and ion accesses independently return EACCES. This is an Android
userspace failure, not a recovery-only log or evidence that waiting longer
will complete initialization. The latest kernel segment reaches 421.493116 s.

SELinux is permissive in this attempt. That does not bypass Unix device node
ownership/mode checks. Missing vendor ueventd rules are consistent with the
observed failures, but the supplied capture does not include actual Android
node stat values, the Android first-API property, or ueventd's parsing log.
The complete causal chain must therefore be confirmed by the next test.

The pinned public vendor baseline contains `/ueventd.rc` (48613 bytes, SHA256
8debe752a74eb73382de872638462e6869f50041d75bba9f66aa89e2e2530f12), with no
imports and with these intended rules:

| Node | Mode | Owner | Group |
| --- | --- | --- | --- |
| /dev/qseecom | 0660 | system | drmrpc |
| /dev/spcom | 0660 | system | system |
| /dev/ion | 0664 | system | system |

The existing P1 changes do not relocate or replace that file. Public-baseline
inspection run 42427694467 validates the Git blob identity before extracting
configuration. The baseline's first API property is 29, but it does not prove
the final Android property: donor properties and loading rules also matter.
AOSP ueventd has a canonical `/system/etc/ueventd.rc` which imports
`/vendor/etc/ueventd.rc`; legacy fallback can depend on first API level.
This upstream reference alone does not prove Xiaomi's actual import graph.

## Reversible candidate

The ready ENABLE ZIP adds only `/vendor/etc/ueventd.rc`, containing an import
of the unchanged, pinned original `/vendor/ueventd.rc`. It restores access to
the original rules through the canonical route without inventing node modes,
altering HAL users, changing properties, disabling encryption, deleting keys,
or modifying boot/super images. This is a candidate, not a confirmed boot fix.

The installer requires the real System partition to be mounted read-only as
EROFS in recovery and verifies that its actual ueventd configuration imports
the canonical Vendor path. It rejects absent/mismatched/ambiguous sources,
vendor hash drift, foreign existing canonical files, payload corruption and
unexpected labels/paths before activation. REMOVE deletes only the exact new
bridge. The original rules, existing BOOTDIAG V3 and saved metadata logs remain.
System is inspected only; no System remount or write is performed.

Ten focused tests cover preflight rejection, path escape/ambiguity, corruption,
label/remount/activation failure cleanup, reversible installation and original
mount mode, foreign-file preservation, CRC/SHA256 and a bounded import model.
The baseline/model test uses the tracked archive in a full checkout. It is
skipped in this partial local workspace, whose binary baseline is absent;
the release CI requires and independently pins that archive before running
all tests using real mksh. The model does not execute the OEM ueventd binary.
Hardware boot and the effective node modes still require confirmation.

The diagnostic reached its 1500-line bound early because repeated spcom/DSP
errors dominate logcat. Both later snapshots were still retained, which is
why the exact blocked vdc command is available. No private input logs are
included in this public report or in the published ZIPs.
