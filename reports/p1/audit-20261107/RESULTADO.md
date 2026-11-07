# Revisão de boot e preparação dos testes — 7 de novembro de 2026

A P1r2 foi instalada pelos testers, mas o usuário relata que o Android não inicia.
Os últimos recovery.log, dmesg e logcat recebidos registram a sessão de recovery
antes da tentativa de boot. Não contêm a causa persistida do reinício. Nenhuma
correção causal de boot é anunciada nesta revisão.

## BPF: a falta de FTRACE não demonstra reinício obrigatório

Foram lidos o hyper_bpfloader real (SHA256
a823d9672bb24a45bfe298dce0249e72c197e0588fb9bda0d1fe997071cc05c7)
e 18 objetos BPF das imagens usadas no port. Todos os 18 não têm seção ELF
critical; isso inclui os oito objetos Xiaomi selecionados no boot.

loadProg inicializa a criticidade em falso em 0x2e230 e somente a ativa após
readSectionByName("critical") retornar sucesso (0x2e328–0x2e354). O fallback
loadMiuiProg segue a mesma regra (0x26ba8; 0x26cb8–0x26ce4).
loadAllElfObjects só acumula o erro do objeto quando essa marca é verdadeira
(0x227fc–0x2280c). Erros comuns de um objeto opcional, sozinhos, não provam a
saída fatal do carregador.

O caminho de boot varre /system/etc/bpf/miui/ e /vendor/etc/bpf/, sem recursão,
com filtro .o e lista de boot. MiuiMmTrace.o e MiuiMmStat.o em system_ext não
são varridos por esse caminho. Pasta vendor BPF ausente é aceita nesse fluxo.
Continuam possíveis falhas na criação dos diretórios de bpffs, publicação da
propriedade, aborts/sinais e erros de outro loader, como netbpfload do APEX.
O rc mantém reboot_on_failure; não foi removido para mascarar uma falha.

## Dependências dos serviços iniciais

As árvores transitivas e os símbolos dinâmicos fortes, incluindo versões,
foram examinados para init (38 nós), vold (50), apexd (33), servicemanager (21),
surfaceflinger (301), hyper_bpfloader (9) e hwservicemanager (22).
Nenhuma árvore examinada ficou com DT_NEEDED ou símbolo forte sem provedor
compatível no modelo estático usado.

Os APEX de fábrica runtime, i18n e tethering foram considerados. Uma segunda
árvore usa os provedores bootstrap dos quatro executáveis que o requerem.
Namespaces efetivos, dlopen, ativação de APEX e execução no telefone permanecem
limites: presença e símbolos não comprovam visibilidade durante o boot.

## Falhas distintas para procurar no próximo teste

- Montagem inicial/SELinux: mount failure, policy load/compile failure, panic.
- APEX: bootstrap-apexd-failed e apexd-failed.
- Armazenamento/criptografia: vold-failed e erro imediatamente anterior.
- Autotestes: boringssl-self-check-failed.
- BPF AOSP/APEX: bpfloader-failed ou netbpfload-missing.
- BPF Xiaomi: hyper-bpfloader-failed.

O kernel extraído tem EROFS, DM_USER, DM_DEFAULT_KEY, DM_BOW e PSTORE_RAM.
Os dois autotestes BoringSSL e app_process 32/64 bits existem. Essas ausências
não foram encontradas. A compatibilidade VINTF continua aberta; o host não
validou o conjunto como compatível.

## Correções de diagnóstico publicadas

O coletor v3 guarda o fim de pstore e last_kmsg quando excedem os limites, em
vez de descartar a parte final que pode conter o crash. Também registra status
de comando, timeout, truncamento e se pstore está montado. Não monta, formata,
limpa logs nem grava partições da ROM.

Oito testes passaram em mksh na CI:
https://github.com/bonecopreparado/vendor-r8q/actions/runs/42377712628

Coletor pronto:
https://github.com/bonecopreparado/vendor-r8q/releases/tag/r8q-bootlog-collector-3-1

ZIP: 5459 bytes.
SHA256: 72c8da73da080c24324eb755076ad2710ff4634fdb36650753893a3e03a034af

## Estado das melhorias do instalador

No workspace foram preparadas invalidação verificada dos buffers dos alvos antes
da releitura e decodificação estrita de pontos de montagem escapados. O relatório
local registra 56 cenários em mksh, sem gravações físicas ou teste de boot.
Essas alterações do instalador NÃO estão incluídas no ZIP P1r2 já publicado nem
neste commit do coletor. O ambiente ficou indisponível antes da publicação dessas
duas alterações; não há uma nova ROM anunciada como resultado desta revisão.

Os logs brutos de aparelhos não foram publicados.
