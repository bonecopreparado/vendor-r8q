"""Execute the recovery collector against bounded mock kernel/storage files."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/bootlog_collector.sh"
PACKAGER = ROOT / "tools/package_bootlog_collector.py"


class CollectorTests(unittest.TestCase):
    def run_fixture(self, base: Path, *, storage: str, large: bool = False, missing_tools: bool = False):
        paths = ["external_sd", "usb_otg", "storage/sdcard1", "storage/usb", "data", "sdcard", "tmp", "proc", "sys/fs/pstore", "bin"]
        for path in paths:
            (base / path).mkdir(parents=True, exist_ok=True)
        mounts = []
        if storage == "external":
            mounts.append(f"/dev/fake {base}/external_sd exfat rw 0 0\n")
        elif storage == "internal":
            mounts.append(f"/dev/fake {base}/data f2fs rw 0 0\n")
        (base / "proc/mounts").write_text("".join(mounts))
        for name in ["cmdline", "version", "uptime", "reset_reason"]:
            (base / "proc" / name).write_text(f"fixture-{name}\n")
        (base / "proc/last_kmsg").write_bytes(b"K" * (4194404 if large else 15))
        for i in range(9):
            (base / f"sys/fs/pstore/console-ramoops-{i}").write_bytes(b"P" * (2097252 if large and i == 0 else 30))
        (base / "tmp/recovery.log").write_text("CURRENT RECOVERY\n")
        protected = base / "block-target-do-not-change"
        protected.write_bytes(b"NOT A LOG: NEVER WRITE")
        sources = [protected, base / "proc/last_kmsg", *(base / "sys/fs/pstore").iterdir()]
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        for name, body in {
            "getprop": "printf 'fixture-property\\n'\n",
            "dmesg": "printf 'CURRENT RECOVERY KERNEL\\n'\n",
            "logcat": "printf 'CURRENT RECOVERY LOGCAT\\n'\n",
        }.items():
            p = base / "bin" / name
            p.write_text("#!/bin/sh\n" + body)
            p.chmod(0o755)
        script = SCRIPT.read_text()
        # Redirect every absolute input/output path into this fixture. Production
        # code has no environment-controlled test override or privileged path.
        for path in ["/sys/fs/pstore", "/external_sd", "/usb_otg", "/storage", "/sdcard", "/data", "/tmp", "/proc"]:
            script = re.sub(r"(?<![A-Za-z0-9_.-])" + re.escape(path), "@FIXTURE@" + path, script)
        script = script.replace("@FIXTURE@", str(base))
        runner = base / "run.sh"
        runner.write_text(script)
        if missing_tools:
            for command in ["awk", "date", "mkdir", "cat", "head", "wc", "tail", "rm", "sh", "printf"]:
                target = shutil.which(command)
                self.assertIsNotNone(target)
                (base / "bin" / command).symlink_to(target)
            path = str(base / "bin")
        else:
            path = str(base / "bin") + ":" + os.environ["PATH"]
        env = dict(os.environ, PATH=path)
        shell = shutil.which("mksh") or shutil.which("sh")
        self.assertIsNotNone(shell)
        proc = subprocess.run([shell, str(runner), "3", "", "unused.zip"], env=env, text=True, capture_output=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(proc.stderr, "", proc.stderr)
        expected = base / {"external": "external_sd", "internal": "sdcard", "volatile": "tmp"}[storage]
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
        self.assertFalse(list((base / "usb_otg").glob("R8Q-*")))
        if missing_tools:
            folder, = (p for p in expected.glob("R8Q-BOOTLOGS-*") if p.is_dir())
            return folder, proc.stdout
        archive, = expected.glob("R8Q-BOOTLOGS-*.tar.gz")
        self.assertLess(archive.stat().st_size, 32 * 1024 * 1024)
        return archive, proc.stdout

    def test_previous_boot_preserved_inputs_bounded_and_current_logs_labeled(self):
        with tempfile.TemporaryDirectory() as temp:
            archive, output = self.run_fixture(Path(temp), storage="external", large=True)
            with tarfile.open(archive, "r:gz") as tar:
                entries = {m.name.split("/", 1)[1]: m for m in tar.getmembers() if "/" in m.name}
                self.assertEqual(entries["previous-boot/last_kmsg.log"].size, 4194304)
                self.assertEqual(entries["previous-boot/pstore-1.log"].size, 2097152)
                self.assertEqual(len([n for n in entries if "pstore-" in n]), 8)
                index = tar.extractfile(entries["INDEX.txt"]).read().decode()
                self.assertIn("may be truncated", index)
                self.assertIn("more than 8 records", index)
                self.assertIn("CURRENT OrangeFox", index)
                self.assertEqual(tar.extractfile(entries["current-recovery/proc-cmdline.txt"]).read(), b"fixture-cmdline\n")
                self.assertIn("Missing/empty persistent records do NOT prove", index)
                self.assertNotIn("block-target", str(entries))
            self.assertIn(str(archive), output)

    def test_unmounted_external_directory_is_not_used(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            archive, _ = self.run_fixture(base, storage="internal")
            self.assertEqual(archive.parent, base / "sdcard")
            self.assertFalse(list((base / "external_sd").glob("R8Q-*")))

    def test_temporary_fallback_warns_before_reboot(self):
        with tempfile.TemporaryDirectory() as temp:
            archive, output = self.run_fixture(Path(temp), storage="volatile")
            self.assertEqual(archive.parent.name, "tmp")
            self.assertIn("WILL DISAPPEAR on reboot", output)

    def test_missing_timeout_skips_commands_and_missing_compression_keeps_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            folder, output = self.run_fixture(Path(temp), storage="internal", missing_tools=True)
            self.assertIn("Compression tools unavailable", output)
            index = (folder / "INDEX.txt").read_text()
            self.assertIn("SKIPPED current command (timeout unavailable): dmesg", index)
            self.assertIn("SKIPPED current command (timeout unavailable): logcat", index)
            self.assertTrue((folder / "previous-boot/last_kmsg.log").exists())
            self.assertFalse((folder / "current-recovery/dmesg.log").exists())

    def test_recovery_zip_has_executable_entrypoint_and_no_rom_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "collector.zip"
            subprocess.run(["python3", str(PACKAGER), "--output", str(output)], cwd=ROOT, check=True, capture_output=True)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(len(archive.namelist()), 4)
                self.assertEqual(archive.read("LICENSE.txt"), (ROOT / "LICENSE").read_bytes())
                info = archive.getinfo("META-INF/com/google/android/update-binary")
                self.assertEqual((info.external_attr >> 16) & 0o777, 0o755)
                self.assertEqual(archive.read(info), SCRIPT.read_bytes())
                self.assertIsNone(archive.testzip())
            self.assertEqual(output.with_name(output.name + ".sha256").read_text().split()[0], hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
