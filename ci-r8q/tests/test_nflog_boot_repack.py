"""Exercise preservation/rejection with synthetic boot files, never devices."""
from pathlib import Path
import importlib.util,struct,unittest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('nflog_repack',ROOT/'tools/kernel_nflog/repack_boot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
    def image(self,size=1024,fill=13):
        b=bytearray([fill]*size);struct.pack_into('<Q',b,8,0x80000);struct.pack_into('<Q',b,16,0x100000);struct.pack_into('<Q',b,24,10);b[56:60]=b'ARM\x64';return bytes(b)
    def boot(self):
        header=bytearray(4096);header[:8]=b'ANDROID!';struct.pack_into('<10I',header,8,1024,0x80008000,333,0x81000000,0,0,0x80000100,4096,2,0);struct.pack_into('<I',header,1644,1660);struct.pack_into('<I',header,1648,511);header[64:64+len(b'androidboot.test=preserved!')]=b'androidboot.test=preserved!';parts={'kernel':self.image(),'ramdisk':b'R'*333,'second':b'','recovery_dtbo':b'','dtb':b'D'*511};header[576:608]=m.boot_id(parts)
        b=bytearray(header)
        for n in ['kernel','ramdisk','second','recovery_dtbo','dtb']:b.extend(parts[n]);b.extend(bytes(m.align(len(b),4096)-len(b)))
        b.extend(b'SEANDROIDENFORCE\0');b.extend(bytes(32768-len(b)));return bytes(b)
    def test_changed_kernel_preserves_ramdisk_dtb_cmdline_addresses_and_capacity(self):
        old=self.boot();new,report=m.repack_bytes(old,self.image(7000,27));self.assertEqual(len(old),len(new));self.assertNotEqual(old,new)
        before=m.sections(old);after=m.sections(new)
        for n in ['ramdisk','dtb','second','recovery_dtbo']:self.assertEqual(before[n],after[n])
        self.assertEqual(old[12:576],new[12:576]);self.assertEqual(old[608:4096],new[608:4096]);self.assertFalse(report['hardware_boot_confirmed'])
    def test_unchanged_kernel_is_byte_identical(self):
        old=self.boot();new,_=m.repack_bytes(old,self.image());self.assertEqual(old,new)
    def test_invalid_boot_id_and_unknown_trailer_rejected(self):
        b=bytearray(self.boot());b[576]^=1
        with self.assertRaisesRegex(ValueError,'boot ID'):m.repack_bytes(bytes(b),self.image())
        b=bytearray(self.boot());p=16384;b[p]=88
        with self.assertRaisesRegex(ValueError,'trailer'):m.repack_bytes(bytes(b),self.image())
    def test_non_arm64_kernel_and_changed_load_parameters_rejected(self):
        for kernel in [b'bad',b'\0'*1024]:
            with self.assertRaisesRegex(ValueError,'ARM64'):m.repack_bytes(self.boot(),kernel)
        for offset in [8,24]:
            k=bytearray(self.image());k[offset]^=1
            with self.assertRaisesRegex(ValueError,'load offset'):m.repack_bytes(self.boot(),bytes(k))
    def test_oversized_kernel_cannot_expand_boot_partition(self):
        with self.assertRaisesRegex(ValueError,'capacity'):m.repack_bytes(self.boot(),self.image(32768))
    def test_invalid_arm64_memory_size_rejected(self):
        k=bytearray(self.image());struct.pack_into('<Q',k,16,64)
        with self.assertRaisesRegex(ValueError,'memory size'):m.repack_bytes(self.boot(),bytes(k))
if __name__=='__main__':unittest.main()
