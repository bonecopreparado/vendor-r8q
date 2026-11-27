# Onde o boot parou

A **P1r5 KEYMASTER-TEE** é a base experimental. A tentativa de instalação mais recente, em 26/11/2026, foi bloqueada durante o preflight do firmware. Os registros de boot anteriores ainda não chegaram a um início completo do HyperOS.

## Atualização de 26/11/2026 · perfil IPA não confere

A foto do recovery mostra duas tentativas. Na primeira, a bateria estava em 24% e o estado era **Discharging**, então a guarda interrompeu o processo. Na segunda, continuava em 24%, mas aparecia **Charging**. Essa vez o preflight de bateria passou. A checagem de AVB encontrou flags 3 e o leitor ZIP64 também passou. O instalador exibiu o diagnóstico aritmético de 32 bits e depois interrompeu em:

`ERROR: Stock firmware differs: ipa_fws.b01 (...). Nothing was written.`

A P1r5 exige o SHA-256 `8bc6bf3243e4a76cd18e5128cccf1cf1b7c6653ee228116d16b3b8e086cf8231` para `ipa_fws.b01`, obtido de um perfil Samsung conferido com a captura `G781BXXSIHYJ2`. A identificação no topo da foto parece ser `G780GXXSHEYJ1`. A release declara ambos os modelos, mas a foto mostra que o APNHLOS desse G780G não passa pelo perfil exato atual.

**Resultado da tentativa:** o script confere os seis arquivos IPA por montagem APNHLOS somente leitura antes de gravar qualquer imagem. A linha de erro afirma que nada foi escrito. O Super, o Boot e o DTBO do telefone permaneceram como estavam. Não contorne a checagem e não grave firmware IPA ou APNHLOS manualmente.

**Pendência de compatibilidade:** verificar os seis hashes completos do APNHLOS G780GXXSHEYJ1 e conferir qual conjunto autenticado de firmware deve corresponder à Vendor dessa variante. A imagem só mostra o hash que divergiu, e o valor ficou ilegível na foto. O `recovery.log` da segunda tentativa pode confirmar o hash integral e o modelo. Até então, não tratar a P1r5 como pré-validada para esse perfil G780G.

Para preservar o registro sem reiniciar o recovery, no CMD do Windows use `adb pull /tmp/recovery.log recovery-p1r5-26nov.log`. Confira o modelo e a versão de firmware indicados no começo do log.
## O último teste no aparelho

Na tentativa `6HJfVN`, o recovery enxergava duas árvores de arquivos diferentes. A primeira leitura de `/vendor` encontrou a biblioteca do próprio TWRP. Ao identificar `dm-1` pelo nome lógico `vendor` e montar a partição em modo de leitura, **os quatro SHA-256 conferiram** com os da release. Isso confirma qual conjunto Keymaster estava instalado. [Identidades dos quatro arquivos](https://github.com/bonecopreparado/vendor-r8q/releases/download/p1r5-keymaster-tee-experimental-5-1/keymaster-tee.json)

| Tempo desde o início do kernel | O que apareceu no último boot Android do TAR |
| --- | --- |
| 11,78 s | O init informou `keymaster=running` depois de iniciar a classe de serviços. Ainda faltava confirmar o registro de `IKeymasterDevice/default`. |
| 11,92 s | A `keystore2` tentou obter o TEE pelo adaptador legado, recebeu `HARDWARE_TYPE_UNAVAILABLE` e encerrou com `SIGABRT`. |
| 12,07 s | O `vdc` iniciou `cryptfs encryptFstab` e encontrou o serviço `vold` imediatamente. |
| 93,15 s | A última amostra ainda mostrava o `vdc` esperando. Faltava o marcador de saída de `mount_all --late`. |

A fonte dessas observações é o `last_kmsg` do TAR enviado pelo tester. O mesmo arquivo conserva vários boots. Os horários acima pertencem à última sequência iniciada por `Booting Linux`. O `recovery.log` dessa coleta registra o sideload do coletor de 6.562 bytes.

## Bugs, hipóteses e critérios para encerrar cada item

| Prioridade | Situação | O que falta observar |
| --- | --- | --- |
| **1 · bloqueia o boot** | A `keystore2` encerra porque o TEE obrigatório fica indisponível. A Vendor traz o serviço Samsung e o manifesto declara o Keymaster 4.0 `default`. | No TEE-HAL-LOG, procurar a primeira mensagem do linker, do serviço Samsung ou do `hwservicemanager`. Confirmar registro e acesso pelo cliente. |
| **2 · montagem de Data** | O F2FS chegou a montar o dispositivo em leitura. Depois, `encryptFstab` ficou pendente durante a tentativa observada. | Capturar o retorno da operação, o fim de `mount_all` e a entrada em `post-fs-data`. Formatar Data novamente não é necessário para este teste. |
| **3 · compatibilidade de bibliotecas** | O `libcrypto.so` principal do doador carece de `sk_delete`. O VNDK 30 embarcado exporta esse símbolo. A KEYMASTER-TEE também leva o provedor legado `libcrypto-v33.so`. | Identificar a resolução real do linker no boot se houver erro de biblioteca ou símbolo. A análise estática sozinha não atribui a causa. |
| **4 · compatibilidade do sistema** | Há achados históricos em VINTF, BPF, políticas e HALs. Na P1, a política compilou em host após correções; os relatórios registram separadamente os resultados de compatibilidade. | Revalidar com a composição exata em teste e o primeiro erro de runtime. A falha do TEE é a primeira fatalidade observada nesta tentativa. |
| **5 · uso cotidiano** | Tela após a logo, SurfaceFlinger, rádio, Wi-Fi, áudio, câmeras, sensores, NFC e desbloqueio de dados aguardam validação no Android do port. | Primeiro atingir `sys.boot_completed=1`. Depois registrar os resultados por modelo, firmware, build e função. |

## Sintomas que já confundiram os testes

| Sintoma | Como interpretar |
| --- | --- |
| Recovery mostra `Invalid zip file` antes de iniciar o instalador | Em um teste antigo foi selecionado o ZIP da auditoria. Confira o nome, tamanho e SHA-256 da ROM. Cartões FAT32 não comportam o arquivo completo da P1r5. |
| ADB só reconhece o aparelho no TWRP | Foi o comportamento relatado na logo. O coletor lê o kernel anterior ao voltar ao recovery. Um logcat obtido nesse momento pode descrever o próprio TWRP. |
| V6 devolve TAR `PARTIAL`, ou falta `/metadata/r8q-bootdiag-v6` | Nessa etapa precoce pode faltar a captura persistida do Android. Verifique os arquivos de status do coletor e o `last_kmsg` antes de tentar outro flash. |
| Faltam arquivos em `/vendor` no TWRP | O recovery pode expor sua própria árvore em RAM. Confira a origem em `/proc/mounts` e o nome lógico em sysfs antes de comparar arquivos com o manifesto da ROM. O número de `dm-*` pode mudar. |
| Format Data falha com o dispositivo ocupado | Em uma sessão anterior o mapeamento `userdata` ainda mantinha a partição em uso. É um problema de estado do recovery. O teste atual de registro do TEE dispensa a formatação. |

## Mudanças já incorporadas

- **Imagem e instalador.** A P1r2 corrigiu o empacotamento ZIP64. A revisão EROFS tratou o limite de links simbólicos que afetava a leitura de `libc`. [Evidência EROFS](https://github.com/bonecopreparado/vendor-r8q/tree/f1351e4a92f1db4e1dfcf167acb0e8f443547350/reports/p1/erofs-boot-failure-20261107)
- **Kernel.** A linha P1r3/P1r4 reuniu NFLOG, KernelSU/SUSFS e a correção do índice de CPU no scheduler. A P1r5 incorporou MEMCG, PSI e freezer v1. [Scheduler](https://github.com/bonecopreparado/vendor-r8q/tree/f1351e4a92f1db4e1dfcf167acb0e8f443547350/reports/p1/p1r4-scheduler-20261115) · [Composição P1r5](https://github.com/bonecopreparado/vendor-r8q/tree/f1351e4a92f1db4e1dfcf167acb0e8f443547350/reports/p1/p1r5-complete-20261117)
- **Vendor.** A sequência IPA/R2 alinhou o firmware IPA/IPA UC ao perfil Samsung avaliado e corrigiu os rótulos da raiz da Vendor e dos arquivos de contexto. A P1r5 completa incorpora o R2. [Relatório técnico R2](https://github.com/bonecopreparado/vendor-r8q/tree/f1351e4a92f1db4e1dfcf167acb0e8f443547350/reports/p1/security-r2-20261116)
- **Keymaster.** A KEYMASTER-TEE integrou o serviço Samsung e o backend da referência oficial LineageOS para r8q. Os testes do pacote e os hashes no aparelho passaram. O registro do serviço em runtime continua em investigação. [Código da integração](https://github.com/bonecopreparado/vendor-r8q/blob/f1351e4a92f1db4e1dfcf167acb0e8f443547350/tools/vendor_security/keymaster_tee.py)

O próximo marco é receber um TAR do TEE-HAL-LOG e confrontar as linhas `R8QTEE` com `R8QKEYSTORE` no mesmo boot. [Roteiro do teste](docs/RETOMADA.md) · [Estado histórico na época da P1r2](https://github.com/bonecopreparado/vendor-r8q/blob/17669efee036c538e10ed0d6f3f5ee524c1b3fc1/STATUS.md)
