# P1r2: falha ao criar temporário do mksh antes da gravação

O recovery.log recebido em 7 de novembro contém duas tentativas de ADB sideload.
Nas duas, o ZIP de 5.387.889.413 bytes alcança o leitor r8q-zipread 2 e aborta com
`/tmp/updater[231]: can't create temporary file : No such file or directory`.
Isso ocorre ao processar o here-document da tabela de payloads, antes da
verificação completa das partes e de qualquer gravação em super/boot/dtbo.

A pasta WORK sob /tmp havia sido criada e já passara pelos testes de escrita e
leitura. O shell, porém, não recebia uma configuração TMPDIR para seus próprios
temporários. A correção fixa e exporta TMPDIR para WORK e substitui o here-document da tabela
por printf de texto literal, eliminando a dependência do temporário interno. O valor anterior de TMPDIR não aparece no log; não se afirma seu
caminho exato. Caminhos inexistentes e caminhos que apontam para arquivo são
casos de reprodução, não valores supostamente coletados do aparelho.

Os 182 testes gerais passaram na primeira CI. O mksh Linux não reproduziu o erro
antigo com TMPDIR inválido: esse comportamento depende do ambiente/build do
recovery. A regressão verifica a construção real da tabela sem here-document,
além dos cenários completos do instalador com TMPDIR inválido e partições
simuladas. A confirmação no recovery Android permanece pendente.
O template histórico P0r8 permanece com o hash fixado.

A revisão do ZIP recebe release separado com TMPFIX no título e na tag.
O nome do arquivo e o rótulo P1r2 são mantidos; o novo SHA256 e a origem da
release identificam esta revisão. As imagens são reconstruídas com o mesmo
plano P1r2; não há correção causal do bootloop Android anunciada.
Logs brutos e identificadores do telefone não foram publicados.
