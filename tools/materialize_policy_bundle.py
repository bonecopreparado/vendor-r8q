"""Restore reviewed CIL source inputs from the checked-in hash-pinned TAR."""
from pathlib import Path
import hashlib,tarfile
ROOT=Path(__file__).resolve().parents[1]

def main():
    source=ROOT/'ci-r8q/inputs/selinux-policy-audit-bundle.tar.gz'
    if hashlib.sha256(source.read_bytes()).hexdigest()!='e2f1f72e28e3f55ea0ce896a98b4b48e017dbf74c385538e9fb4f3484b6b2524':
        raise ValueError('Policy input archive identity differs')
    destination=ROOT/'reports/audit-20261031/overnight/selinux'
    with tarfile.open(source) as archive:
        total=0
        for entry in archive:
            p=Path(entry.name)
            if p.is_absolute() or '..' in p.parts or p.parts[0]!='policy-bundle':raise ValueError('Unsafe policy archive path')
            if entry.isdir():continue
            if not entry.isfile():raise ValueError('Policy archive links/special files forbidden')
            total+=entry.size
            if total>32*1024**2:raise ValueError('Policy archive too large')
            data=archive.extractfile(entry).read();target=destination/p
            if target.is_symlink():raise ValueError('Policy output symlink forbidden')
            if target.exists():
                if target.read_bytes()!=data:raise ValueError('Existing policy source differs: '+entry.name)
            else:
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    print('Pinned policy source bundle verified/materialized')

if __name__=='__main__':main()
