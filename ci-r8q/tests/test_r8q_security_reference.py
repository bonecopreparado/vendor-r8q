"""Behavioral regression checks for the pinned R8Q static security contract."""
from pathlib import Path
import importlib.util
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('r8q_security_contract',ROOT/'tools/audit_r8q_security_reference.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class Tests(unittest.TestCase):
    def fixture(self,strongbox=True):
        files={'build.prop':b'ro.hardware.gatekeeper=mdfpp\nro.hardware.keystore=mdfpp\nro.product.first_api_level=29\n',
               'etc/init/gk.rc':b'service samsung-gk /vendor/bin/hw/android.hardware.gatekeeper@1.0-service\n    interface android.hardware.gatekeeper@1.0::IGatekeeper mdfpp\n',
               'etc/init/gk-qti.rc':b'service qti-gk /vendor/bin/hw/android.hardware.gatekeeper@1.0-service-qti\n    class early_hal\n',
               'etc/init/km.rc':b'service samsung-km /vendor/bin/hw/android.hardware.keymaster@4.0-service\n    interface android.hardware.keymaster@4.0::IKeymasterDevice default\n'}
        sb='<instance>strongbox</instance>'if strongbox else''
        files['etc/vintf/manifest.xml']=('''<manifest version="2.0" type="device">
<hal format="hidl"><name>android.hardware.gatekeeper</name><version>1.0</version><interface><name>IGatekeeper</name><instance>default</instance><instance>mdfpp</instance></interface></hal>
<hal format="hidl"><name>android.hardware.keymaster</name><version>4.0</version><interface><name>IKeymasterDevice</name><instance>default</instance>'''+sb+'''</interface></hal></manifest>''').encode()
        fstab=b'''vendor /vendor ext4 ro wait,logical,first_stage_mount
/dev/block/bootdevice/by-name/userdata /data f2fs noatime,inlinecrypt wait,fileencryption=ice
/dev/block/bootdevice/by-name/apnhlos /vendor/firmware_mnt vfat ro,context=u:object_r:firmware_file:s0 wait
/dev/block/bootdevice/by-name/modem /vendor/firmware-modem vfat ro,context=u:object_r:firmware_file:s0 nofail
'''
        return files,fstab

    def test_valid_qti_and_mdfpp_companions_are_not_reported_as_a_duplicate_bug(self):
        f,t=self.fixture();r=audit.audit(f,t)
        self.assertIn('retained_and_valid',r['gatekeeper_coexistence'])
        self.assertFalse(r['runtime_boot_confirmed'])

    def test_strongbox_is_observed_without_disabling_it_or_replacing_default_tee(self):
        for present in [False,True]:
            f,t=self.fixture(present);r=audit.audit(f,t)
            self.assertEqual(r['strongbox'],'declared_vendor_instance_not_removed'if present else'not_declared')
            self.assertTrue(r['default_keymaster']['executable'].endswith('@4.0-service'))

    def test_missing_mandatory_default_tee_is_rejected_even_with_strongbox(self):
        f,t=self.fixture();root=ET.fromstring(f['etc/vintf/manifest.xml'])
        for hal in root.findall('hal'):
            if hal.findtext('name')!='android.hardware.keymaster':continue
            interface=hal.find('interface')
            for instance in list(interface.findall('instance')):
                if instance.text=='default':interface.remove(instance)
        f['etc/vintf/manifest.xml']=ET.tostring(root)
        with self.assertRaisesRegex(ValueError,'default TEE'):audit.audit(f,t)

    def test_wrong_or_conflicting_samsung_module_selectors_are_rejected(self):
        for addition in [b'ro.hardware.keystore=qcom\n',b'ro.hardware.gatekeeper=default\n']:
            f,t=self.fixture();f['build.prop']+=addition
            with self.assertRaisesRegex(ValueError,'Conflicting'):audit.audit(f,t)

    def test_an_upstream_filesystem_or_crypto_migration_requires_separate_review(self):
        for old,new,pattern in [(b'vendor /vendor ext4',b'vendor /vendor erofs','EROFS'),(b'fileencryption=ice',b'fileencryption=aes-256-xts:aes-256-cts:v2','migration')]:
            f,t=self.fixture()
            with self.assertRaisesRegex(ValueError,pattern):audit.audit(f,t.replace(old,new))

    def test_wrong_device_firmware_partition_or_readwrite_firmware_mount_is_rejected(self):
        for old,new in [(b'by-name/apnhlos',b'by-name/efs'),(b'vfat ro,',b'vfat rw,')]:
            f,t=self.fixture()
            with self.assertRaisesRegex(ValueError,'firmware mount'):audit.audit(f,t.replace(old,new))

    def test_duplicate_default_service_configuration_is_rejected(self):
        f,t=self.fixture();f['etc/init/km-extra.rc']=b'service second-km /vendor/bin/hw/second-keymaster\n    interface android.hardware.keymaster@4.0::IKeymasterDevice default\n'
        with self.assertRaisesRegex(ValueError,'absent or ambiguous'):audit.audit(f,t)


if __name__=='__main__':unittest.main()
