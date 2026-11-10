R8Q V4 RECOVERY LOG COLLECTOR - WINDOWS

This collects evidence that already exists. It does NOT install the v4 addon,
repair boot, restart the phone, format storage, clear logs, change properties,
or read private EFS/key files. It mounts only Metadata and Vendor through the
ordinary recovery mount command when they are not already mounted.

1. Put Collect-R8Q-V4.cmd in the SAME folder as adb.exe (platform-tools).
2. Connect the phone in normal OrangeFox/recovery ADB, outside ADB Sideload.
   Preserve the current failed-boot
   evidence: do not run another boot test, Format Data or erase captures first.
3. Run Collect-R8Q-V4.cmd. It accepts exactly one ready ADB device and checks
   recovery identity using only ro.bootmode and ro.orangefox.boot.
4. Read the final message. The script uses a new R8Q-LOGS-V4-... folder for
   every attempt, and all pulls go to that same folder.
5. Send the exact ZIP path printed by the script privately. Keep the folder
   until the evidence has been reviewed. Do not send an older empty ZIP.

Inputs are limited to:
 - /tmp/recovery.log (current recovery session; required and nonempty)
 - /proc/last_kmsg (previous kernel record, when exposed)
 - /metadata/r8q-bootdiag-v4 (existing Android v4 diagnostic captures)
 - /vendor/etc/ueventd.rc (the applied import bridge, when present)
 - /sys/fs/pstore (optional persistent kernel records)

COLLECTION-STATUS.txt keeps ADB errors and operation results. Device serials
are not intentionally stored as collection metadata. No broad getprop dump
is collected. Recovery logs describe recovery; they do not by themselves
identify the Android boot failure.

A COMPLETE archive means the requested primary reads succeeded and captured
files exist. It does not mean Android booted or that a HAL supplied every
requested field. Old and new v4 captures are copied together, without deletion.

A PARTIAL archive is explicitly named ...-PARTIAL.zip. It may still help when
last_kmsg or v4 evidence is unavailable. Send it with the error messages.
If recovery.log is absent/empty, or archive verification fails, the script
does not claim a valid completed collection. The partial folder is preserved.
Do not reboot merely to make another collection attempt; fix the shown ADB
or mount error first. A later run creates another fresh folder.

Host requirements: Windows 10/11, adb.exe and Windows PowerShell 5 with the
built-in Compress-Archive module. Paths are passed to PowerShell through
environment variables; spaces and apostrophes in folder names are not code.

Exit codes: 0 = complete archive; 2 = labeled partial archive; 1 = failure.
The script pauses so a double-click launch does not hide its error message.

Validation limitation: reviewed statically for CMD/PowerShell syntax and path
handling in a Linux workspace. It has NOT been executed on Windows or against
a connected phone here. The first Windows use must confirm the ADB commands
and archive result; no Windows runtime-test claim is made.
