"""Package current machine-generated audit reports; never create a recovery ZIP.

Only approved text report roots, readiness status and license notices are read.
ROM inputs, compiler binaries, old artifacts and device/user logs are excluded.
"""
from pathlib import Path
import gzip
import hashlib
import io
import json
import os
import tarfile

ROOT = Path(os.environ.get('R8Q_PROJECT_ROOT', Path(__file__).resolve().parents[2])).resolve()
NAME = 'R8Q-AUDIT-REPORTS-NOT-FLASHABLE.tar.gz'
REPORT_ROOTS = ('ci-results', 'context-results', 'vintf-results')
TEXT_SUFFIXES = {'.json', '.txt', '.log', '.md', '.diff'}
EXCLUDED_PARTS = {
    'input', 'inputs', 'otatools', '.deps', 'sources', 'source', 'extracted',
    'images', 'payloads', 'runtime', 'vendor', 'odm', 'system', 'system_ext', 'product',
}
EXCLUDED_NAMES = {'contexts.txt', 'references.json', 'all-contexts.json',
                  'recovery.log', 'dmesg.log', 'logcat.log'}
MAX_FILE_BYTES = 8 * 1024**2
MAX_TOTAL_BYTES = 64 * 1024**2
README = '''R8Q AUDIT REPORTS - NOT FLASHABLE

This TAR contains current validation reports, release status and license notices.
It is not a ROM, an installer, a recovery update, a vendor image or a boot patch.
Do not select it in OrangeFox Install. No META-INF updater is included.

Reports describe their own scope and limitations. A passing regression baseline
does not clear known SELinux findings, establish VINTF/kernel compatibility or
confirm boot. Consult release-readiness.json before considering device testing.

This package is generated from the current checkout and available current-run
reports. It does not download artifacts from an older workflow run. Missing
report roots are recorded in PACKAGE-MANIFEST.json; missing evidence is not a
passing compatibility result. Firmware inputs and host compiler binaries are
not distributed in this package.
'''


def safe_file(path, root):
    """Reject symlinks anywhere between root and the selected report file."""
    relative = path.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return False
    return path.is_file()


def report_allowed(relative):
    lowered = tuple(part.lower() for part in relative.parts)
    if set(lowered) & EXCLUDED_PARTS or relative.suffix.lower() not in TEXT_SUFFIXES:
        return False
    name = relative.name.lower()
    if name in EXCLUDED_NAMES:
        return False
    return not any(name.startswith(prefix) for prefix in
                   ('recovery(', 'recovery-', 'recovery ', 'dmesg(', 'dmesg-',
                    'dmesg ', 'logcat(', 'logcat-', 'logcat ', 'r8q-device-',
                    'r8q-metadata-', 'device-inventory'))


def collect_members(root):
    members = {'README-NOT-FLASHABLE.txt': README.encode()}
    report_roots, skipped = {}, []
    total = 0
    for directory in REPORT_ROOTS:
        folder = root / directory
        report_roots[directory] = bool(folder.is_dir() and not folder.is_symlink())
        if not report_roots[directory]:
            continue
        for path in sorted(folder.rglob('*')):
            relative = path.relative_to(folder)
            if not report_allowed(relative) or not safe_file(path, root):
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                skipped.append({'path':directory+'/'+relative.as_posix(),
                                'reason':'report exceeds 8 MiB limit'})
                continue
            data = path.read_bytes()
            if b'\0' in data:
                skipped.append({'path':directory+'/'+relative.as_posix(),
                                'reason':'not a text report'})
                continue
            data.decode('utf-8')
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise ValueError('Current report text exceeds 64 MiB limit')
            members['reports/'+directory+'/'+relative.as_posix()] = data

    status_path = root/'ci-r8q/inputs/release-readiness.json'
    if not safe_file(status_path, root):
        raise ValueError('A current release-readiness.json is required')
    status_data = status_path.read_bytes()
    status = json.loads(status_data)
    if not isinstance(status.get('boot_ready'), bool) or not isinstance(status.get('status'), str):
        raise ValueError('Release readiness status is incomplete')
    candidate_status = root/'output/release-readiness.json'
    if safe_file(candidate_status, root) and json.loads(candidate_status.read_bytes()) != status:
        raise ValueError('Generated candidate status differs from the current source status')
    members['release-readiness.json'] = status_data
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        path = root/name
        if safe_file(path, root):
            members[name] = path.read_bytes()
    folder = root/'licenses'
    if folder.is_dir() and not folder.is_symlink():
        for path in sorted(folder.rglob('*')):
            if safe_file(path, root) and path.suffix.lower() in {'.txt', '.md', '.json'}:
                members[path.relative_to(root).as_posix()] = path.read_bytes()
    manifest = dict(schema_version=1, archive_kind='AUDIT_REPORTS_NOT_FLASHABLE',
                    current_report_roots=report_roots, skipped_reports=skipped,
                    boot_ready=status['boot_ready'], release_status=status['status'],
                    files={name:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
                           for name,data in sorted(members.items())})
    members['PACKAGE-MANIFEST.json'] = (json.dumps(manifest,indent=2)+'\n').encode()
    members['SHA256SUMS.txt'] = ''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n'
                                      for name,data in sorted(members.items())).encode()
    return members


def build_bundle(root=ROOT):
    members = collect_members(root)
    out = root/'output'
    out.mkdir(exist_ok=True)
    destination = out/NAME
    with destination.open('wb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0,compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed,mode='w',format=tarfile.USTAR_FORMAT) as archive:
                for name,data in sorted(members.items()):
                    info = tarfile.TarInfo(name)
                    info.size=len(data);info.mode=0o644;info.mtime=0
                    info.uid=0;info.gid=0;info.uname='';info.gname=''
                    archive.addfile(info,io.BytesIO(data))
    with tarfile.open(destination,'r:gz') as archive:
        if archive.getnames()!=sorted(members) or any(not entry.isfile() for entry in archive):
            raise ValueError('Unexpected report archive members')
        for name,data in members.items():
            if archive.extractfile(name).read()!=data:
                raise ValueError('Report archive content differs')
    sha = hashlib.sha256(destination.read_bytes()).hexdigest()
    (out/(NAME+'.sha256')).write_text(sha+'  '+NAME+'\n')
    return dict(file=str(destination),bytes=destination.stat().st_size,sha256=sha,
                archive_kind='AUDIT_REPORTS_NOT_FLASHABLE')


if __name__=='__main__':
    print(json.dumps(build_bundle(),indent=2))
