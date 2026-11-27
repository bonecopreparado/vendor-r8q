"""Unit tests for Vendor/ODM/Product/Boot audit fixes, VNDK-30 Keymaster reorder, and G780G/G781B IPA preflight."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from p1_single_template import template
from p1r5_installer import G780G_EYJ1_STOCK
from vendor_security import audit_fixes, keymaster_tee

SHELL = os.environ.get('MKSH_BINARY', shutil.which('bash'))


class Tests(unittest.TestCase):
    def test_clean_vendor_manifest_strips_strongbox_and_ghost_hals(self):
        sample = (
            '<manifest version="1.0" type="device">\n'
            '    <hal format="hidl" override="true">\n'
            '        <name>android.hardware.contexthub</name>\n'
            '        <transport>hwbinder</transport>\n'
            '        <version>1.0</version>\n'
            '    </hal>\n'
            '    <hal format="hidl" override="true">\n'
            '        <name>android.hardware.keymaster</name>\n'
            '        <transport>hwbinder</transport>\n'
            '        <version>4.0</version>\n'
            '        <interface>\n'
            '            <name>IKeymasterDevice</name>\n'
            '            <instance>default</instance>\n'
            '            <instance>strongbox</instance>\n'
            '        </interface>\n'
            '        <fqname>@4.0::IKeymasterDevice/default</fqname>\n'
            '        <fqname>@4.0::IKeymasterDevice/strongbox</fqname>\n'
            '    </hal>\n'
            '    <hal format="hidl">\n'
            '        <name>vendor.qti.hardware.soter</name>\n'
            '        <transport>hwbinder</transport>\n'
            '    </hal>\n'
            '</manifest>\n'
        ).encode('utf-8')
        cleaned = audit_fixes.clean_vendor_manifest(sample).decode('utf-8')
        self.assertIn('<instance>default</instance>', cleaned)
        self.assertIn('@4.0::IKeymasterDevice/default', cleaned)
        self.assertNotIn('strongbox', cleaned)
        self.assertNotIn('contexthub', cleaned)
        self.assertNotIn('vendor.qti.hardware.soter', cleaned)

    def test_unify_fstab_fbe2_updates_ice_and_adds_erofs_and_system_ext(self):
        sample = (
            'product\t/product\text4\tro\twait,avb,logical,first_stage_mount\n'
            '/dev/block/platform/soc/1d84000.ufshc/by-name/prism     /prism                 ext4    ro,barrier=1,discard                                 nofail,avb,first_stage_mount\n'
            '/dev/block/platform/soc/1d84000.ufshc/by-name/optics    /optics                ext4    ro,barrier=1,discard                                 nofail,avb,first_stage_mount\n'
            '/dev/block/bootdevice/by-name/userdata\t/data\tf2fs\tnoatime,nosuid,nodev\tlatemount,wait,check,fileencryption=ice,quota,reservedsize=128M,checkpoint=fs\n'
            '/dev/block/bootdevice/by-name/keydata\t/keydata\text4\tnoatime,inlinecrypt\twait,check,fileencryption=ice,nofail\n'
        ).encode('utf-8')
        updated = audit_fixes.unify_fstab_fbe2(sample).decode('utf-8')
        self.assertIn('product\t/product\terofs\t', updated)
        self.assertIn('system_ext\t/system_ext\terofs\t', updated)
        self.assertIn('inlinecrypt', updated)
        self.assertIn('fileencryption=aes-256-xts:aes-256-cts:v2+inlinecrypt_optimized', updated)
        self.assertIn('keydirectory=/metadata/vold/metadata_encryption', updated)
        self.assertNotIn('fileencryption=ice', updated)
        self.assertNotIn('nofail,avb,first_stage_mount', updated)

    def test_ramplus_ueventd_brightness_and_bpf_transforms(self):
        ramplus = audit_fixes.fix_fstab_ramplus(b'/dev/block/zram0 none swap defaults zramsize=12147483648,auto_configure\n')
        self.assertIn(b'zramsize=2147483648', ramplus)

        ueventd = audit_fixes.fix_ueventd_rc(b'/sys/class/graphics/fb0 modes 0664 system graphics\n*/\n#next\n')
        self.assertNotIn(b'*/', ueventd)

        qcom = audit_fixes.strip_brightness_sync(
            b'# end\n\n service brightness_sync /vendor/bin/brightness_sync.sh\n   class late_start\n   user root\n   seclabel u:r:system_server:s0\n\nservice next /vendor/bin/next\n'
        )
        self.assertNotIn(b'brightness_sync.sh', qcom)
        self.assertIn(b'service next /vendor/bin/next', qcom)

        prop = audit_fixes.add_bpf_override(b'ro.product.model=r8q\n')
        self.assertIn(b'ro.bpf.kver_override=5.10.239\n', prop)
        self.assertEqual(audit_fixes.add_bpf_override(prop), prop)

    def test_encode_vfs_cap_v2_matches_linux_layout(self):
        cap_hex = audit_fixes.encode_vfs_cap_v2((audit_fixes.CAP_NET_BIND_SERVICE,))
        magic, perm_lo, inh_lo, perm_hi, inh_hi = struct.unpack('<5I', bytes.fromhex(cap_hex))
        self.assertEqual(magic, 0x02000001)
        self.assertEqual(perm_lo, 1 << 10)
        self.assertEqual((inh_lo, perm_hi, inh_hi), (0, 0, 0))

        cap_bt = audit_fixes.encode_vfs_cap_v2((audit_fixes.CAP_NET_ADMIN, audit_fixes.CAP_BLOCK_SUSPEND))
        _, perm_lo, _, perm_hi, _ = struct.unpack('<5I', bytes.fromhex(cap_bt))
        self.assertEqual(perm_lo, 1 << 12)
        self.assertEqual(perm_hi, 1 << (36 - 32))

    def test_reorder_needed_vndk30_swaps_dt_needed_without_changing_size(self):
        # Construct minimal valid AArch64 ELF64 with .dynstr and .dynamic
        strtab = b'\x00libkeymaster4.so\x00libskeymaster4device.so\x00libc.so\x00'
        off_km4 = strtab.index(b'libkeymaster4.so')
        off_skm = strtab.index(b'libskeymaster4device.so')
        off_c = strtab.index(b'libc.so')
        dyn = (
            struct.pack('<QQ', 1, off_km4)
            + struct.pack('<QQ', 1, off_skm)
            + struct.pack('<QQ', 1, off_c)
            + struct.pack('<QQ', 0, 0)
        )
        ehdr_size = 64
        str_off = ehdr_size
        dyn_off = str_off + len(strtab)
        sh_off = dyn_off + len(dyn)
        ehdr = bytearray(64)
        ehdr[0:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', ehdr, 18, 183)  # EM_AARCH64
        struct.pack_into('<Q', ehdr, 40, sh_off)
        struct.pack_into('<HH', ehdr, 58, 64, 3)  # shentsize=64, shnum=3
        sh_null = bytes(64)
        sh_str = struct.pack('<IIQQQQIIQQ', 0, 3, 0, 0, str_off, len(strtab), 0, 0, 1, 0)
        sh_dyn = struct.pack('<IIQQQQIIQQ', 0, 6, 0, 0, dyn_off, len(dyn), 1, 0, 8, 16)
        raw = bytes(ehdr) + strtab + dyn + sh_null + sh_str + sh_dyn

        patched = keymaster_tee.reorder_needed_vndk30(raw)
        self.assertEqual(len(patched), len(raw))
        t0, v0 = struct.unpack_from('<QQ', patched, dyn_off)
        t1, v1 = struct.unpack_from('<QQ', patched, dyn_off + 16)
        self.assertEqual((t0, v0, t1, v1), (1, off_skm, 1, off_km4))
        # Idempotent if already ordered
        self.assertEqual(keymaster_tee.reorder_needed_vndk30(patched), patched)

    def test_p1r5_preflight_accepts_g780g_eyj1_profile_and_stages_sync(self):
        with tempfile.TemporaryDirectory(prefix='r8q-g780g-preflight-') as tmp:
            r = Path(tmp)
            (r / 'bin').mkdir()
            (r / 'work').mkdir()
            (r / 'stock').mkdir()
            (r / 'device').write_bytes(b'fixture')
            (r / 'mounts').write_text('')
            # Populate fake G780G stock files whose sha256sum is returned by stubbed sha256sum
            g780g_map = dict(G780G_EYJ1_STOCK)
            for name in g780g_map:
                (r / 'stock' / name).write_text(name)
            source = template(build_label='P1r5')
            begin = source.index('STOCK_MOUNTED=0\n')
            end = source.index('ui_print "P1r5: Samsung firmware profile matches;', begin)
            end = source.index('\n', end) + 1
            guard = source[begin:end]
            guard = guard.replace('/dev/block/bootdevice/by-name/apnhlos', str(r / 'device'))
            guard = guard.replace('/proc/mounts', str(r / 'mounts')).replace('[ -b "$APNHLOS_REAL" ]', '[ -f "$APNHLOS_REAL" ]')
            header = (
                f'set -eu\nset -o pipefail\nWORK={r / "work"}\nZIPREAD={r / "bin/helper"}\n'
                'ui_print() { printf \'%s\\n\' "$*"; }\n'
                'abort() { ui_print "ERROR: $*"; exit 1; }\n'
            )
            (r / 'script').write_text(header + guard)
            (r / 'bin/mount').write_text(
                f'#!/usr/bin/env python3\nimport shutil, sys\nfrom pathlib import Path\n'
                f'r = Path({str(r)!r})\ntarget = Path(sys.argv[-1])\n'
                f'shutil.copytree(r / "stock", target / "image")\n'
                f'(r / "mounts").write_text(sys.argv[-2] + " " + str(target) + " vfat ro,relatime 0 0\\n")\n'
            )
            (r / 'bin/umount').write_text(
                f'#!/usr/bin/env python3\nimport shutil, sys\nfrom pathlib import Path\n'
                f'r = Path({str(r)!r})\ntarget = Path(sys.argv[1])\n'
                f'if (target / "image").exists(): shutil.rmtree(target / "image")\n'
                f'(r / "mounts").write_text("")\n'
            )
            (r / 'bin/sha256sum').write_text(
                f'#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n'
                f'm = {g780g_map!r}\np = Path(sys.argv[1])\n'
                f'print(m[p.name], str(p))\n'
            )
            (r / 'bin/helper').write_text('#!/bin/sh\nprintf "R8Q_BLOCK_IO_DIRECT_V1\\n"\n')
            for tool in ('mount', 'umount', 'sha256sum', 'helper'):
                (r / 'bin' / tool).chmod(0o755)
            res = subprocess.run(
                [SHELL, str(r / 'script')],
                env=dict(os.environ, PATH=str(r / 'bin') + os.pathsep + os.environ['PATH']),
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn('G780G Vendor IPA will sync', res.stdout)
            self.assertFalse((r / 'work').exists())


if __name__ == '__main__':
    unittest.main()
