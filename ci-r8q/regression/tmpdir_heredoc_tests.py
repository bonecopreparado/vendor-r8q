"""Exercise the actual payload-table command in mksh without device access."""
import os, pathlib, subprocess, sys, tempfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'tools'))
from p1_single_template import template
text=template(build_label='P1r2')
start=text.index("printf '%s")
# The table command is identified by its destination rather than other printf.
destination=' > "$WORK/payload.rows"\n'
end=text.index(destination)+len(destination)
start=text.rfind("\n",0,text.index("'@@PAYLOAD_ROWS@@'"))+1
command=text[start:end]
assert '<<' not in command and command.startswith("printf '%s")
sample='super super-000.gz 4096 '+'a'*64+' 128 '+'b'*64+' 0 '+'c'*64
command=command.replace('@@PAYLOAD_ROWS@@',sample)
shell=os.environ.get('MKSH_BINARY','mksh')
with tempfile.TemporaryDirectory() as directory:
    root=pathlib.Path(directory)
    valid=root/'work';valid.mkdir()
    regular=root/'regular';regular.write_text('not a directory')
    for bad in (root/'missing',regular,root/'missing with spaces'):
        env=dict(os.environ,TMPDIR=str(bad),WORK=str(valid))
        result=subprocess.run([shell,'-c','set -eu\n'+command],env=env,capture_output=True)
        assert result.returncode==0,result.stderr
        assert (valid/'payload.rows').read_text()==sample+'\n'
        (valid/'payload.rows').unlink()
        print('Payload table without here-document passed:',bad.name,flush=True)
print('3 real mksh cases passed; no device writes. Android recovery confirmation pending.')
