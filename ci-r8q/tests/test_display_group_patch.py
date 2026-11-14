"""Regression tests without redistributing the private OEM binaries."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch as mock_patch
try:
    import unicorn
except ImportError:
    unicorn = None

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('display_group_patch', ROOT/'tools/display_group/patch_surfaceflinger.py')
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


def fixture():
    """Synthetic ELF, deliberately different hashes and file offset from OEM."""
    data = bytearray(4096)
    ident = b'\x7fELF\x02\x01\x01' + bytes(9)
    struct.pack_into('<16sHHIQQQIHHHHHH', data, 0, ident, 3, 183, 1, 0, 64, 0, 0, 64, 56, 2, 0, 0, 0)
    struct.pack_into('<IIQQQQQQ', data, 64, 1, 5, 0x300, patch.VA - 0x100, 0, 0x700, 0x700, 0x1000)
    note = struct.pack('<III', 4, len(bytes.fromhex(patch.BUILD_ID)), 3) + b'GNU\0' + bytes.fromhex(patch.BUILD_ID)
    note += bytes((-len(note)) % 4)
    struct.pack_into('<IIQQQQQQ', data, 120, 4, 4, 0x200, 0x200, 0, len(note), len(note), 4)
    data[0x200:0x200 + len(note)] = note
    data[0x400 - 12:0x400 + 20] = patch.CONTEXT
    return bytes(data)


class ExactPatchTests(unittest.TestCase):
    def setUp(self):
        self.before = fixture()
        self.after = self.before[:0x400] + patch.PATCHED + self.before[0x404:]
        self.mock = mock_patch.multiple(patch, SIZE=len(self.before), OFFSET=0x400,
            ORIGINAL_SHA256=patch.sha(self.before), PATCHED_SHA256=patch.sha(self.after))
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_exact_forward_and_reverse(self):
        self.assertEqual(patch.transform(self.before), self.after)
        self.assertEqual(patch.transform(self.after, reverse=True), self.before)
        self.assertEqual([i for i, (a, b) in enumerate(zip(self.before, self.after)) if a != b], [0x401, 0x403])

    def test_wrong_or_already_patched_input_rejected(self):
        for data in (self.before[:-1], self.before + b'0', self.after, bytes(len(self.before))):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                patch.transform(data)

    def test_unknown_file_same_size_rejected(self):
        data = bytearray(self.before)
        data[-1] ^= 1
        with self.assertRaises(ValueError):
            patch.transform(bytes(data))

    def test_structural_guards_independent_of_hash(self):
        # Re-pin each malformed fixture to exercise guards after the whole-file
        # hash, rather than merely re-testing a failed hash for every mutation.
        mutations = ((0, b'BAD!'), (18, struct.pack('<H', 62)),
            (64 + 4, struct.pack('<I', 4)), (64 + 8, struct.pack('<Q', 0x301)),
            (0x210, b'\0'), (0x400, b'\0'))
        for off, value in mutations:
            data = bytearray(self.before)
            data[off:off + len(value)] = value
            with self.subTest(offset=off), mock_patch.object(patch, 'ORIGINAL_SHA256', patch.sha(data)):
                with self.assertRaises(ValueError):
                    patch.verify(bytes(data))

    def test_existing_destination_and_symlink_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'target'
            target.write_bytes(b'keep')
            link = Path(folder)/'link'
            link.symlink_to(target)
            for path in (target, link):
                with self.assertRaises(FileExistsError):
                    patch.write_new(path, self.after)
            self.assertEqual(target.read_bytes(), b'keep')

    def test_new_file_readback(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'candidate'
            patch.write_new(target, patch.transform(self.before))
            self.assertEqual(patch.verify(target.read_bytes(), patched=True), patch.PATCHED_SHA256)


@unittest.skipIf(unicorn is None, 'Optional ARM64 emulator: run the dedicated display-group32 CI for these tests')
class Arm64ComparisonTests(unittest.TestCase):
    def compare(self, candidate, default, corrected):
        from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
        from unicorn.arm64_const import UC_ARM64_REG_X8, UC_ARM64_REG_X19, UC_ARM64_REG_NZCV
        # The three actual instructions around the defective comparison. No
        # entire OEM function or library is embedded in this test.
        instructions = bytes.fromhex('6a3240b9') + (patch.PATCHED if corrected else patch.ORIGINAL) + bytes.fromhex('5f01086b')
        emulator = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        emulator.mem_map(0x1000, 0x4000)
        emulator.mem_write(0x1000, instructions)
        emulator.mem_write(0x3030, struct.pack('<i', candidate))
        emulator.mem_write(0x4030, struct.pack('<i', default))
        emulator.reg_write(UC_ARM64_REG_X19, 0x3000)
        emulator.reg_write(UC_ARM64_REG_X8, 0x4000)
        emulator.emu_start(0x1000, 0x1000 + len(instructions), count=3)
        return bool(emulator.reg_read(UC_ARM64_REG_NZCV) & (1 << 30))

    def test_1080_group_repro_and_false_positive_removed(self):
        self.assertFalse(self.compare(1080, 1080, False))
        self.assertTrue(self.compare(56, 1080, False))
        self.assertTrue(self.compare(1080, 1080, True))
        self.assertFalse(self.compare(56, 1080, True))

    def test_full_int32_identity_and_group_separation(self):
        values = (-2147483648, -1, 0, 1, 56, 255, 256, 1080, 1081, 2147483647)
        for candidate in values:
            for default in values:
                with self.subTest(candidate=candidate, default=default):
                    self.assertEqual(self.compare(candidate, default, True), candidate == default)


if __name__ == '__main__':
    unittest.main()
