"""Input/ELF checks; these never pretend to exercise Android Binder or HWC."""
from pathlib import Path
import hashlib
import importlib.util
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('composer_dump_build', ROOT / 'tools/display_probe/build_probe.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class ElfTests(unittest.TestCase):
    def fixtures(self):
        return [
            "Class: ELF64\nData: 2's complement, little endian\nType: DYN (Shared object file)\nMachine: AArch64\n",
            '[Requesting program interpreter: /system/bin/linker64]\n',
            ''.join('0x1 (NEEDED) Shared library: [' + name + ']\n' for name in sorted(helper.REQUIRED_NEEDED))
                + '0x6ffffffb (FLAGS_1) Flags: NOW PIE\n',
            'U android::hardware::graphics::composer::V2_1::IComposer::tryGetService(std::__1::basic_string<char>, bool)\n',
        ]

    def test_reviewed_arm64_platform_hidl_dependencies_pass_without_phone_claim(self):
        result = helper.inspect_elf(*self.fixtures())
        self.assertEqual(set(result['needed']), helper.REQUIRED_NEEDED)
        self.assertFalse(result['phone_linker_compatibility_confirmed'])

    def test_architecture_endian_type_interpreter_and_pie_are_not_waived(self):
        changes = [(0, 'AArch64', 'X86-64'), (0, 'ELF64', 'ELF32'),
                   (0, 'little endian', 'big endian'), (0, 'Type: DYN', 'Type: EXEC'),
                   (1, '/system/bin/linker64', '/lib/ld-linux-aarch64.so.1'),
                   (2, 'NOW PIE', 'NOW')]
        for index, before, after in changes:
            with self.subTest(change=(before, after)):
                fixtures = self.fixtures()
                fixtures[index] = fixtures[index].replace(before, after)
                with self.assertRaises(ValueError):
                    helper.inspect_elf(*fixtures)

    def test_missing_hidl_or_unreviewed_extra_library_fails(self):
        for extra in ('0x1 (NEEDED) Shared library: [libprivatevendor.so]\n', ''):
            fixtures = self.fixtures()
            if extra:
                fixtures[2] += extra
            else:
                fixtures[2] = fixtures[2].replace('android.hardware.graphics.composer@2.1.so', 'libdifferent.so')
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                helper.inspect_elf(*fixtures)

    def test_rpath_runpath_and_text_relocations_fail(self):
        for tag in ('RPATH', 'RUNPATH', 'TEXTREL'):
            fixtures = self.fixtures()
            fixtures[2] += f'0x1 ({tag}) /vendor/lib64\n'
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                helper.inspect_elf(*fixtures)

    def test_ndk_stl_namespace_and_missing_hidl_lookup_fail(self):
        for replacement in ('std::__ndk1::basic_string', 'std::basic_string'):
            fixtures = self.fixtures()
            fixtures[3] = fixtures[3].replace('std::__1::basic_string', replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                helper.inspect_elf(*fixtures)
        fixtures = self.fixtures()
        fixtures[3] = fixtures[3].replace('IComposer::tryGetService', 'SomeOtherLookup')
        with self.assertRaises(ValueError):
            helper.inspect_elf(*fixtures)


class ArchiveTests(unittest.TestCase):
    def test_archive_uses_published_length_and_content_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'ndk.zip'
            content = b'small verified archive fixture'
            archive.write_bytes(content)
            with mock.patch.object(helper, 'NDK_BYTES', len(content)), mock.patch.object(
                    helper, 'NDK_SHA1', hashlib.sha1(content).hexdigest()):
                result = helper.verify_ndk_archive(archive)
                self.assertEqual(result['sha256'], hashlib.sha256(content).hexdigest())
                archive.write_bytes(b'x' * len(content))
                with self.assertRaisesRegex(ValueError, 'SHA1'):
                    helper.verify_ndk_archive(archive)

    def test_short_missing_and_symlinked_archives_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'ndk.zip'
            with self.assertRaises(ValueError):
                helper.verify_ndk_archive(archive)
            archive.write_bytes(b'x')
            with self.assertRaises(ValueError):
                helper.verify_ndk_archive(archive)
            symlink = Path(directory) / 'link.zip'
            symlink.symlink_to(archive)
            with self.assertRaises(ValueError):
                helper.verify_ndk_archive(symlink)


if __name__ == '__main__':
    unittest.main()
