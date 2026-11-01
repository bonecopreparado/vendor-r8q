# Comentário do tester sobre update-binary

O usuário esclareceu que “I think problem in update.binary16:11” era sobre a
P0r3. Não foi apresentado erro/log novo da P0r7. `16:11` não é evidência de
número de linha; pode ser o horário da conversa.

O componente é `META-INF/com/google/android/update-binary`. Neste projeto ele
é um script shell, executado pelo OrangeFox; `updater-script` só tem comentário.
Na P0r3, update-binary-v3:106 exige `dd ... iflag=fullblock`. O recovery recusou
essa opção e o script abortou com “dd sem iflag=fullblock; nada foi gravado”.
O requisito foi corrigido na P0r4, e a P0r7 conserva o método portátil.
O comentário antigo é consistente com o diagnóstico conhecido; não estabelece
defeito novo na P0r7.

Os demais erros históricos eram diferentes: falha na pipeline de leitura do ZIP
gigante na P0r4 (processo responsável não identificado pelo log) e aritmética/
comparação numérica de 32 bits em P0r5/P0r6. A P0r7 usa partes externas e evita
offsets em bytes nas operações inteiras do shell.

## Revisão adicional

- Kit publicado, nove fontes, templates de origem e três ZIPs internos do bundle
  coincidem. CRCs passaram; não se encontrou instalador antigo misturado.
- Sete probes de empacotamento cobriram saídas existentes, symlinks, corrida de
  publicação e oportunidades de validar mais estritamente no PC. A checagem AWK
  já recusa offsets não canônicos antes de escrever no recovery.
- Dezenove casos de borda passaram, incluindo SAR, UI em FD3/8/9, temporários,
  falha de flush e leitura curta. Foi encontrado um caso secundário de paths:
  pontos de montagem de sistema com espaços/tabs/backslash chegam codificados
  ao umount e causam aborto antes da escrita. Isso não é o mesmo que espaço
  na pasta do ZIP e não foi demonstrado no aparelho do tester.
- Patch isolado em patches/0002-recovery-mount-paths, NON_SHIPPING; 37 regressões
  passaram no candidato. Não se alteraram a P0r7, seus pins ou pacotes públicos.
  Não foi publicada uma P0r8 por causa desse comentário antigo.
- A auditoria VINTF foi refinada com fontes Android e dados originais do Mi 10;
  gaps de XML não devem ser automaticamente tratados como bloqueio de boot.
  A falta de matriz FCM4 afeta depreciação no check host/OTA, mas não impede
  sozinha combinar as matrizes em runtime. VNDK30/34 e API SELinux30.0/31+
  continuam divergentes nos XML; o próprio doador já declara os mesmos valores
  antigos da Samsung. Não foi executado checkvintf nem confirmado bypass OEM.

Nenhum telefone foi acessado. Os testes não comprovam boot, HALs nem execução
no OrangeFox exato. O estado físico atual do telefone depende do último log
real, não desse comentário antigo. As imagens da P0 continuam inalteradas.
