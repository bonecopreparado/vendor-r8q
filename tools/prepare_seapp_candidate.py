"""Remove proven inactive Samsung selectors and contradictory donor duplicates.

No allow rules, role assignments, domain aliases, image writes or fake labels.
This is a pinned isolated configuration candidate, not a boot-tested ROM.
"""
from pathlib import Path
import collections,difflib,hashlib,json,xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'patches/0004-seapp-fixes'
PINS={
 'vendor/vendor_seapp_contexts':'277a1b6bd188077be9e398f6cdf8cdd8aabbddfa8cb6678aab68c8ddf47e2848',
 'system_ext/system_ext_seapp_contexts':'0740721ec93810e4c3efd5549a4362a754ad9778d4ba3e8f97e7579b49972a64',
 'product/product_seapp_contexts':'2fd04f9d730e073a00621765150741958e02e9ba6a4aa4079d3ac68908aadbf0',
}
DOMAINS={'dsms_app','kfa_app','oneseg_apk','sec_untrusted_app','teed_app','teeregistryd_app','trustonicpartner_app'}
OUTPUT_KEYS={'domain','type','levelFrom','level'}
DEDUP_NAMES={'org.codeaurora.ims','com.qualcomm.qti.devicestatisticsservice','com.qualcomm.qti.services.systemhelper:systemhelper_service'}
SHA=lambda b:hashlib.sha256(b).hexdigest()

def fields(line):
    line=line.split('#',1)[0].strip()
    if not line or line.startswith('neverallow'):return None
    result={}
    for token in line.split():
        key,value=token.split('=',1)
        if key in result:raise ValueError('Duplicate field')
        result[key]=value
    return result

def selector(rule):return tuple(sorted((k,v)for k,v in rule.items()if k not in OUTPUT_KEYS))

def package_records(inventory,apex):
    if len(apex['modules'])!=46:raise ValueError('Incomplete factory APEX coverage')
    rows=inventory['apks']+apex['apks'];result=[]
    for row in rows:
        if row.get('bytes')==0 and row.get('sha256')==SHA(b''):
            # Exact empty placeholders cannot contain a package or signer.
            continue
        if row.get('inspection_error'):raise ValueError('Incomplete APK inspection')
        manifests=[x['attrs']for x in row['manifest']if x['tag']=='manifest']
        if len(manifests)!=1 or not isinstance(manifests[0].get('package'),str) or not row.get('certificates_sha256'):
            raise ValueError('Incomplete package/signing identity')
        result.append(dict(row,package=manifests[0]['package'],shared_uid=manifests[0].get('sharedUserId')))
    return result

def prove_inactive(rule,apps,mac_permissions):
    if rule.get('name'):
        name=rule['name'];name=name.split(':',1)[0]
        matches=[a['package']for a in apps if a['package'].startswith(name[:-1])] if name.endswith('*') else [a['package']for a in apps if a['package']==name]
        if matches:raise ValueError('Samsung selector has installed factory package: '+str(matches))
        return dict(kind='package_or_prefix_absent',selector_name=rule['name'])
    if rule.get('user')=='oneseg':
        if any('oneseg'in str(a.get('shared_uid','')).lower()for a in apps):raise ValueError('oneseg shared UID is retained')
        return dict(kind='oneseg_shared_uid_absent')
    if rule.get('seinfo')in {'trustonicpartner','good_trustonicpartner'}:
        signer_hashes=set()
        for record in mac_permissions:
            for signer in ET.fromstring(record['xml']).findall('signer'):
                if any(x.get('value')==rule['seinfo']for x in signer.iter('seinfo')):
                    signer_hashes.add(SHA(bytes.fromhex(signer.attrib['signature'])))
        if any(signer_hashes.intersection(a['certificates_sha256'])for a in apps):raise ValueError('Trustonic signer matches a retained factory APK')
        return dict(kind='seinfo_signer_absent',seinfo=rule['seinfo'],mac_signer_sha256=sorted(signer_hashes))
    raise ValueError('Inactive selector has no proved absence predicate')

def transform(texts,apps,mac_permissions):
    indexed={}
    for part,text in texts.items():
        for number,line in enumerate(text.splitlines(),1):
            rule=fields(line)
            if rule:indexed[(part,number)]=(line,rule)
    removals={};groups=collections.defaultdict(list)
    for key,(line,rule)in indexed.items():groups[selector(rule)].append((key,rule))
    for key,(line,rule)in indexed.items():
        part,number=key
        if part=='vendor' and rule.get('domain')in DOMAINS:
            removals[key]=dict(reason='inactive_legacy_samsung_app_selector',proof=prove_inactive(rule,apps,mac_permissions))
        elif part=='system_ext' and rule.get('name')=='com.qualcomm.telephony':
            if rule.get('domain')!='radio_service':raise ValueError('Unexpected donor radio mapping')
            vendor=[r for k,r in groups[selector(rule)]if k[0]=='vendor']
            if len(vendor)!=1 or vendor[0].get('domain')!='vendor_qtelephony' or any(rule.get(k)!=vendor[0].get(k)for k in ('type','levelFrom','level')):
                raise ValueError('Coherent existing vendor telephony selector unavailable')
            removals[key]=dict(reason='invalid_radio_service_process_domain_duplicate',retained_domain='vendor_qtelephony')
        elif part=='vendor' and rule.get('name')in DEDUP_NAMES:
            others=[(k,r)for k,r in groups[selector(rule)]if k[0]in ('system_ext','product')]
            if len(others)!=1 or others[0][1].get('domain')!=rule.get('domain'):raise ValueError('Contradictory duplicate domain requires separate review')
            if rule['name'].startswith('com.qualcomm.qti.services.systemhelper:'):
                retained=others[0][1]
                matched=[a for a in apps if a['package']=='com.qualcomm.qti.services.systemhelper']
                if len(matched)!=1 or matched[0]['shared_uid']!='android.uid.system' or retained.get('type')!='system_app_data_file' or 'levelFrom'in retained:
                    raise ValueError('SystemHelper system UID/data label proof differs')
                reason='retain_framework_system_uid_data_label'
            else:
                if any(rule.get(k)!=others[0][1].get(k)for k in OUTPUT_KEYS):raise ValueError('Nonidentical duplicate output')
                reason='identical_duplicate_selector_output'
            removals[key]=dict(reason=reason,retained_partition=others[0][0][0],retained_rule=others[0][1])
    expected_domains={indexed[k][1]['domain']for k in removals if removals[k]['reason']=='inactive_legacy_samsung_app_selector'}
    if expected_domains!=DOMAINS:raise ValueError('Samsung domain coverage differs')
    output={part:''.join(line+'\n'for n,line in enumerate(text.splitlines(),1)if(part,n)not in removals)for part,text in texts.items()}
    remaining=collections.defaultdict(list)
    for part,text in output.items():
        for n,line in enumerate(text.splitlines(),1):
            rule=fields(line)
            if rule:remaining[selector(rule)].append((part,n,rule))
    if any(len(rows)>1 for rows in remaining.values()):raise ValueError('Duplicate seapp selectors remain')
    return output,[dict(partition=k[0],line=k[1],original=indexed[k][0],**value)for k,value in sorted(removals.items())]

def main():
    source=OUT/'original';texts={}
    for path,expected in PINS.items():
        data=(source/path).read_bytes()
        if SHA(data)!=expected:raise ValueError('Seapp source identity differs: '+path)
        texts[path.split('/')[0]]=data.decode()
    raw=(OUT/'app-inventory.json').read_bytes();araw=(OUT/'apex-app-inventory.json').read_bytes()
    if SHA(raw)!='8b0314b289668085b131c0cd7cfc222ea29c6ef23f43d7d8cb1cecd052e4fa6d' or SHA(araw)!='ecf83b8fa1fecdd06ae75272225dfd6761c1b9bc6132dbaf870059c343293c54':raise ValueError('APK inventory identity differs')
    inventory=json.loads(raw);apex=json.loads(araw);apps=package_records(inventory,apex)
    outputs,changes=transform(texts,apps,inventory['mac_permissions'])
    records=[]
    for part,text in outputs.items():
        if text==texts[part]:continue
        filename=part+'_seapp_contexts';dest=OUT/'candidate'/part/'etc/selinux'/filename
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text)
        diff=''.join(difflib.unified_diff(texts[part].splitlines(True),text.splitlines(True),fromfile='original/'+part+'/'+filename,tofile='candidate/'+part+'/'+filename))
        (OUT/(part+'.diff')).write_text(diff)
        records.append(dict(partition=part,path='/etc/selinux/'+filename,before_sha256=SHA(texts[part].encode()),after_sha256=SHA(text.encode())))
    result=dict(status='ISOLATED_CONFIGURATION_FIX_NOT_BOOT_TESTED',changes=changes,files=records,real_factory_apks=len(apps),factory_apex_modules=len(apex['modules']),cil_or_allow_changes=False,rom_images_changed=False,limits=['Factory APK manifests and signing-certificate metadata were inspected; APK signatures were not independently cryptographically verified.','No /data packages or runtime state were available. Samsung/Trustonic app suites are not supported by this factory composition.','App launch, radio/IMS/Trustonic behavior still requires runtime validation.'])
    (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(files=records,removed_rules=len(changes),real_factory_apks=len(apps)),indent=2))

if __name__=='__main__':main()
