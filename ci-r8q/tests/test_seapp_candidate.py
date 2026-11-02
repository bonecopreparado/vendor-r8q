"""Bounded selector fixtures verify no new app privilege is manufactured."""
from pathlib import Path
import importlib.util,unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('seapp_candidate',ROOT/'tools/prepare_seapp_candidate.py')
candidate=importlib.util.module_from_spec(spec);spec.loader.exec_module(candidate)

class Tests(unittest.TestCase):
    def texts(self):
        return {
          'vendor':''.join('user=_app seinfo=platform name=absent.'+domain+' domain='+domain+' type=app_data_file\n'for domain in sorted(candidate.DOMAINS))+
                   'user=_app seinfo=platform name=com.qualcomm.telephony domain=vendor_qtelephony type=app_data_file levelFrom=all\n'+
                   'user=_app seinfo=platform name=org.codeaurora.ims isPrivApp=true domain=vendor_qtelephony type=app_data_file levelFrom=all\n'+
                   'user=system seinfo=platform name=com.qualcomm.qti.services.systemhelper:systemhelper_service domain=vendor_systemhelper_app type=app_data_file levelFrom=user\n',
          'system_ext':'user=_app seinfo=platform name=com.qualcomm.telephony domain=radio_service type=app_data_file levelFrom=all\n'+
                       'user=_app seinfo=platform name=org.codeaurora.ims isPrivApp=true domain=vendor_qtelephony type=app_data_file levelFrom=all\n'+
                       'user=system seinfo=platform name=com.qualcomm.qti.services.systemhelper:systemhelper_service domain=vendor_systemhelper_app type=system_app_data_file\n',
          'product':''}
    def apps(self):return [dict(package='com.qualcomm.qti.services.systemhelper',shared_uid='android.uid.system',certificates_sha256=['1'*64])]
    def test_radio_uses_existing_vendor_mapping_without_new_rule(self):
        texts=self.texts();result,changes=candidate.transform(texts,self.apps(),[])
        self.assertNotIn('domain=radio_service',result['system_ext'])
        self.assertIn('name=com.qualcomm.telephony domain=vendor_qtelephony',result['vendor'])
        for part in texts:self.assertTrue(set(result[part].splitlines())<=set(texts[part].splitlines()))
        self.assertTrue(any(x['reason']=='invalid_radio_service_process_domain_duplicate'for x in changes))
    def test_active_samsung_package_blocks_cleanup(self):
        with self.assertRaisesRegex(ValueError,'installed factory package'):
            candidate.transform(self.texts(),self.apps()+[dict(package='absent.dsms_app')],[])
    def test_prefix_package_match_blocks_cleanup(self):
        with self.assertRaises(ValueError):candidate.prove_inactive(dict(name='com.samsung.oneconnect*'),[dict(package='com.samsung.oneconnect.service')],[])
    def test_trustonic_signer_match_blocks_cleanup(self):
        mac=[dict(xml='<policy><signer signature="00"><seinfo value="trustonicpartner"/></signer></policy>')]
        with self.assertRaisesRegex(ValueError,'Trustonic signer'):
            candidate.prove_inactive(dict(seinfo='trustonicpartner'),[dict(certificates_sha256=[candidate.SHA(b'\0')])],mac)
    def test_oneseg_shared_uid_blocks_cleanup(self):
        with self.assertRaisesRegex(ValueError,'oneseg shared UID'):
            candidate.prove_inactive(dict(user='oneseg'),[dict(shared_uid='android.uid.oneseg')],[])
    def test_wrong_systemhelper_uid_blocks_conflict_resolution(self):
        with self.assertRaisesRegex(ValueError,'SystemHelper'):
            candidate.transform(self.texts(),[dict(package='com.qualcomm.qti.services.systemhelper',shared_uid='android.uid.phone')],[])
    def test_missing_correct_vendor_telephony_domain_blocks_fix(self):
        texts=self.texts();texts['vendor']=texts['vendor'].replace('name=com.qualcomm.telephony domain=vendor_qtelephony','name=com.qualcomm.telephony domain=radio')
        with self.assertRaisesRegex(ValueError,'telephony selector'):
            candidate.transform(texts,self.apps(),[])
    def test_unexpected_inactive_selector_cannot_be_dropped(self):
        with self.assertRaisesRegex(ValueError,'absence predicate'):candidate.prove_inactive(dict(user='mystery'),[],[])
    def test_all_apex_coverage_is_required(self):
        with self.assertRaisesRegex(ValueError,'APEX coverage'):candidate.package_records(dict(apks=[]),dict(modules=[],apks=[]))
    def test_unknown_apk_inspection_failure_blocks_absence_proof(self):
        with self.assertRaisesRegex(ValueError,'Incomplete APK inspection'):
            candidate.package_records(dict(apks=[dict(inspection_error='unparsed')]),dict(modules=[{}]*46,apks=[]))

if __name__=='__main__':unittest.main()
