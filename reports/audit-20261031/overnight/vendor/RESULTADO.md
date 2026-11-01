# Comparador de vendor pronto para CI

Não foi baixada a nova vendor nesta tarefa e não há conclusão sobre sua
qualidade ou compatibilidade. A parte concretamente finalizada é um módulo
portátil de reconstrução/comparação, com baseline real exportada.

Entrega de código e dados: `ci-r8q/vendor_audit/`.

- `audit_vendor.py`: CLI `export-baseline --image --output` e
  `audit --source --transfer --baseline --output`.
- `ext4_readonly.py`: leitor ext4 offline, sem montagem/escrita, com métodos
  explícitos para arquivos, stat, diretórios e symlinks.
- `requirements.txt`: Brotli 1.2.1 para o job que já tenha obtido o asset.
- `data/vendor.transfer.list`: lista fornecida, full v4, SHA256
  `842d27abf8b27160c57ebf8bf0872c358e4adb75c374f15c6b7e947794a70e26`.
- `data/baseline-vendor.zip`: 2.306.551 bytes, SHA256
  `320fab260c5b571fb3cde1288d30d67b904ef7c5381e4b1d73715ddf2867699e`.

A baseline vem da imagem vendor efetivamente usada na P0, SHA256
`18e48f734c31f263f330786ffea841738a733784da05b5b6d86b5e5217d82d5f`,
1.647.726.592 bytes. O exportador conferiu essa identidade completa antes de
ler o filesystem. Exportou 2.819 arquivos e 371 configs, incluindo CIL,
file_contexts/property_contexts sem extensão, VINTF, init, fstab, propriedades e
`.conf` de hardware. Os 166 configs comuns com extrações anteriores independentes
via debugfs possuem os mesmos hashes. Nenhuma imagem P0 foi alterada.

O analisador parcial antigo tinha uma falha concreta: tratava os elementos de
`Ext4.list_dir()` como dicionários, enquanto a API retorna tuplas `(nome, is_dir)`.
O módulo novo trata corretamente as tuplas e tem teste específico dessa API.
Não é necessário usar o analisador Windows parcial antigo no CI.

Na execução futura, o asset Brotli é recusado se tamanho ou SHA diferir dos
936.067.987 bytes e
`2d80788f5336cf82aa1a3e8c625f8942aac410be014a820186369173946199af`
fornecidos para o release. A transfer list é fixada pelo hash correspondente.
O parser exige cobertura integral da imagem, sem gaps/overlap/incremental.
A lista real passou: 799 comandos, 791 new e 8 zero, imagem 1.687.379.968 bytes.

Reconstrução usa um arquivo local novo, não um dispositivo. Intervalos zero/erase
ficam zerados no arquivo esparso novo. Truncamento, dados Brotli extras e saídas
anteriores são recusados. No Ubuntu, o CI deve fornecer e2fsck; se disponível,
`e2fsck -f -n` é executado e um resultado não limpo interrompe a análise.

`analysis.json` compara arquivo/tamanho/hash, modo/uid/gid, symlinks, categorias
de configuração e propriedades declaradas por arquivo. O ZIP de relatório inclui
configs antigos/novos e fsck, sem incluir a imagem ou os APK/SO completos. Uma
versão Android/ColorOS declarada em propriedades não é confundida com a versão
efetiva do sistema ou com compatibilidade melhor.

Treze testes passaram: ranges fora de ordem e zeros corretos, incremental,
overlap/gaps, Brotli truncado/sobrando, preservação de saída anterior, API tuplas,
seleção de contextos sem extensão, carga da baseline real, baseline desconhecida,
comparação de propriedades/metadados e parser da transfer list real. Evidência:
`tests.log`. Sintaxe Python dos três módulos passou.

Limites explícitos: arquivos regulares acima de 64 MiB não são hasheados;
xattrs/checksums/journal não são validados pelo leitor Python; o ext4 não suporta
todos os features e rejeita layouts desconhecidos. Não verifica boot, SELinux
compilado, ABI/linker nem funcionamento de HAL. A comparação da nova vendor
depende da execução do job com o asset disponível. Não se recomenda instalá-la
nem anunciá-la como melhor antes dessas validações.
