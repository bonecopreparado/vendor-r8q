# Estado atual — HyperOS para r8q

## Versão que foi entregue

**P1r2**, experimental, sem boot confirmado.

- Fonte: [a036e2ed34f82eab1cf6bea34b8ae8c81b6a0fa8](https://github.com/bonecopreparado/vendor-r8q/tree/a036e2ed34f82eab1cf6bea34b8ae8c81b6a0fa8).
- [Release e instruções](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r2-single-experimental-1-1).
- [Build concluído](https://github.com/bonecopreparado/vendor-r8q/actions/runs/41570865668).
- Arquivo: `HyperOS4-R8Q-P1r2-SINGLE-EXPERIMENTAL.zip`.
- Tamanho: 5.387.889.413 bytes.
- SHA256: `014965aadd4c35ab171dc1c3e7e7d3d633fd208c12e0ce6f3d556e594e5e5bcf`.

A fonte dessa release está no commit acima. O código histórico de P0 na
`main` não foi substituído por esta atualização de documentação.

## O que foi corrigido e o que permanece aberto

| Item | Situação da P1r2 | Limite da evidência |
| --- | --- | --- |
| Redeclaração de sysfs_battery_supply/sysfs_memory | Declarações conflitantes removidas do CIL de system_ext; alias Samsung preservado | Compilação host dos CIL exatos passou; carga no aparelho não demonstrada |
| Nove referências inválidas de contexto da P0 | Revisão de seapp e remoção do serviço/trigger logdumpd aplicadas; 2.879 válidas, zero inválidas | Não valida todas as decisões de acesso em runtime |
| Mapping system_ext/product | 23 arquivos removidos conforme experimento indicado pelo doador; mappings de system mantidos | Experimento, sem confirmação de que resolve o bootloop |
| ZIP/flash | ZIP64 corrigido; pacote completo; 22 payloads relidos pelo executável ARM64 emulado; 179 testes, 42 cenários mksh e 6 fixtures EROFS passaram | Não testa o cartão, driver ou recovery real |
| Readback do aparelho | Escrita usa fsync/sync; releitura atual pode usar cache do kernel | Não é prova independente de persistência física após perda de energia |
| hyper_bpfloader | Kernel sem FTRACE e comando reboot_on_failure confirmados; loader possui filtros e tratamento de objetos/programas opcionais | Falha obrigatória e motivo de reboot não capturados |
| VINTF, kernel e HALs | Incompatibilidades conhecidas permanecem | CI verde não significa compatibilidade geral |
| NFC, overlays, health e outros recursos | Há correção da declaração duplicada do serviço NFC Samsung; ausência da biblioteca Oplus e demais pontos continuam abertos | Nenhum hardware validado pelo boot de HyperOS |

## Evidência que falta

Os últimos logs enviados são do recovery. A tentativa P1r1 com CRC em
`super-012.gz` abortou antes das escritas; o cartão foi identificado como
exFAT. O SHA256 daquela cópia ainda não foi recebido. Não há retorno de teste
de boot da P1r2 até esta revisão.

Se uma instalação terminar e o aparelho reiniciar, precisamos do registro
daquele boot — pstore/last_kmsg ou o coletor já fornecido — para distinguir
falha de init/política, BPF, kernel, APEX ou outro serviço. Alterar somente o
reinício automático do BPF seria um experimento diagnóstico separado, não
uma implementação de FTRACE nem uma correção comprovada.

[Comparação detalhada com o relatório externo](reports/review-20261103/RESULTADO.md).
