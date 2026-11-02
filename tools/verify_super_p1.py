"""Independent readback with unmodified LineageOS extract-utils LP parser."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
REFERENCE=ROOT/'tools/lineage-reference'
package=REFERENCE/'package/extract_utils'
package.mkdir(parents=True,exist_ok=True)
(package/'__init__.py').write_text('')
for name in ('lp.py','utils.py'):
    (package/name).write_bytes((REFERENCE/name).read_bytes())
sys.path.insert(0,str(package.parent))
from extract_utils.lp import LpImage

class HashSink:
    def __init__(self):self.digest=hashlib.sha256();self.size=0
    def write(self,data):self.digest.update(data);self.size+=len(data);return len(data)

def main():
    report=json.loads((ROOT/'reports/p1/super-build.json').read_text())
    rows=[]
    with (ROOT/'candidates/p1/super-r8q-hyperos-p1.img').open('rb') as source:
        image=LpImage(source)
        names=image.get_partition_names()
        expected={p['name']:p for p in report['embedded_sources']}
        if set(names)!=set(expected):raise ValueError('Independent partition list mismatch')
        for name in names:
            p=image.find_partition(name)
            sink=HashSink()
            # The upstream read/extraction implementation writes into a hash sink
            # instead of creating another full partition file on disk.
            for extent in image._LpImage__extents[p.first_extent_index:p.first_extent_index+p.num_extents]:
                if extent.target_type!=0:raise ValueError('Nonlinear extent unexpected')
                image._write_extent_to_file(extent,sink)
            row=dict(name=name,bytes=sink.size,sha256=sink.digest.hexdigest())
            if row['bytes']!=expected[name]['bytes'] or row['sha256']!=expected[name]['sha256']:
                raise ValueError('Independent readback mismatch: '+name)
            rows.append(row);print(name,'independent SHA256 matched',flush=True)
    provenance=json.loads((REFERENCE/'lp-source.json').read_text())
    result=dict(tool='Unmodified LineageOS extract-utils LP parser/extractor',
                source=provenance,partitions=rows,
                scope='Independent partition enumeration, extents decoding and payload hashing. Does not establish boot/runtime compatibility.')
    (ROOT/'reports/p1/super-independent-readback.json').write_text(json.dumps(result,indent=2)+'\n')
    report['checks'].append('Independent LineageOS LP parser enumerates/extracts all partitions with matching hashes')
    report['pending']=[p for p in report['pending'] if p!='AOSP liblp independent reader']
    (ROOT/'reports/p1/super-build.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()

