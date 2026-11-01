"""Check fixed context references against an exact serialized candidate policy."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
work = ROOT / '.deps/context-inputs'
inputs = ROOT / 'ci-r8q/inputs/context-audit.tar.gz'
expected = 'ad031132de92d9ee9ca7564d2b85a1d513844dc9d3ee02b23d0f399a94130b6e'
if hashlib.sha256(inputs.read_bytes()).hexdigest() != expected:
    raise ValueError('Context bundle identity differs')
work.parent.mkdir(exist_ok=True)
with tarfile.open(inputs) as archive:
    names = {'context-inputs/candidate.policy','context-inputs/contexts.txt','context-inputs/references.json','context-inputs/manifest.json'}
    if set(archive.getnames()) != names or len(archive.getmembers()) != 4:
        raise ValueError('Unexpected context bundle members')
    for entry in archive:
        if not entry.isfile() or entry.size > 8*1024**2:
            raise ValueError('Unexpected context input type/size')
        target = work.parent / entry.name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(archive.extractfile(entry).read())
manifest = json.loads((work/'manifest.json').read_text())
expected_files = {'candidate.policy', 'contexts.txt', 'references.json'}
if set(manifest.get('files', {})) != expected_files:
    raise ValueError('Unexpected context manifest files')
if manifest.get('policy_sha256') != '70278111389ef8affecddf0eee346f4d3cba4b72fe7bc907e512f7c610d769ad':
    raise ValueError('Unexpected isolated policy candidate')
for name,sha in manifest['files'].items():
    if Path(name).name != name or hashlib.sha256((work/name).read_bytes()).hexdigest()!=sha:
        raise ValueError('Mixed context input files')
refs = json.loads((work/'references.json').read_text())
contexts = (work/'contexts.txt').read_text().splitlines()
if contexts != sorted(set(contexts)) or set(contexts) != set(refs['references']):
    raise ValueError('Context label list and source references differ')
baseline_path = ROOT/'ci-r8q/inputs/context-baseline.json'
baseline = json.loads(baseline_path.read_text())
if baseline.get('schema_version') != 1 or baseline.get('policy_sha256') != manifest['policy_sha256']:
    raise ValueError('Context baseline belongs to a different policy')
out = ROOT/'context-results';out.mkdir(exist_ok=True)
checker = ROOT/'build/check-contexts'
caps = ['network_peer_controls','open_perms','extended_socket_class','nnp_nosuid_transition','netlink_xperm','functionfs_seclabel']
capcheck = subprocess.run([str(ROOT/'build/check-policy-caps'),str(work/'candidate.policy')]+caps,capture_output=True,text=True,timeout=30)
(out/'caps-check.txt').write_text(capcheck.stdout+capcheck.stderr)
if capcheck.returncode: raise ValueError('Policy capabilities did not pass')
result = subprocess.run([str(checker),str(work/'candidate.policy'),str(work/'contexts.txt')],capture_output=True,text=True,timeout=120)
(out/'checker-stderr.txt').write_text(result.stderr)
if result.returncode: raise ValueError('Context checker failed its input/controls')
rows=[]
for line in result.stdout.splitlines():
    context,parse,checked=line.split('\t')
    rows.append(dict(context=context,parse_status=int(parse),check_status=int(checked),references=refs['references'][context]))
if set(r['context'] for r in rows)!=set(refs['references']) or len(rows)!=len(refs['references']):
    raise ValueError('Checker output coverage differs')
invalid=[r for r in rows if r['parse_status'] or r['check_status']]
known = baseline['known_invalid_contexts']
new_invalid = [r for r in invalid if r['context'] not in known]
known_invalid = [r for r in invalid if r['context'] in known]
resolved_baseline = sorted(set(known)-{r['context'] for r in invalid})
report=dict(status='EXACT_POLICY_CONTEXT_CHECK_NOT_RUNTIME_TEST',policy_sha256=manifest['policy_sha256'],
            contexts=len(rows),valid=len(rows)-len(invalid),invalid=invalid,
            candidate_applied_to_rom=False, rom_release_status='BLOCKED_PENDING_IMAGE_INTEGRATION_AND_RUNTIME_VALIDATION',
            regression_status='NEW_INVALID_CONTEXTS' if new_invalid else 'NO_NEW_INVALID_CONTEXTS',
            new_invalid=new_invalid, known_invalid=known_invalid, resolved_baseline=resolved_baseline,
            known_invalid_explanations={r['context']:known[r['context']] for r in known_invalid},
            baseline_sha256=hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
            checker_sha256=hashlib.sha256(checker.read_bytes()).hexdigest(),
            source_files=refs['sources'],limits=refs['limits'])
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
(out/'all-contexts.json').write_text(json.dumps(rows,indent=2)+'\n')
with zipfile.ZipFile(out/'R8Q-context-audit.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for path in sorted(out.iterdir()):
        if path.is_file() and path.suffix in ('.json','.txt'):archive.write(path,path.name)
print(json.dumps(dict(status=report['status'],contexts=report['contexts'],valid=report['valid'],invalid=len(invalid),
                     new_invalid=len(new_invalid),known_invalid=len(known_invalid),
                     regression_status=report['regression_status'],rom_release_status=report['rom_release_status']),indent=2))
for row in invalid: print('INVALID:',row['context'],json.dumps(row['references']))
if new_invalid: raise SystemExit(1)
