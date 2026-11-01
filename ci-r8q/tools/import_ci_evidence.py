"""Read only known members from prior CI ZIPs; do not extract arbitrary paths."""
from pathlib import Path
import hashlib
import io
import zipfile

ROOT = Path(__file__).resolve().parents[2]
def read_member(archive, name):
    matching = [i for i in archive.infolist() if i.filename == name]
    if len(matching) != 1 or matching[0].file_size > 16*1024**2:
        raise ValueError('Unexpected or duplicated CI archive member: ' + name)
    return archive.read(name)

with zipfile.ZipFile(ROOT/'downloads/tools-evidence.zip') as outer:
    data = read_member(outer, 'Auditoria-R8Q-20261031.zip')
if hashlib.sha256(data).hexdigest() != '0eba23f3951b993305807b85d4d8c6afb2cbaea8760f2b43d3e67b5c6b16434f':
    raise ValueError('Prior tools artifact differs from validated run')
with zipfile.ZipFile(io.BytesIO(data)) as inner:
    for name in ('secilc-host','check-policy-caps','compiler-sha256.txt','selinux-source-commit.txt'):
        path = ROOT/'build'/name; path.parent.mkdir(exist_ok=True)
        path.write_bytes(read_member(inner, 'linux-tools/'+name))
    policy = ROOT/'ci-results/policy'; policy.mkdir(parents=True, exist_ok=True)
    for name in ('result.json','original-init.log','candidate-init.log','candidate-init-caps.log','candidate-neverallow-audit.log'):
        (policy/name).write_bytes(read_member(inner, 'evidence/policy/'+name))
with zipfile.ZipFile(ROOT/'downloads/vendor-evidence.zip') as outer:
    data = read_member(outer, 'RELATORIO-VENDOR-1610.zip')
if hashlib.sha256(data).hexdigest() != '52611e12807255db3b37ea82ff4a483b2ae0686ca710843db1776de475d48e27':
    raise ValueError('Prior vendor artifact differs from validated run')
out=ROOT/'output';out.mkdir(exist_ok=True)
(out/'RELATORIO-VENDOR-1610.zip').write_bytes(data)
print('Imported pinned compiler/policy evidence and vendor comparison; no ROM images.')
