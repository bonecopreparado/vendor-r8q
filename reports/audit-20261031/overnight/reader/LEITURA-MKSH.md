# Dois erros reproduzidos no shell de 32 bits; dd não é a causa demonstrada

## Descoberta

A semântica inteira de mksh é de 32 bits por padrão, mesmo quando o binário e
o sistema operacional são de 64 bits. As duas mensagens dos logs podem ser
reproduzidas exatamente no shell, sem modificar o dd e sem aparelho Android.

Foi compilado mksh R59 no host a partir dos 28 arquivos de
`NetBSD/pkgsrc/shells/mksh/files`. Todas as identidades de blob Git conferem
com a listagem da API; registro em `mksh-src/SOURCE.json`. Fonte `sh.h`, linhas
208–223, declara `mksh_ari_t=int32_t` fora de `MKSH_LEGACY_MODE` e documenta
wraparound garantido para aritmética, divisão e módulo.

Execução real de `mksh-src/mksh`, não um shim de aritmética:

```text
version=@(#)MIRBSD KSH R59 2020/05/16
p0r5_skip=-524288
numeric_zero=1
string_zero=0
p0r6_length=536866816
p0r6_blocks=131071
```

### P0r5 / recovery(4): o próprio shell produziu o skip negativo

O script usa `start=2147483648` e passa `skip="$((start/4096))"` ao dd.
No mksh, esse cálculo dá `-524288`. Isso corresponde exatamente à mensagem
`dd: -524288 < 0`. Logo, esse log não demonstra overflow de multiplicação no
dd: o chamador já pode ter entregue um argumento negativo.

### P0r6 / recovery(5): a nona parte foi tratada como se fosse a primeira

Em super-008, `offset=4294967296`. No mksh,
`[ "$offset" -eq 0 ]` é verdadeiro, pois o teste numérico também aplica a
semântica inteira que reduz esse valor a zero. O teste por string
`[ "$offset" = 0 ]` é falso, como deveria.

Assim, o ramo destinado somente à primeira parte foi repetido em 4 GiB:

1. descarta mais 4096 bytes da leitura;
2. calcula `length=536870912-4096`;
3. pede `count=131071` ao dd.

O dd retorna 131071 blocos / 536866816 bytes, exatamente o recovery(5).log.
Não é necessário assumir que dd pediu 131072 e perdeu um bloco: o script
pode ter pedido 131071 devido ao ramo errado. O contador em bytes `cursor`
também volta a zero em 4 GiB; o teste `-eq` compara os dois zeros resultantes.
O mesmo erro voltaria a ocorrer em 8 GiB.

Essa é uma reprodução concreta e completa do sintoma com mksh real. O binário
`/sbin/sh` exato do tester ainda não foi identificado; não afirmar que rodamos
o binário dele. O próximo log deve registrar KSH_VERSION e caminho/ELF do shell.
Não inferir defeito físico nem integridade de toda super a partir desses logs.

## Correção P0r7 preparada

Gerador: `tools/prepare_p0r7_installer.py`.
Template: `delivery/Revisao-P0r7-Windows/p0r7-assets/installer-template.sh`.

- Zero do offset é comparado por string: `[ "$offset" = 0 ]`.
- Aritmética de offsets em bytes fica no AWK, que representa esses inteiros
  de até 10 GiB exatamente. Validação ocorre antes de gravar: campos decimais
  canônicos, formato SHA, ordem de nomes, contiguidade, alinhamento, limites
  de parte e cobertura total de cada partição.
- Cursor do shell passa a contar blocos de 4 KiB, nunca bytes. A super completa
  mede só 2.512.896 blocos, bem abaixo de 2^31. Comprimentos por chamada de dd
  continuam em até 512 MiB.
- Todas as capacidades absolutas são comparadas como strings, como já fazia
  `check_size`. A contagem dos arquivos comprimidos é limitada a 1 GiB no AWK;
  os demais testes/cálculos inteiros do shell só recebem valores pequenos.
- Mostra `2147483647+1` como diagnóstico de aritmética, sem exigir shell de
  64 bits. Preserva contagem exata do prefixo e a UI quando OUTFD=9.
- Todos os hashes de entrada e retorno, proteções de AVB/capacidade/geometria,
  montagens, origem dos payloads e método de escrita permanecem obrigatórios.

Um helper C próprio não é necessário para corrigir os dois bugs identificados.
Ainda pode ser uma alternativa futura, mas adicionaria binário, ABI, toolchain
e validação sem resolver melhor esse erro específico do chamador.

## Verificações novas

`test_shell32_regression.py` é portátil e aceita MKSH_BINARY,
R8Q_PROJECT_ROOT, --old-template, --new-template e --report-dir.
Usa mksh real e GNU dd sem shim. O arquivo esparso tem a capacidade real da
super e marcadores distintos no início/fim de cada região de 512 MiB:

1. reproduz ambos os cálculos incorretos no mksh;
2. P0r6 falha exatamente em super-008;
3. P0r7 valida os 20 hashes até o fim dos 10 GB, com UI em FD9, e valida antes
   a tabela completa de offsets de 10 GB pelo AWK;
4. corrupção em 8 GiB continua detectada em super-016;
5. truncamento da última região continua detectado em super-019.

`test_installer_mock_mksh.py` porta o harness completo para um shell mksh real
e remove dependência de imagens de ROM. Embute somente os cabeçalhos AVB de
256 bytes e a estrutura LP de 52 bytes das coletas. Além dos 32 cenários
anteriores, verifica cinco erros de tabela (offset 4 GiB indevido, gap,
desalinhamento, hash malformado e tamanho gzip 4 GiB); todos devem abortar
antes de alterar qualquer imagem fixture.

As execuções e limites estão em `shell32-regression-tests.txt`,
`shell32-results.json`, `installer-mksh-tests.txt` e `installer-results.json`.
Nenhuma gravação em telefone foi feita. Esses testes não confirmam boot,
SELinux, HALs ou o comportamento do binário exato do recovery do tester.
