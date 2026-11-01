# Revisão independente adicional do instalador P0r7

A observação do tester sobre `update.binary` era referente à tentativa P0r3,
conforme esclarecimento recebido. Esta revisão procura problemas adicionais
na P0r7; não atribui as limitações abaixo à tentativa antiga e não interpreta
`16:11` como número de linha do código.

Fonte publicada examinada:
`delivery/Revisao-P0r7-Windows/p0r7-assets/installer-template.sh`.
SHA256 mantido sem alteração:
`690280161dfa294add407fcb6fa1e853c531b24dc52a38081ba6bcb022aa0ea6`.

## Resultados

Não foi identificado novo defeito crítico demonstrado no fluxo normal de
instalação r8q nos aspectos examinados: descritores, temporários, traps,
propagação de erros, montagens SAR, leituras curtas e flush.

Foi reproduzida uma limitação de compatibilidade que aborta de forma segura:
os pontos de montagem lidos de `/proc/mounts` permanecem codificados quando
passados a `umount`. O kernel representa espaço por `\040`, tab por `\011` e
barra invertida por `\134`. O argumento de `umount` deve conter o caminho real.

| Entrada em /proc/mounts | Argumento atual de umount | Resultado atual |
|---|---|---|
| `/vendor/cache\040files` | `/vendor/cache\040files` literal | Aborta antes de escrever |
| `/vendor/cache\011files` | `/vendor/cache\011files` literal | Aborta antes de escrever |
| `/vendor/cache\134files` | `/vendor/cache\134files` literal | Aborta antes de escrever |
| `/vendor/cache\134040files` | `/vendor/cache\134040files` literal | Aborta antes de escrever |

Isso só afeta uma montagem de sistema ou descendente cujo ponto de montagem
contenha esses caracteres. Espaços no nome da pasta ou do ZIP em armazenamento
externo não são o mesmo caso: os caminhos de payloads já ficam entre aspas e
a origem de montagem usa decodificação própria. Não há evidência de que essa
condição tenha ocorrido no aparelho do tester.

Outra oportunidade de diagnóstico foi reproduzida: se `sort` falhar na criação
de `mount_list`, a P0r7 sai com o status do processo (na fixture, 77) sem uma
mensagem `ERRO:` própria. O `set -e`/`pipefail` interrompe antes da primeira
gravação, e o temporário é removido. Isso não burla verificações nem demonstra
a causa de qualquer erro do tester. Poderia receber `|| abort ...` específico
numa revisão futura, assim como duas atribuições dos probes de hash e a leitura
final de `/proc/mounts`; não foi alterado nesta rodada.

## Patch isolado: não entregue para flash

`patches/0002-recovery-mount-paths/` contém:

- `candidate.diff`: mudança somente no tratamento do caminho de `umount`;
- `installer-template-candidate.sh`: cópia isolada para testes;
- `status.json`: estado `NON_SHIPPING`, origem e SHA fixados.

SHA256 do candidato:
`76d344f3a7b0be6aafd52d34a84509ec4ac2a90adfb3c9bd7fa95caf696fe737`.

O candidato decodifica uma única vez as sequências `040`, `011` e `134` usando
um parser literal no AWK. Transporta o texto por `ENVIRON`, evitando que `awk
-v` ou `printf %b` interpretem escapes por conta própria. Assim, `\134040`
vira uma barra invertida seguida dos caracteres `040`, e não um espaço.
Recusa `\012` (newline) e qualquer escape desconhecido, antes de chamar
`umount` e antes de gravar. Mantém a validação do prefixo do caminho, a falha
fechada se `umount` falhar e as verificações finais de montagens/dispositivos.

O template publicado, os pins e os kits publicados permanecem intactos. Não
foi preparada ou publicada uma P0r8 para flash por causa desse caso de borda.

## Validação adicional em mksh real

**19 cenários de borda passaram**, com descritores e arquivos regulares:

- SAR em `/system_root`, incluindo montagem descendente; filhos desmontados
  antes dos pais;
- UI nos descritores 3, 8 e 9;
- quatro caminhos codificados: P0r7 publicada aborta sem escrita e candidato
  desmonta usando o argumento real correto;
- newline recusado antes da chamada de `umount`;
- falha realista de `umount` após a decodificação aborta sem escrita;
- falha de `sort` aborta sem escrita, preservando o status;
- falhas de fsync ou sync depois da gravação de super interrompem antes de
  DTBO/boot e pedem restauração;
- dd retornando sucesso após uma leitura curta é recusado pelo hash de retorno.

Em todos esses cenários, o prefixo de super permaneceu igual e o diretório
temporário privado foi removido, incluindo os casos de falha após escrita.
O hook de `umount` exige correspondência com o caminho real montado e remove
somente aquela entrada, sem o atalho anterior de apagar todas as montagens.

**Os 37 cenários completos do instalador também passaram no candidato**,
reutilizando o harness de regressão sob mksh real. Eles cobrem entradas
inválidas, montagens por aliases/bind, flags AVB, geometria, tabela, integridade,
truncamento, falhas de processos e persistência de prefixo. Esta rodada não
repete nem reconta o teste anterior de 10 GB do conserto de aritmética.

Evidências nesta pasta:

- `test_mount_and_failure_edges.py`, `mount-and-failure-tests.txt` e
  `mount-and-failure-results.json` (19 cenários);
- `candidate-base-regression-tests.txt` e `installer-results.json`
  (37 cenários);
- `build_mount_path_candidate.py`, gerador do patch isolado.

## Limites

Nenhum comando de montagem ou flash real foi executado em telefone. Os testes
usam arquivos temporários com capacidades instrumentadas e hooks de processos.
Não equivalem a validar o binário exato do recovery, todos os possíveis
mapeamentos dm/overlay ou o firmware. A verificação AVB continua sendo de
cabeçalho/flags, não uma verificação criptográfica completa da cadeia.
Boot, SELinux, VINTF e funcionalidades de hardware não são confirmados por
essa revisão do instalador.
