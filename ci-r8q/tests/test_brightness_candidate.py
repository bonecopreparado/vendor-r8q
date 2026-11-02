"""Bounded real-shell tests of the optional normalized brightness conversion."""
from pathlib import Path
import os
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'patches/0006-hardware-adaptation/optional-brightness/brightness_sync.sh'
SHELL=os.environ.get('MKSH_BINARY') or shutil.which('mksh') or '/bin/sh'


class BrightnessCandidateTests(unittest.TestCase):
    def run_value(self,value,maximum):
        prefix=SOURCE.read_text().split('# Main loop.',1)[0]
        result=subprocess.run([SHELL,'-c',prefix+'\nscale_brightness "$1" "$2"','_',value,maximum],
                              capture_output=True,text=True,timeout=5)
        return result

    def test_normalized_values_and_actual_hardware_maximum(self):
        for value,maximum,expected in [('0','255','0'),('0.5','255','128'),('1','255','255'),
                                       ('0.5','4095','2048'),('0.5','65535','32768'),('1.0E-4','65535','7')]:
            with self.subTest(value=value,maximum=maximum):
                result=self.run_value(value,maximum)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout.strip(),expected)

    def test_unknown_brightness_does_not_produce_a_write_value(self):
        for value in ('','NaN','Infinity','-1','1.1','4095','Error: no display id specified','0.5\n1','$(id)','\\060.5'):
            with self.subTest(value=value):
                result=self.run_value(value,'255')
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(result.stdout,'')

    def test_invalid_or_overflowing_hardware_maximum_is_rejected(self):
        for maximum in ('','0','-1','65536','4294967296','255junk','255\n1','0255'):
            with self.subTest(maximum=maximum):
                result=self.run_value('0.5',maximum)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(result.stdout,'')


if __name__=='__main__':unittest.main()
