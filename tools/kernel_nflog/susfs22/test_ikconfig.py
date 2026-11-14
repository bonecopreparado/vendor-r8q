"""Run the actual IKCONFIG prerequisite rule with distinct real/stock inputs."""
from pathlib import Path
import gzip
import subprocess
import sys
import tempfile

text=(Path(sys.argv[1])/'kernel/Makefile').read_text()
lines=text.splitlines()
matches=[i for i,line in enumerate(lines)if line.startswith('$(obj)/config_data.gz:')]
if len(matches)!=1:
    raise ValueError('Expected exactly one IKCONFIG gzip prerequisite rule')
i=matches[0]
rule='\n'.join(lines[i:i+2])+'\n'
with tempfile.TemporaryDirectory()as work:
    root=Path(work)
    (root/'out').mkdir()
    (root/'arch/arm64/configs').mkdir(parents=True)
    actual=b'CONFIG_KSU_SUSFS=y\nCONFIG_NETFILTER_NETLINK_LOG=y\n'
    (root/'actual.config').write_bytes(actual)
    (root/'arch/arm64/configs/stock-defconfig').write_bytes(b'CONFIG_STALE_FIXTURE=y\n')
    make='obj := out\nKCONFIG_CONFIG := actual.config\nif_changed = gzip -n -c $< > $@\n'+rule+'\n.PHONY: FORCE\nFORCE:\n'
    (root/'Makefile').write_text(make)
    subprocess.run(['make','out/config_data.gz'],cwd=root,check=True,capture_output=True)
    if gzip.decompress((root/'out/config_data.gz').read_bytes())!=actual:
        raise ValueError('IKCONFIG still embeds a stock config instead of the real build')
print('Actual IKCONFIG rule embeds the generated configuration, not the stock fixture')
