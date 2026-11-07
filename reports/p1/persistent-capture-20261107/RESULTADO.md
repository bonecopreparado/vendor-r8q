# Android userspace capture remains necessary

The new `last_kmsg` reaches 301.173212 seconds in its most recent Android
segment. Userdata mounts as F2FS at 11.799697 seconds. The final recorded
init-child executable is `/system/bin/vdc` at 11.832127 seconds. No zygote or
app_process start is recorded after that point. These observations locate
the stall but do not identify the blocked vdc command or establish its cause.
Waiting longer or formatting data again is not justified by this evidence.

The earlier EROFS inline-symlink errors and BoringSSL-failure reboot do not
recur in this segment. The EROFS-COMPAT ROM remains the test base. No new ROM
or purported boot fix is produced from these incomplete userspace logs.

An init child executes `/system/bin/sh` at 6.078581 seconds, consistent with
the v2 diagnostic service starting early. Its identity is not proven by the
kernel exec record alone. There are no R8QBOOT messages in the supplied
files. The recovery log contains no retained addon installation history.
Absence of messages does not establish that the user failed to install it.
Why the kernel mirror failed to appear remains unresolved; this report does
not claim the Samsung kernel categorically discards userspace messages.

The two current-recovery logs describe OrangeFox, not the failed Android
userspace session. Their errors cannot establish which service holds boot.
The complete private input hashes and bounded findings are in evidence.json;
raw logs and device identifiers are not published.

## Diagnostic v3

The actual Android log shows metadata (`sda28`, ext4) mounted at 2.559780 s.
The recovery partition inventory independently identifies it as metadata.
Cache is `sda32`; no cache mount appears in the latest Android segment, so
the new capture must not assume cache is already available.

v3 preserves the asynchronous `on init` start and writes filtered Android
logcat and the two process snapshots into fresh private regular files under
`/metadata/r8q-bootdiag-v3/capture.XXXXXX/boot.log`. It does not depend on
`/dev/kmsg`, ADB being available in Android, or the userdata unlock completing.
The runtime verifies the existing metadata mount, physical partition identity,
ext4 and read/write mode, private directory ownership/mode and free space.
It never mounts, remounts or formats metadata and never opens existing key
files. No encryption/key handling is changed in the ROM.

Capture is bounded to 1500 logcat lines of 900 bytes and two snapshots of at
most 16 selected processes, with bounded command, wait-channel and stack
fields. The whitelist omits vdc password arguments. Each capture is below
2 MiB, at most four captures are retained, and starting requires at least
12 MiB free. Files are mode 0600 under mode 0700 directories. Prior evidence
is never overwritten or deleted. Removal stops the addon and leaves logs.

The v2 source recreates the exact previously published ZIP SHA256 values
before its payload bytes are preserved for guarded removal. V3 REMOVE
accepts only the pinned v1/v2/v3 payload hashes, including partial setups;
ENABLE requires removal before an upgrade. Unknown files remain protected.

Seventeen local tests pass using Bash, including simulated mount/path/space
failures, immutable previous captures, long input bounds, argument redaction,
installation rollback and both legacy upgrades. These fixtures do not execute
OEM init or prove that the diagnostic service will run on hardware. The
release workflow separately executes these tests using real mksh and attests
the ready ZIPs before publication. Hardware capture is still required.
