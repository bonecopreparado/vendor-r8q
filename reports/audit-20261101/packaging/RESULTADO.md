# Revisão independente do empacotamento Windows P0r7 e análise de vendor

Nenhum arquivo de produção, imagem ou artefato publicado foi modificado nesta
revisão. Os únicos novos arquivos são este relatório e probes em diretório de
auditoria. Os probes usam arquivos temporários pequenos; não executam comandos
em dispositivos nem repetem a regressão de largura do mksh já identificada.

## Resultado principal

Não encontrei um novo defeito de empacotamento que explique uma falha real da
P0r7 ou justifique gerar outra revisão de instalador neste momento. O comentário
do tester referido pelo usuário era sobre P0r3, não um recovery.log novo da P0r7.

Confirmações de integridade:

- `output/Correcao-P0r7-Windows.zip`: SHA256
  `2a036a0accd69094737113f5ef8a8987b45aa00d1c95d1746687d335e586acf6`.
- Os nove arquivos desse ZIP coincidem byte a byte com os fontes atuais em
  `delivery/Revisao-P0r7-Windows/`; não há template ou corretor antigo misturado.
- Os templates P0r5/P0r6 aceitos pelo corretor são idênticos aos assets dos ZIPs
  anteriormente entregues. Não encontrei rejeição causada por um template de
  origem alterado depois da publicação.
- Os ZIPs P0r7, diagnóstico r2 e relatório de vendor presentes no bundle unificado
  local são idênticos aos respectivos arquivos de saída. A entrega registrada
  em `ENTREGA-20261101.json` informa o bundle como
  `e27d2d2308a88f3fadc3b283eeaf0cb05c890ed09d37337ca827145659927c92`.

## Saída parcial, aliases e concorrência

Probes adicionais passaram ao tentar gerar P0r7 com um destino que é symlink
para arquivo existente, symlink pendurado e resultado que aparece durante a
validação. Em todos os casos a saída foi recusada e o destino anterior ficou
intacto. A criação exclusiva por hard link no POSIX continua protegendo o rename
que sobrescreveria um arquivo. No ramo Windows, `Path.rename` recusa destino
existente e admite FAT/exFAT; esse ramo não foi executado num Windows real aqui.

O corretor verifica os 22 arquivos comprimidos e os bytes descomprimidos antes de
publicar, confere o ZIP pequeno por releitura/CRC e conserva o original. Falhas
de criação deixam somente `.partial-*`, que não deve ser usado. Os hashes são
novamente verificados no recovery, portanto a verificação no PC não é usada
como substituta da verificação após copiar para o telefone.

## Melhorias possíveis, sem impacto causal demonstrado

### 1. Tipos numéricos do JSON não são estritos no corretor

Python considera `0.0 == 0` e `False == 0`. O teste de igualdade dos campos raw
contra o layout confiável aceita esses tipos na entrada. Um probe coordenado
alterando o offset no JSON **e também rerenderizando o instalador de origem**
conseguiu gerar um novo ZIP com offset `0.0`/`False` na tabela.

A proteção AWK da P0r7 recusou ambos por `inteiro nao canonico` antes de qualquer
escrita. Não é um bypass de hash, não ocorre com os ZIPs originais e uma alteração
somente no manifesto já seria recusada pelo vínculo com o instalador de origem.
É oportunidade de falhar mais cedo no PC: exigir `type(value) is int` nos campos
inteiros ou reconstruir os campos raw a partir do layout confiável antes de
renderizar, aceitando da entrada somente metadados gzip validados.

### 2. Baseline da vendor: CLI isolada versus job publicado

O loader isolado verifica identidade da imagem declarada no JSON, CRC e hashes
dos configs, mas não o SHA256 do arquivo baseline inteiro. Um ZIP sintético com
identidade de imagem autodeclarada e config inventado é aceito pela API isolada.

O workflow publicado verifica explicitamente o SHA256 fixo
`320fab260c5b571fb3cde1288d30d67b904ef7c5381e4b1d73715ddf2867699e`
do baseline **antes** da análise. O ZIP sintético não passa por essa etapa.
Não encontrei contaminação da baseline usada no CI ou nos relatórios publicados.
Uma futura versão standalone pode validar também o hash declarado em
`data/sources.json` para manter a mesma garantia fora do workflow.

### 3. Categorias de configs são diferenças de conteúdo

Uma mudança somente de modo/uid/gid aparece corretamente em `metadata_changed`,
mas não em `config_categories`, que é calculado com adição/remoção/SHA alterado.
Um probe de chmod em fstab produziu esse comportamento. Não há perda no campo
de metadados, mas consumidores devem consultá-lo também antes de concluir que
uma categoria está inteiramente igual. Pode-se documentar o nome como categorias
de conteúdo ou incluir um agrupamento separado de metadados.

## Evidências e limites

`probe_packaging.py`, `probe.log` e `probe-results.json` registram sete cenários
novos: dois tipos de offset não canônico, dois aliases de saída, corrida de
publicação, baseline standalone sintética e mudança de metadados de config.
Todos os resultados esperados foram confirmados.

Não houve teste em Windows real, flash ou execução de boot. Não se retirou
checagem para fazer uma montagem passar. As observações acima são limites de
validação e oportunidades de melhoria; não são evidência de um novo erro no
telefone nem motivo para substituir o pacote P0r7 por outra revisão sem um
recovery.log atual.
