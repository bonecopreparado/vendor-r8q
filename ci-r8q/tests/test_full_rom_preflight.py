"""Run the actual read-only stock-firmware preflight in private shell fixtures."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from p1_single_template import template
from vendor_security.full_rom import payloads
SHELL=os.environ.get('MKSH_BINARY',shutil.which('bash'))


class Tests(unittest.TestCase):
    def fixture(self,flags=None):
        t=tempfile.TemporaryDirectory(prefix='r8q-stock-preflight-');self.addCleanup(t.cleanup)
        r=Path(t.name);(r/'bin').mkdir();(r/'work').mkdir();(r/'stock').mkdir();(r/'device').write_bytes(b'fixture')
        for name,data in payloads().items():(r/'stock'/name).write_bytes(data)
        (r/'flags').write_text(json.dumps(flags or {}));(r/'mounts').write_text('')
        source=template(build_label='P1r5')
        begin=source.index('STOCK_MOUNTED=0\n');end=source.index('ui_print "P1r5: Samsung firmware profile matches;',begin)
        end=source.index('\n',end)+1;guard=source[begin:end]
        guard=guard.replace('/dev/block/bootdevice/by-name/apnhlos',str(r/'device'))
        guard=guard.replace('/proc/mounts',str(r/'mounts')).replace('[ -b "$APNHLOS_REAL" ]','[ -f "$APNHLOS_REAL" ]')
        header='set -eu\nset -o pipefail\nWORK='+str(r/'work')+'\nZIPREAD='+str(r/'bin/helper')+'''\nui_print() { printf '%s\\n' "$*"; }
abort() { ui_print "ERROR: $*"; exit 1; }
'''
        (r/'script').write_text(header+guard)
        prelude='#!/usr/bin/env python3\nimport json,sys,shutil\nfrom pathlib import Path\nr=Path('+repr(str(r))+')\nflags=json.loads((r/"flags").read_text())\n'
        mount=prelude+'''args=sys.argv[1:]
assert args[:4]==['-t','vfat','-o','ro']
with (r/'events').open('a')as f:f.write('mount-ro\\n')
target=Path(args[-1]);shutil.copytree(r/'stock',target/'image')
if flags.get('tamper'):(target/'image/ipa_uc.b02').write_bytes(b'wrong firmware')
device=str(r/'wrong')if flags.get('device')else args[-2]
options='rw'if flags.get('rw')else 'ro'
(r/'mounts').write_text(device+' '+str(target)+' vfat '+options+',relatime 0 0\\n')
'''
        unmount=prelude+'''target=Path(sys.argv[1]);assert target==r/'work/stock-fw'
with (r/'events').open('a')as f:f.write('umount\\n')
if (target/'image').exists():shutil.rmtree(target/'image')
(r/'mounts').write_text('')
'''
        for name,body in [('mount',mount),('umount',unmount),('helper',"#!/bin/sh\nprintf 'R8Q_BLOCK_IO_DIRECT_V1\\n'\n")]:
            p=r/'bin'/name;p.write_text(body);p.chmod(0o755)
        return r

    def run_script(self,r):
        return subprocess.run([SHELL,str(r/'script')],env=dict(os.environ,PATH=str(r/'bin')+os.pathsep+os.environ['PATH']),
                              capture_output=True,text=True,timeout=15)

    def test_matching_actual_stock_programs_pass_and_mount_is_released(self):
        r=self.fixture();result=self.run_script(r)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('firmware profile matches',result.stdout)
        self.assertEqual((r/'events').read_text(),'mount-ro\numount\n')
        self.assertFalse((r/'work').exists())

    def test_firmware_mismatch_or_wrong_mount_is_rejected_and_cleaned_up(self):
        for flag in ('tamper','rw','device'):
            with self.subTest(flag=flag):
                r=self.fixture({flag:True});result=self.run_script(r)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertIn('Nothing was written',result.stdout)
                self.assertIn('umount',(r/'events').read_text());self.assertEqual((r/'mounts').read_text(),'')

    def test_full_rom_requires_stock_and_direct_io_guards_before_any_image_write(self):
        script=template(build_label='P1r5')
        guard=script.index('Stock firmware differs:');probe=script.index('# Exercise flush permissions')
        self.assertLess(guard,probe);self.assertLess(probe,script.index('stream_image super | write_tail'))
        self.assertIn('[ -b "$APNHLOS_REAL" ]',script)
        self.assertIn('R8Q_BLOCK_IO_DIRECT_V1',script);self.assertIn('flags != 3',script)
        self.assertNotIn('cb9c55af64889209',script)
        self.assertNotIn('dd bs=4096 count="$((length/4096))"',script)


if __name__=='__main__':unittest.main()
