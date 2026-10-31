"""Package tools and audit evidence only; no ROM images or device/user logs."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output'
OUT.mkdir(exist_ok=True)
destination = OUT / 'Auditoria-R8Q-20261031.zip'
readme = '''AUDITORIA R8Q - EXPERIMENTAL - SEM BOOT CONFIRMADO

Este pacote reune o corretor Windows P0r7, diagnostico somente leitura r2,
compilador SELinux Linux (se compilado no CI) e relatorios. Nao e a ROM completa
e nao deve ser instalado diretamente no recovery.

P0r7: extraia Correcao-P0r7-Windows.zip junto de runtime em Montar-P0-Windows.
Arraste o INSTALAR-P0r6.zip ou INSTALAR-P0r5.zip PEQUENO sobre CORRIGIR-P0r7.cmd.
Aguarde PRONTO; copie so INSTALAR-P0r7.zip novo para a pasta do celular com
os mesmos 22 payloads e selecione esse novo instalador no OrangeFox.

Diagnostico-Leitura-R8Q-r2.zip e selecionado diretamente no OrangeFox e so le.
Esta revisao usa comparacoes textuais para offsets e registra limites do shell.
O diagnostico anterior r1 foi substituido por tambem ter comparacao numerica.

Os sintomas em 2 e 4 GiB foram reproduzidos num mksh real no Linux: divisao
overflowa em 2 GiB e comparacao numerica reconhece 4 GiB como zero. P0r7 usa
contagem de blocos pequena, comparacao textual e pre-validacao AWK de offsets.
Os hashes continuam obrigatorios. Falta execucao real do P0r7 no OrangeFox.

SELinux: consulte evidence/policy/result.json e logs. Uma compilacao aprovada
no host nao resolve sozinha contextos, semantica dos aliases ou kernel/runtime.
As imagens da ROM P0 nao foram alteradas por este pacote. VINTF tem pendencias.
Policy binaria de pesquisa e CIL nao sao distribuidos como patch flashavel aqui.
Se falhou apos gravar super, restaure a base antes de iniciar o estado incompleto.
'''
members = {'COMECE-AQUI.txt': readme.encode('utf-8')}
for name in ('Correcao-P0r7-Windows.zip', 'Diagnostico-Leitura-R8Q-r2.zip'):
    path = OUT / name
    if path.is_file(): members[name] = path.read_bytes()
for name in ('secilc-host', 'check-policy-caps', 'compiler-sha256.txt', 'selinux-source-commit.txt'):
    path = ROOT / 'build' / name
    if path.is_file(): members['linux-tools/' + name] = path.read_bytes()
policy = ROOT / 'ci-results/policy'
if policy.exists():
    for path in policy.iterdir():
        if path.is_file() and path.suffix in ('.json', '.log'):
            members['evidence/policy/' + path.name] = path.read_bytes()
reports = ROOT / 'reports/audit-20261031/overnight'
if reports.exists():
    for path in reports.rglob('*'):
        if path.is_file() and path.suffix in ('.md', '.diff', '.json', '.txt') and path.stat().st_size < 2*1024**2:
            if 'mksh-src' not in path.parts and 'policy-bundle' not in path.parts:
                members['evidence/audit/' + path.relative_to(reports).as_posix()] = path.read_bytes()
for path in (ROOT / 'ci-results').glob('*.txt'):
    members['evidence/tests/' + path.name] = path.read_bytes()
members['SHA256SUMS.txt'] = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n' for name, data in sorted(members.items())).encode()
with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=False) as z:
    for name, data in sorted(members.items()):
        i = zipfile.ZipInfo(name, date_time=(2026, 10, 31, 0, 0, 0))
        i.create_system = 3
        i.external_attr = (0o100755 if name in ('linux-tools/secilc-host','linux-tools/check-policy-caps') else 0o100644) << 16
        i.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(i, data, compresslevel=6)
with zipfile.ZipFile(destination) as z: assert z.testzip() is None
sha = hashlib.sha256(destination.read_bytes()).hexdigest()
(OUT / (destination.name + '.sha256')).write_text(sha + '  ' + destination.name + '\n')
print(json.dumps(dict(file=str(destination), bytes=destination.stat().st_size, sha256=sha), indent=2))
