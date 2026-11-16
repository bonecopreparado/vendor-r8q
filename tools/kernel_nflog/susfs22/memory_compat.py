"""Pinned memcg shrinker lifetime-lock repair, without replacing global reclaim."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
PINS=json.loads((HERE/'memory-shrinker-pins.json').read_text())
PATCH=HERE/'memory-shrinker.patch'


def file_sha(path):
    if path.is_symlink() or not path.is_file():raise ValueError('Expected regular memory source')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_report():
    return dict(status='EXPERIMENTAL_MEMCG_SHRINKER_LOCK_REPAIR',pins=PINS,
                existing_global_shrinker_locks_preserved=True,hardware_boot_confirmed=False)


def verify(source):
    if file_sha(source/PINS['path'])!=PINS['after_sha256']:
        raise ValueError('Repaired memcg shrinker source differs')


def apply(source,evidence,env,audit):
    if (PINS['source_commit']!=audit.SOURCE_COMMIT or file_sha(PATCH)!=PINS['patch_sha256']
        or file_sha(source/PINS['path'])!=PINS['before_sha256']):
        raise ValueError('Canonical memcg source or repair patch differs')
    command=['git','-C',source,'apply','--whitespace=nowarn']
    audit.run(command+['--check',PATCH],evidence/'memcg-shrinker-check.log',env)
    audit.run(command+[PATCH],evidence/'memcg-shrinker-apply.log',env)
    verify(source)
    return expected_report()
