from pathlib import Path
import hashlib
import importlib.util
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('v6_image_plan',ROOT/'tools/bootdiag_v6/image_plan.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Tests(unittest.TestCase):
    def fixture(self):
        return dict(schema_version=1,source_image_sha256='0'*64,
                    operations=[dict(op='delete',path='/old-cache',old_sha256='1'*64)])

    def test_validated_helper_hash_paths_metadata_and_licenses_are_bound(self):
        plan=self.fixture()
        helper=b'fixture only; real ELF is validated by the native build validator'
        licenses={'licenses/fixture.txt':b'notice'}
        with patch.object(module.render.previous,'validate_probe',return_value=(helper,{'fixture':True},licenses)) as validate:
            result,payloads,notices,evidence=module.add_diagnostics(plan,Path('reviewed-probe'))
        validate.assert_called_once_with(Path('reviewed-probe'))
        self.assertEqual(len(plan['operations']),1)
        self.assertEqual(result['operations'][0],plan['operations'][0])
        self.assertEqual(len(result['operations']),4)
        for row in result['operations'][1:]:
            self.assertEqual(row['op'],'add')
            self.assertEqual(hashlib.sha256(payloads[row['source']]).hexdigest(),row['sha256'])
            if row['path'].startswith('/bin/'):
                self.assertEqual(row['metadata_from'],'/bin/init.qti.qcv.sh')
        sha=hashlib.sha256(helper).hexdigest()
        runtime=payloads['candidate/vendor/bin/r8q-bootdiag.sh'].decode()
        self.assertIn('PROBE_SHA='+sha,runtime)
        self.assertIn('/metadata/r8q-bootdiag-v6',runtime)
        self.assertIn('/bin/r8q-composer-dump-'+sha[:12],runtime)
        self.assertEqual(notices,licenses)
        self.assertEqual(evidence['required_zip_licenses'],{'licenses/fixture.txt':hashlib.sha256(b'notice').hexdigest()})
        self.assertIs(evidence['boot_confirmed'],False)

    def test_foreign_native_build_or_conflicting_target_is_refused(self):
        with patch.object(module.render.previous,'validate_probe',side_effect=ValueError('unknown ELF')):
            with self.assertRaisesRegex(ValueError,'unknown ELF'):
                module.add_diagnostics(self.fixture(),Path('unknown'))
        plan=self.fixture()
        plan['operations'].append(dict(op='delete',path='/bin/r8q-bootdiag.sh'))
        with patch.object(module.render.previous,'validate_probe',return_value=(b'fixture',{},{})):
            with self.assertRaisesRegex(ValueError,'already'):
                module.add_diagnostics(plan,Path('reviewed'))


if __name__=='__main__':unittest.main()
