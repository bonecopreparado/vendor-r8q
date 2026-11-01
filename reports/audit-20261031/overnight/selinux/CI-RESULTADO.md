# Compilação integral e auditoria de controle

A execução real do GitHub Actions 41249309007 compilou libsepol/secilc do pin
6423998bc7b154da7f9fe726cfda9ace774dfa94. A política original reproduziu a falha
de alias esperada. O candidato de três mudanças compilou com as flags usadas
pelo init, inclusive `-N`, sem remover capabilities. A política serializada tem
versão 30, 1.975.722 bytes e SHA256
70278111389ef8affecddf0eee346f4d3cba4b72fe7bc907e512f7c610d769ad.

Um checker ligado à mesma libsepol reabriu o arquivo e confirmou os seis bits de
policycap, inclusive `functionfs_seclabel`. Isso supera o limite da libsepol antiga
do host. Os executáveis Linux, hashes e proveniência estão em tools/selinux-modern.

A execução adicional sem `-N` encontrou 335 registros de violação neverallow
(334 textos distintos). Por esse critério adicional, o job terminou vermelho;
o compilador e os testes do instalador passaram. Não removeram asserts ou regras
para obter sinal verde. O modo normal de compilação de split policies pelo init
não reavalia essas assertions entre as versões dessa maneira; ainda é necessário
revisar a semântica e não interpretar o número como 335 bugs runtime comprovados.

## Controle para avaliar as três mudanças

Foi compilada uma variante exclusivamente diagnóstica que mantém os tipos do
framework separados e renomeia somente os dois aliases Samsung conflitantes.
As regras, assertions e os tipos reais vendor permanecem; o atributo versionado
ausente recebe a mesma declaração da candidata. Nenhuma variante foi aplicada
à ROM. Ambos os modos init compilaram e preservaram os seis policycaps.

A auditoria neverallow do controle e da candidata apresentou os mesmos 335
registros/334 textos canônicos, mesmos conjuntos de allows correspondentes e
nenhum texto exclusivo de um dos lados. Isso mostra que as violações impressas
não surgem por causa da fusão desses dois aliases. Não prova equivalência de
permissões/contextos entre as duas políticas nem valida o comportamento do kernel.

Fontes dos registros na candidata: 225 plat novo, 101 plat_pub_versioned antigo,
7 system_ext, 1 product e 1 vendor. O parser preserva ocorrências duplicadas em
vez de descartar silenciosamente uma delas. A análise reutilizou os quatro logs
de compilação já gerados; corrigiu apenas o agrupamento de assertions duplicadas.
Ver neverallow-analysis/summary.json, candidate-assertions.json e
control-assertions.json, com hashes das evidências anteriores.

Conclusão limitada: o conflito estrutural de compilação tem uma correção mínima
que gera um binário válido no host com todas as capabilities preservadas. A
seleção final da vendor, revisão de tipos/contextos, VINTF, geração de uma imagem
coerente e teste de boot continuam pendentes. Não foi distribuída política como
patch flashável e nenhum filesystem da P0 foi alterado.
