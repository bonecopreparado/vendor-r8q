# checkvintf oficial executado: P0 incompatível com a referência AOSP 17

O teste deixou de ser uma proposta: o `checkvintf` oficial de Android 17/API37
executou no GitHub sobre os metadados reais da composição P0. Os testes completos
retornaram **65 / INCOMPATIBLE**, tanto sem kernel quanto com o kernel/config
4.19.325 realmente incluído no boot da P0. Não houve alteração de imagem ou
gravação em aparelho.

Execução: https://github.com/bonecopreparado/vendor-r8q/actions/runs/41319419220

Ferramenta: build oficial AOSP 16644040, alvo
`aosp_cf_x86_64_only_phone-userdebug`, fingerprint
`Android/generic_system/generic:17/CP2A.260605.016/16644040:userdebug/test-keys`.
O prefixo CP2A.260605.016 coincide com a plataforma declarada pelo doador.
ZIP oficial de 531.408.471 bytes, SHA256
`bc85557aa0c59a7d0b48b8175250948d67b2d0f293bd74eb8d5753ba4ad7781f`.
Binário checkvintf SHA256
`6f7601b9409ac5db70d8b05bc98d117fe68456464e710eb2e2964c7edf1325db`.
Essas identidades estão fixadas em `ci-r8q/pins/official-otatools.json` para as
próximas execuções, que recusam um ZIP com hash diferente.

## Resultados observados

| Comando/escopo | Exit | Resultado |
| --- | ---: | --- |
| --check-one framework | 0 | Documentos framework carregam e passam na consistência verificada |
| --check-one vendor/ODM | 0 | Documentos device carregam e passam na consistência verificada |
| --check-compat sem kernel | 65 | INCOMPATIBLE |
| --check-compat com kernel real | 65 | INCOMPATIBLE |
| Manifest framework base × matriz vendor literal | 1 | Incompatível nesse par, sem composição de fragments |
| Manifest vendor × matriz framework base literal | 1 | Incompatível nesse par |

O comando completo registra explicitamente:

1. `Sepolicy version 30.0 doesn't satisify the requirements.` Isso se refere à
   interface SELinux declarada no manifest, não à versão binária de policy 30.
2. `Cannot find framework matrix at FCM version 4.` É o check de depreciação do
   CLI; permanece diferente da composição que aceita matrizes sem nível.
3. 68 instâncias/versões de HAL declaradas pelo device não aparecem na matriz
   framework, incluindo interfaces Samsung e Oplus. São 68 entradas de metadados,
   **não 68 bugs de runtime comprovados**. O runner preserva a lista completa.

`--check-compat` agrega compatibilidade, depreciação e checks adicionais de HAL.
Não existe flag independente de depreciação nesse CLI. Os resultados acima não
inventam uma execução separada que a ferramenta não oferece.

O log confirma a leitura do kernel 4.19.325 e do IKCONFIG fornecido, e a coleta
do fragment de `/apex/com.android.virt/etc/vintf/virtualizationservice.xml`.
O parser avisa que o device e esse kernel não declaram nível FCM de kernel.
Não foi preenchido um nível artificial para eliminar o aviso. A falha anterior
de sepolicy pode impedir que outras verificações sejam alcançadas; o resultado
não aprova os requisitos de kernel.

## VNDK: limite do teste de par literal

O par manifest `/system` × matriz vendor falha em VNDK30 e anuncia a lista
suportada vazia. Esse par não inclui o fragment de `/system_ext`, que anuncia
VNDK34. Portanto ele não prova que o framework composto suporta uma lista vazia.
A divergência de declarações 30 versus 34 permanece documentada, mas o comando
completo apresentou primeiro a incompatibilidade de sepolicy; não se atribui ao
teste completo uma mensagem VNDK que ele não emitiu.

## Próximo trabalho e bloqueio

Não corrigir isso apenas alterando os números do manifest, removendo HALs ou
desligando verificações. É necessário alinhar a interface de política realmente
fornecida, os requisitos e providers de HAL da Samsung e os componentes do
framework. O libvintf OEM do doador ainda pode ter comportamento diferente da
referência host; não foi executado no aparelho para comprovar isso.

O modelo host considera todos os 46 módulos APEX de fábrica ativos, sem validar
a ativação real, as atualizações em /data, os namespaces ou o boot. Vendor SKU
não foi coletado e permaneceu uma hipótese vazia explícita. Esses limites estão
no gate e no manifesto de entrada. O código de auditoria continua mantendo
`release_ready=false` e `boot_confirmed=false`.

Evidência exata baixada do artifact: `ci-run-41319419220/`, com `gate.json`,
`results.json`, comandos, stdout/stderr, build.prop oficial e lock da ferramenta.
Foram validados os CRCs do artifact e o SHA do bundle de entrada. Dezesseis
testes offline do runner também passaram, incluindo sinais/crashes, uso inválido,
distinção entre incompatibilidade e erro de metadados, versão e hashes.
