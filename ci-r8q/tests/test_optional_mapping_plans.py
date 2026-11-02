"""Keep the donor-guided deletion variant confined to optional mappings."""
from pathlib import Path
import hashlib
import importlib.util
import json
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('optional_mapping_plans',ROOT/'tools/prepare_p1_plans.py')
planner=importlib.util.module_from_spec(spec);spec.loader.exec_module(planner)
HEADER=b'Path : /etc/selinux/mapping\nNID TYPE FILENAME\n1 2 .\n2 2 ..\n'


class Tests(unittest.TestCase):
    def test_complete_flat_listing_is_sorted_and_rejects_unsafe_children(self):
        self.assertEqual(planner.parse_mapping_listing(HEADER+b'3 1 30.0.compat.cil\n4 1 30.0.cil\n','product'),
                         ['30.0.cil','30.0.compat.cil'])
        for child in [b'3 2 nested\n',b'3 7 30.0.cil\n',b'3 1 ../30.0.cil\n',b'not a valid row\n',
                      b'3 1 30.0.cil\n4 1 30.0.cil\n']:
            with self.subTest(child=child),self.assertRaises(ValueError):
                planner.parse_mapping_listing(HEADER+child,'system_ext')

    def test_listing_bounds_and_empty_directory_are_rejected(self):
        for text in [HEADER,b'X'*65537,HEADER+b''.join(f'{i+3} 1 {100000+i}.cil\n'.encode() for i in range(65))]:
            with self.assertRaises(ValueError):planner.parse_mapping_listing(text,'product')

    def test_platform_mapping_cannot_be_selected(self):
        with self.assertRaisesRegex(ValueError,'Only system_ext/product'):
            planner.mapping_deletions('system')

    def test_deletions_pin_every_regular_file_and_reject_inode_aliases(self):
        import rebuild_erofs_candidate
        content=b'(typeattribute fixture_30_0)\n'
        directory=dict(mode=stat.S_IFDIR|0o755)
        regular=dict(mode=stat.S_IFREG|0o644,nlink=1,size=len(content))
        fake=SimpleNamespace(entry=lambda p:directory if p==planner.MAPPING_BASE else regular,
                             read=lambda p:content)
        listing=SimpleNamespace(stdout=HEADER+b'3 1 30.0.cil\n')
        with patch.object(rebuild_erofs_candidate,'Image',return_value=fake),patch.object(planner.subprocess,'run',return_value=listing):
            self.assertEqual(planner.mapping_deletions('product'),[dict(op='delete',path='/etc/selinux/mapping/30.0.cil',
                old_sha256=hashlib.sha256(content).hexdigest(),bytes=len(content))])
            for invalid in [dict(regular,mode=stat.S_IFLNK|0o777),dict(regular,nlink=2),dict(regular,size=1024**2+1)]:
                fake.entry=lambda p,row=invalid:directory if p==planner.MAPPING_BASE else row
                with self.assertRaisesRegex(ValueError,'bounded single-link regular'):
                    planner.mapping_deletions('system_ext')

    def test_default_and_variant_differ_only_in_optional_mapping_operations(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def write(name,data):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            composition={'partitions':[{'partition':p,'sha256':'a'*64} for p in ['system','system_ext','product','vendor','odm']]}
            write('reports/composition-proposed.json',json.dumps(composition).encode())
            bundle='reports/audit-20261031/overnight/selinux/policy-bundle/'
            old_policy=b'old policy\n';new_policy=b'corrected policy\n';old_mapping=b'old mapping\n';new_mapping=b'corrected mapping\n'
            files={}
            for name,old,new in [('system_ext_system_ext_sepolicy.cil',old_policy,new_policy),
                                 ('system_ext_mapping_30.0.cil',old_mapping,new_mapping)]:
                files['original/'+name]=planner.SHA(old);files['candidate/'+name]=planner.SHA(new)
                write(bundle+'candidate/'+name,new)
            write(bundle+'manifest.json',json.dumps({'files':files}).encode())
            for part in ('system_ext','vendor'):
                write('patches/0004-seapp-fixes/candidate/'+part+'/etc/selinux/'+part+'_seapp_contexts',b'corrected contexts\n')
            write('patches/0006-hardware-adaptation/candidate/manifest.json',b'{"files":[]}')
            write('patches/0005-vintf-adaptation/candidate/system/etc/vintf/compatibility_matrix.device.xml',b'<matrix/>\n')
            write('patches/0005-vintf-adaptation/candidate/system_ext/etc/vintf/manifest/r8q-vndk30.xml',b'<manifest/>\n')
            # Use the existing reviewed diff as the historical logger fixture.
            diff=(ROOT/'patches/0007-policy-integration/vendor-_etc_init_hw_init.qcom.rc.diff').read_text()
            old_init=''.join(line[1:]+'\n' for line in diff.splitlines() if line.startswith('-') and not line.startswith('---'))
            def read(part,path):
                if path=='/etc/selinux/system_ext_sepolicy.cil':return old_policy
                if path=='/etc/selinux/mapping/30.0.cil':return old_mapping
                if path=='/etc/init/hw/init.qcom.rc':return old_init.encode()
                return b'unchanged original\n'
            rows={part:[dict(op='delete',path='/etc/selinux/mapping/30.0.cil',old_sha256=planner.SHA(old_mapping),bytes=len(old_mapping))]
                  for part in ('system_ext','product')}
            outputs={}
            for variant in (False,True):
                out=root/('variant' if variant else 'baseline')
                with patch.object(planner,'ROOT',root),patch.object(planner,'OUT',out),patch.object(planner,'read',side_effect=read),\
                     patch.object(planner,'mapping_deletions',side_effect=lambda p:rows[p]),patch.object(planner.subprocess,'run'):
                    planner.main(['--omit-optional-mappings'] if variant else [])
                outputs[variant]={p.name:json.loads(p.read_text()) for p in out.glob('*-plan.json')}
            base=outputs[False];variant=outputs[True]
            self.assertNotIn('product-plan.json',base)
            for part in ('system','vendor','odm'):
                self.assertEqual(base[part+'-plan.json'],variant[part+'-plan.json'])
            base_ext=base['system_ext-plan.json']['operations']
            variant_ext=variant['system_ext-plan.json']['operations']
            self.assertEqual([r for r in base_ext if '/mapping/' not in r['path']],
                             [r for r in variant_ext if '/mapping/' not in r['path']])
            self.assertEqual([r['op'] for r in variant_ext if '/mapping/' in r['path']],['delete'])
            product=variant['product-plan.json']['operations']
            self.assertEqual(product,[{k:rows['product'][0][k] for k in ('op','path','old_sha256')}])
            for plan in variant.values():
                for operation in plan['operations']:
                    if operation['op']=='delete' and operation['path'].startswith('/etc/selinux/mapping/'):
                        self.assertNotIn(plan, [variant['system-plan.json'],variant['vendor-plan.json'],variant['odm-plan.json']])


if __name__=='__main__':unittest.main()
