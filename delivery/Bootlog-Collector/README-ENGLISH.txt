R8Q READ-ONLY PREVIOUS-BOOT LOG COLLECTOR

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
