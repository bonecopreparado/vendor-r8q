"""Reproduce the recovery's mksh here-document failure without device access."""
import os, pathlib, subprocess, sys, tempfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'tools'))
from p1_single_template import template
text=template(build_label='P1r2')
start=text.index('cat > "$WORK/payload.rows"')
end=text.index('row_count=0',start)
heredoc=text[start:end]
start=text.index('TMPDIR="$WORK"')
pin=text[start:text.index('DD_FSYNC=0',start)]
shell=os.environ.get('MKSH_BINARY','mksh')
with tempfile.TemporaryDirectory() as directory:
    root=pathlib.Path(directory)
    valid=root/'work';valid.mkdir()
    regular=root/'regular';regular.write_text('not a directory')
    for bad in (root/'missing',regular,root/'missing with spaces'):
        env=dict(os.environ,TMPDIR=str(bad),WORK=str(valid))
        old=subprocess.run([shell,'-c','set -eu\n'+heredoc],env=env,capture_output=True)
        assert old.returncode!=0 and b'temporary file' in old.stderr,old.stderr
        assert not (valid/'payload.rows').read_bytes() if (valid/'payload.rows').exists() else True
        fixed=subprocess.run([shell,'-c','set -eu\n'+pin+heredoc],env=env,capture_output=True)
        assert fixed.returncode==0,fixed.stderr
        assert (valid/'payload.rows').read_text()=='@@PAYLOAD_ROWS@@\n'
        (valid/'payload.rows').unlink()
        print('Old failure reproduced; fixed heredoc passed:',bad.name,flush=True)
print('3 old-failure reproductions and 3 fixed cases passed; no device writes')
