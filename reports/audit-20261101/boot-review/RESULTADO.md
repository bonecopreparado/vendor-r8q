# Revisão de compatibilidade antes de novos testes

As imagens P0 permanecem inalteradas e sem boot confirmado. O resultado do
instalador não valida esta compatibilidade. Nenhuma correção de SELinux deste
relatório foi aplicada ao filesystem da ROM.

## SELinux: problema estrutural reproduzido

Uma compilação nova dos CIL originais, com o compilador moderno já verificado e
as flags de compilação do init (`-m -M true -G -c 30 -N`), terminou com código
255: `Re-declaration of typealias sysfs_battery_supply`, referenciando
`vendor_vendor_sepolicy.cil:874`. A candidata isolada de três mudanças compilou
com código 0, gerou novamente o SHA256
`70278111389ef8affecddf0eee346f4d3cba4b72fe7bc907e512f7c610d769ad` e preservou
os seis policycaps, inclusive `functionfs_seclabel`.

Também foram lidos os três pares de arquivos `.sha256` do framework e da política
precompilada em ODM. Plat, system_ext e product divergem nos três casos. Pelo
fluxo normal do init AOSP, essa política precompilada não seria selecionada e o
init tentaria compilar os CIL que apresentam o conflito. Não foi executado o init
Xiaomi para demonstrar que ele conserva exatamente esse fluxo. É uma pendência
concreta que bloqueia recomendar a P0 como pronta; não deve ser disfarçada com
hashes falsificados ou apenas com permissive.

Evidências: `../round2/contexts/fresh-compile/result.json`, os respectivos logs e
`../round2/contexts/precompiled-input-hashes.json`. A candidata precisa ser
integrada em uma nova imagem coerente e validada separadamente antes de qualquer
afirmação sobre boot. Os 335 registros neverallow são outra análise; não substituem
este erro de compilação e não representam automaticamente 335 falhas em execução.

O checker de contextos foi executado na CI 41319419220 com a libsepol moderna
do mesmo pin, controles positivos e negativo e os seis policycaps preservados.
Dos 2.888 contextos, 2.879 passaram e nove falharam. Além do domínio ausente
`logdumpd`, sete seletores de apps Samsung e um seletor Qualcomm pedem contextos
de processo inválidos na candidata. Os oito achados novos não tinham sido
previstos pela inspeção estática inicial. Não foram corrigidos nem ocultados:
passam a compor o primeiro baseline medido, vinculado à CI e aos hashes exatos.
CI falha em nomes, estados ou referências inválidas novos. O serviço logdumpd
está desabilitado e só inicia com `ro.logdumpd.enabled=1`; os seletores de apps
também não provam por si só que os respectivos pacotes existem ou são iniciados.
Passar essa regressão não torna a política original da P0 válida e não equivale
a testar permissões no kernel. Ver `../../../patches/0003-seapp-context-review/README.md`.

## NFC: dependência nativa ausente

O grafo estático cobre 18 raízes HAL/módulos e 291 ELFs, sem erros de leitura.
Encontrou uma dependência sem provedor: o serviço
`/odm/bin/hw/vendor.oplus.hardware.nfcExtns-service` precisa de
`libpnscr2_aidl.so`. A busca não encontrou provedor de 32 ou 64 bits nas bibliotecas
inventariadas. Quatro símbolos `oplusEngineer_pnscr_*` também ficaram sem definição
na closure candidata. O init ODM inicia esse serviço como `class hal` e o VINTF
ODM anuncia `vendor.oplus.hardware.nfcExtns/INfcExtns/default`.

Isso explica uma falha desse serviço na configuração inventariada, consistente
com o NFC já listado como bug. Não comprova que todo o caminho NFC Samsung esteja
quebrado pelo mesmo motivo. Framework APEX adicionais e namespaces reais não
foram resolvidos exaustivamente. A correção exige escolher um conjunto NFC/HAL/
configuração coerente com o hardware Samsung e remover dependências Oplus somente
após avaliar os clientes; copiar uma biblioteca de outra ROM não é uma correção
validada.

O resumo e o SHA256 do grafo completo estão em `findings.json`.

## BPF Xiaomi: novo ponto de falha a investigar

`system_ext/etc/init/hyper_bpfloader.rc:18` executa `hyper_bpfloader` de forma
síncrona. O serviço tem `reboot_on_failure reboot,hyper-bpfloader-failed` na linha
91. Seu binário existe e usa a propriedade `bpf.hyperos_progs_loaded`; ela é
distinta da propriedade AOSP `bpf.progs_loaded`, que participa da inicialização
do netd.

Foram extraídos e inspecionados 18 objetos BPF das imagens system/system_ext.
Vários contêm programas `tracepoint/*` e `kprobe/*`. O kernel R8Q da P0 tem BPF
ativado, mas `CONFIG_FTRACE` desativado; o kernel doador tem FTRACE ativado.
O loader contém filtros de versão de kernel, lista de objetos permitidos e
tratamento de programas opcionais. Ainda falta comprovar quais programas serão
selecionados no R8Q e quais erros são fatais. Portanto, a presença desses objetos
e a diferença de configuração são risco real a investigar, não uma prova de
que esse reboot ocorrerá. Não foram removidas as verificações nem falsificadas
propriedades de sucesso.

Evidência reproduzível da leitura: `../round2/init/audit_bpf_objects.py` e
`../round2/init/bpf-objects/metadata.json`. O ELF possui `.gnu_debugdata`, que pode
ajudar a seguir as funções `checkElfObjectInWhiteList`, `loadAllElfObjects` e
`loadBpfObject` numa próxima investigação sem executar código Android.

## Overlays: valores do doador que precisam de adaptação

Entre 84 RROs inventariados, `AospFrameworkResOverlay.apk` contém prioridade
estática 1000, pico padrão de 90 Hz e brilho inteiro 8–4095/default 615.
`FrameworksResCommon_Sys.apk`, prioridade 100, também define pico padrão de
240 Hz. `DevicesAndroidOverlay.apk`, prioridade 1000, contém o recorte
`M -903,0 H -1080 V 90 H -903 V 0 Z@right`.

São valores concretos inadequados para aceitar sem revisão num S20 FE de 120 Hz,
mas o valor final depende da ativação/precedência dos overlays, do idmap, das
configurações de recurso e do código de exibição Xiaomi. Não foi afirmado que a
tela já ficou efetivamente limitada a 90 Hz. A escala de brilho também precisa
considerar o script Samsung existente e os valores reais do painel. Não foi
removido nenhum APK inteiro para tentar corrigir apenas um recurso.

## O que continua sem prova

Não houve execução de HALs, linker Android, BPF verifier ou policy load no kernel.
O grafo não valida namespaces, versões de símbolos nem dependências abertas
dinamicamente por todos os serviços. SMS, VoLTE, Bluetooth, biometria e câmera
continuam sem teste funcional. A próxima imagem deve vincular alterações
revisadas a novos hashes de partição; reutilizar os hashes P0 significa reutilizar
os mesmos bytes e as mesmas pendências.
