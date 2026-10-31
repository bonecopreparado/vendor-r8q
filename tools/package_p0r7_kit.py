"""Build a small offline Windows patcher; source images are never repackaged."""
from pathlib import Path
import hashlib
import json
import os
import zipfile

ROOT = Path(os.environ.get('R8Q_PROJECT_ROOT', Path(__file__).resolve().parents[1]))
KIT = ROOT / 'delivery/Revisao-P0r7-Windows'
ASSETS = KIT / 'p0r7-assets'
ASSETS.mkdir(parents=True, exist_ok=True)
for name, source in [
    ('chunks.json', ROOT / 'delivery/Revisao-P0r5-Windows/p0r5-assets/chunks.json'),
    ('installer-p0r5.sh', ROOT / 'delivery/Revisao-P0r5-Windows/p0r5-assets/installer-template.sh'),
    ('installer-p0r6.sh', ROOT / 'delivery/Revisao-P0r6-Windows/p0r6-assets/installer-template.sh')]:
    (ASSETS / name).write_bytes(source.read_bytes())
(ASSETS / 'LEIA-ME.txt').write_text('''HyperOS4 -> R8Q P0r7 EXPERIMENTAL

Reaproveita os mesmos 22 gzip da P0r5/P0r6. Instalar INSTALAR-P0r7.zip com
payloads ao lado. Nao precisa recomprimir ou baixar as imagens novamente.
Corrige aritmetica/testes de 32 bits do mksh: em P0r5 a conta do offset de
2 GiB virava negativa; em P0r6 a comparacao numerica tratava 4 GiB como zero,
descartando indevidamente 4096 bytes. Reproduzido num mksh real no Linux.
P0r7 usa comparacao textual para zero e contador em blocos de 4096 bytes.
AWK confere a tabela inteira antes da escrita. Os hashes permanecem obrigatorios.

Nao ha troca de vendor, kernel, DTBO ou conteudo dos filesystems nesta revisao.
As imagens continuam da P0; SELinux e VINTF tem pendencias documentadas.
Somente super, dtbo e boot sao gravados. Nao formata userdata. Sem boot confirmado.
Se falhar apos comecar a gravar, mantenha no recovery e restaure a base antes de
outro boot. Se concluir, reinicie primeiro para RECOVERY para atualizar mappings.
''', encoding='utf-8')
(KIT / 'COMECE-P0r7.txt').write_text('''CORRECAO P0r7 - SHELL COM ARITMETICA DE 32 BITS

1. Extraia este kit junto de runtime, dentro de Montar-P0-Windows.
2. Arraste INSTALAR-P0r6.zip (ou INSTALAR-P0r5.zip) PEQUENO sobre CORRIGIR-P0r7.cmd.
   Escolha o arquivo que tem a subpasta payloads ao lado no PC.
3. Aguarde conferir todas as partes e aparecer PRONTO.
4. INSTALAR-P0r7.zip sera criado ao lado da origem, preservando todos os dados.
5. Copie so o ZIP novo para a pasta do celular com os 22 gzip intactos.
6. No OrangeFox escolha INSTALAR-P0r7.zip.

Nao precisa refazer MONTAR-P0 ou PREPARAR-P0r5, nem copiar payloads novamente.
Precisa apenas de espaco para o ZIP pequeno/log. A verificacao pode demorar.
Nao use .partial-*.zip. Se falhar, envie correcao-p0r7-*.log ou recovery.log.

A causa anterior foi reproduzida no mksh real; falta testar este instalador no
OrangeFox do aparelho. Nao significa que o sistema HyperOS tenha boot confirmado.
As correcoes de politica SELinux e compatibilidade ainda sao trabalho separado.
''', encoding='utf-8')
(KIT / 'CORRIGIR-P0r7.cmd').write_bytes(b'''@echo off\r
setlocal\r
cd /d "%~dp0"\r
if not exist "%~dp0runtime\\python.exe" (\r
 echo Extraia este kit dentro de Montar-P0-Windows, junto da pasta runtime.\r
 pause\r
 exit /b 1\r
)\r
"%~dp0runtime\\python.exe" -X utf8 -u "%~dp0corrigir_p0r7.py" %*\r
set "R8Q_RESULT=%ERRORLEVEL%"\r
pause\r
exit /b %R8Q_RESULT%\r
''')
names = ['chunks.json', 'installer-p0r5.sh', 'installer-p0r6.sh', 'installer-template.sh', 'LEIA-ME.txt']
(ASSETS / 'pins.json').write_text(json.dumps({n: hashlib.sha256((ASSETS / n).read_bytes()).hexdigest() for n in names}, indent=2) + '\n')
out = ROOT / 'output/Correcao-P0r7-Windows.zip'
out.parent.mkdir(exist_ok=True)
files = [KIT / n for n in ['corrigir_p0r7.py', 'CORRIGIR-P0r7.cmd', 'COMECE-P0r7.txt']] + [ASSETS / n for n in names + ['pins.json']]
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=False) as z:
    for path in files:
        i = zipfile.ZipInfo(path.relative_to(KIT).as_posix(), date_time=(2026, 10, 31, 0, 0, 0))
        i.create_system = 3; i.external_attr = 0o100644 << 16; i.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(i, path.read_bytes(), compresslevel=6)
with zipfile.ZipFile(out) as z: assert z.testzip() is None and len(z.namelist()) == 9
print(out, out.stat().st_size, hashlib.sha256(out.read_bytes()).hexdigest())
