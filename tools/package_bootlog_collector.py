#!/usr/bin/env python3
"""Build a small phone-only OrangeFox ZIP that collects, never flashes, logs."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile

README = """R8Q READ-ONLY PREVIOUS-BOOT LOG COLLECTOR

This ZIP is a diagnostic tool, not a ROM or a bootloop fix. It does not flash
partitions, format data, mount partitions, clear logs or change the ROM.

PHONE-ONLY INSTRUCTIONS
1. Download R8Q-BOOTLOG-COLLECTOR.zip and verify its SHA256. Keep it compressed.
2. After one failed ROM boot, return directly to OrangeFox recovery. Avoid
   booting another ROM or restarting recovery again before collection.
3. OrangeFox > Files: select this ZIP and swipe to run the collector.
4. The screen prints the exact R8Q-BOOTLOGS-....tar.gz output path. Normally it
   selects an already-mounted external SD/USB, otherwise /sdcard (internal).
5. Send that .tar.gz file to the developer. Do not send this installer ZIP back.
   You can use a phone file manager after returning to a working ROM, or copy
   the output to external SD/USB from OrangeFox before restoring/formatting.
6. If output falls back to /tmp, COPY IT OUT BEFORE REBOOT: /tmp is temporary.
   If compression fails, copy and send the entire R8Q-BOOTLOGS-... folder.

previous-boot/ is persistent crash evidence if the kernel exposes it.
current-recovery/ is the current OrangeFox session, not a capture of ROM boot.
The collector bounds each input and documents missing/truncated files in
INDEX.txt. Missing pstore/last_kmsg does not prove the previous boot succeeded.

If OrangeFox cannot access the phone storage, mount your normal external
SD/USB using OrangeFox first and run this ZIP again. This tool never mounts it.
Do not format data merely to make collection work.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("delivery/Bootlog-Collector/R8Q-BOOTLOG-COLLECTOR.zip"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    script = (root / "bootlog_collector.sh").read_bytes()
    if not script.startswith(b"#!/sbin/sh\n") or b"\r" in script:
        raise ValueError("Expected LF-only recovery shell entry point")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data, mode in [
            ("META-INF/com/google/android/update-binary", script, 0o755),
            ("META-INF/com/google/android/updater-script", b"# Read-only shell collector.\n", 0o644),
            ("README-ENGLISH.txt", README.encode(), 0o644),
            ("LICENSE.txt", (root.parent / "LICENSE").read_bytes(), 0o644),
        ]:
            info = zipfile.ZipInfo(name, (2026, 11, 2, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_name(args.output.name + ".sha256").write_text(f"{digest}  {args.output.name}\n")
    (args.output.parent / "README-ENGLISH.txt").write_text(README)
    print(f"{args.output}: {args.output.stat().st_size} bytes\nSHA256 {digest}")


if __name__ == "__main__":
    main()
