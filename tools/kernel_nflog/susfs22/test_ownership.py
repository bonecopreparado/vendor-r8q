"""Host C regression using statements extracted from the patched kernel tree."""
from pathlib import Path
import subprocess
import sys
import tempfile

source=Path(sys.argv[1])
text=(source/'fs/namespace.c').read_text()
definition=[line for line in (source/'include/linux/susfs_def.h').read_text().splitlines()
            if line.startswith('#define VFSMOUNT_MNT_FLAGS_KSU_UNSHARED_MNT ')]
if len(definition)!=1:
    raise ValueError('Expected one actual ownership flag definition')
start=text.index('static void mnt_free_id(struct mount *mnt)')
end=text.index('\n}',start)+2
free_function=text[start:end]
start=text.index('static struct mount *susfs_alloc_unshare_ksu_vfsmnt')
end=text.index('if (name)',start)
constructor=text[start:end]
mark='mnt->mnt.mnt_flags |= VFSMOUNT_MNT_FLAGS_KSU_UNSHARED_MNT;'
if constructor.count(mark)!=1:
    raise ValueError('Borrowed ID must be marked before any later failing allocation')
start=text.index('\tmnt->mnt.mnt_flags = old->mnt.mnt_flags;')
end=text.index('/* Don\'t allow unprivileged',start)
clone_flags=text[start:end]
if 'copy_flags |= CL_COPY_MNT_NS;' not in text:
    raise ValueError('Namespace-copy flag is not propagated')
program='''#include <assert.h>
#define CONFIG_KSU_SUSFS_SUS_MOUNT 1
#define MNT_WRITE_HOLD 1
#define MNT_MARKED 2
#define MNT_INTERNAL 4
#define unlikely(x) (x)
struct mount { struct { unsigned long mnt_flags; } mnt; int mnt_id; };
static int mnt_id_ida,freed,last_id;
static void ida_free(int *unused,int id) { (void)unused; freed++;last_id=id; }
'''+definition[0]+'\n'+free_function+'''
static void flags(struct mount *mnt,struct mount *old,int is_mnt_ksu_unshared) {
'''+clone_flags+'''
}
int main(void) {
 struct mount old={{0},10},fresh={{0},20},borrowed={{0},10};
 struct mount *mnt=&borrowed;
 '''+mark+'''
 /* Error cleanup before clone flag assignment must not free an old ID. */
 mnt_free_id(&borrowed); assert(freed==0);
 old.mnt.mnt_flags=VFSMOUNT_MNT_FLAGS_KSU_UNSHARED_MNT;
 flags(&fresh,&old,0);mnt_free_id(&fresh);assert(freed==1 && last_id==20);
 flags(&borrowed,&old,1);mnt_free_id(&borrowed);assert(freed==1);
 old.mnt.mnt_flags=0;
 flags(&fresh,&old,0);mnt_free_id(&fresh);assert(freed==2 && last_id==20);
 flags(&borrowed,&old,1);mnt_free_id(&borrowed);assert(freed==2);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as work:
    path=Path(work)/'ownership.c';path.write_text(program)
    exe=Path(work)/'ownership'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(path),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('Actual mount ownership statements passed error-cleanup and clone scenarios')
