"""Add diagnostics to a copied Vendor plan, using a verified native build.

Callers must verify all add targets are absent from the source filesystem and
include the returned license files in the final distributed ZIP.
"""
import copy
import hashlib
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import render

RC_SHA='f87c5e2be6ce97d93d2aba1098495f3b2f33479a98878b0adab5be888a3fb447'


def add_diagnostics(plan,probe_directory):
    helper,report,notices=render.previous.validate_probe(Path(probe_directory))
    rc=(render.ROOT/'tools/bootdiag/init.rc').read_bytes()
    if hashlib.sha256(rc).hexdigest()!=RC_SHA:
        raise ValueError('Reviewed early diagnostic init service differs')
    helper_sha=hashlib.sha256(helper).hexdigest()
    files={
        '/etc/init/r8q-bootdiag.rc':(rc,'/etc/init/hw/init.qcom.rc'),
        '/bin/r8q-bootdiag.sh':(render.render_runtime(helper_sha),'/bin/init.qti.qcv.sh'),
        '/bin/r8q-composer-dump-'+helper_sha[:12]:(helper,'/bin/init.qti.qcv.sh'),
    }
    result=copy.deepcopy(plan)
    if result.get('schema_version')!=1 or not isinstance(result.get('operations'),list):
        raise ValueError('Expected versioned Vendor plan')
    existing={row['path'] for row in result['operations']}
    if existing & files.keys():
        raise ValueError('Diagnostic target already has a planned operation')
    payloads={}
    for target,(data,metadata_from) in files.items():
        name='candidate/vendor'+target
        result['operations'].append(dict(op='add',path=target,source=name,
            metadata_from=metadata_from,sha256=hashlib.sha256(data).hexdigest()))
        payloads[name]=data
    return result,payloads,notices,dict(namespace='/metadata/r8q-bootdiag-v6',
        probe_sha256=helper_sha,probe_build=report,required_zip_licenses={
            name:hashlib.sha256(data).hexdigest() for name,data in notices.items()},
        boot_confirmed=False)
