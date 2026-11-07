"""Build a pinned EROFS writer which stores symlink targets outside inode blocks."""
from pathlib import Path
import hashlib,json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[2]
COMMIT='3689cbc2349bff05807d2f939146e92eb1bfaea1'
def run(*args,cwd=ROOT):
    subprocess.run(list(map(str,args)),cwd=cwd,check=True)
def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
source=ROOT/'.deps/erofs-legacy'
source.mkdir(parents=True,exist_ok=False)
run('git','init',source)
run('git','remote','add','origin','https://github.com/erofs/erofs-utils.git',cwd=source)
run('git','fetch','--depth=1','origin',COMMIT,cwd=source)
run('git','checkout','--detach','FETCH_HEAD',cwd=source)
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()==COMMIT
p=source/'lib/inode.c';original=p.read_text()
old="\tif (inode->datalayout == EROFS_INODE_FLAT_PLAIN)\n\t\tgoto noinline;"
new="""\t/* Old Android EROFS rejects fast symlinks across inode block edges.
\t * Use the existing plain-data fallback; retain target bytes and xattrs. */
\tif (inode->datalayout == EROFS_INODE_FLAT_PLAIN ||
\t    S_ISLNK(inode->i_mode)) {
\t\tinode->datalayout = EROFS_INODE_FLAT_PLAIN;
\t\tgoto noinline;
\t}"""
assert original.count(old)==1
p.write_text(original.replace(old,new))
output=ROOT/'tools/erofs-legacy/bin';output.mkdir(parents=True,exist_ok=False)
provenance=dict(repository='https://github.com/erofs/erofs-utils',commit=COMMIT,
    original_inode_sha256=hashlib.sha256(original.encode()).hexdigest(),patched_inode_sha256=digest(p),
    policy='All symlinks use existing FLAT_PLAIN data blocks; no target/xattr/ownership changes',
    device_boot_test=False)
run('sh','autogen.sh',cwd=source)
run('./configure','--disable-fuse','--disable-lzma','--without-zlib','--without-libdeflate','--without-libzstd','--without-selinux',cwd=source)
run('make','-j2',cwd=source)
shutil.copy2(source/'mkfs/mkfs.erofs',output/'mkfs.erofs')
provenance['mkfs_sha256']=digest(output/'mkfs.erofs')
(output.parent/'PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')
run(output/'mkfs.erofs','--version')
