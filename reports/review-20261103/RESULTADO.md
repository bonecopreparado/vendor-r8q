# Comparação do relatório externo com a P1r2

O PDF recebido em 03/11/2026 declara que examinou o commit `d182004`, com
instalador P0r8 e composição P0. A ROM enviada mais recentemente foi a P1r2,
commit `a036e2ed34f82eab1cf6bea34b8ae8c81b6a0fa8`. A main permaneceu na
base histórica, o que contribuiu para a divergência de versões. Esta revisão
corrige a documentação, sem alterar a ROM publicada nem seu hash.

## C1 — SELinux

O defeito da P0 é reproduzível. Na P1r2, a correção remove de
`system_ext_sepolicy.cil` as declarações conflitantes de
`sysfs_battery_supply` e `sysfs_memory`, preservando os aliases do vendor.
Não se trata de simplesmente apagar o alias Samsung em vendor_sepolicy.cil.

A verificação adicional encontrou os sete CIL pelos hashes registrados na
extração das imagens finais da P1r2 e os recompilou com sucesso. O resultado
foi exatamente:

`a09214b72ab473870e055aa7f2678e53fc1c5e657477c0b24974ef201f025eed`

As seis capabilities permaneceram habilitadas. Substituir somente o CIL
corrigido de system_ext pelo original reproduziu exit 255 e a mensagem
`Re-declaration of typealias sysfs_battery_supply`. Isso distingue o defeito
antigo da composição enviada atualmente.

Fontes: [aplicação dos patches](https://github.com/bonecopreparado/vendor-r8q/blob/a036e2ed34f82eab1cf6bea34b8ae8c81b6a0fa8/tools/prepare_p1_plans.py),
[verificação das imagens](https://github.com/bonecopreparado/vendor-r8q/blob/a036e2ed34f82eab1cf6bea34b8ae8c81b6a0fa8/tools/verify_p1_policy.py)
e [CI da P1r2](https://github.com/bonecopreparado/vendor-r8q/actions/runs/41570865668).

A P1r2 retira o cache precompiled_sepolicy antigo de ODM e seus hashes.
Compilar os CIL no boot é o caminho normal quando não existe cache compatível;
criar outro precompiled_sepolicy não é uma condição obrigatória para corrigir
essa redeclaração. Um cache novo exigiria verificação própria dos arquivos,
hashes, capabilities e versão. Compilação host continua sem provar a carga
efetiva da política pelo init/kernel do aparelho.

## C2 — BPF

São confirmados: `CONFIG_FTRACE` desabilitado, programas kprobe/tracepoint
entre os objetos do doador e
`reboot_on_failure reboot,hyper-bpfloader-failed` no serviço Xiaomi.

É uma hipótese de alta prioridade. Entretanto, a conclusão causal depende
de qual objeto o loader tenta carregar nesse kernel e de como a falha é
classificada. A inspeção do binário mostra filtros de lista/versão e tratamento
de programas opcionais; o fluxo de agregação não promove toda falha de objeto
a erro fatal. Há mensagens como `failed program is marked optional - continuing`
e `skipping program ... min_kver ... max_kver`.

Não há registro de boot comprovando `hyper-bpfloader-failed` neste aparelho.
A presença de programas incompatíveis na imagem, sozinha, não estabelece que
um deles é obrigatório nessa execução. Também não prova que todos serão
ignorados com sucesso.

Recompilar o kernel com FTRACE pode ser necessário para funcionalidades
específicas, mas envolve dependências e não garante compatibilidade com helpers,
BTF, símbolos ou programas Xiaomi. Retirar apenas reboot_on_failure mantém a
falha do programa; serve para diagnóstico e pode deixar serviços dependentes
sem funcionar. O loader de rede/AOSP deve ser tratado separadamente. Não foi
feita nenhuma dessas alterações nesta revisão.

## M1 — Cache e alcance do readback

O achado aponta uma limitação real. A releitura usa I/O buffered e pode
aproveitar o page cache do bloco. Porém, a escrita já usa
`dd conv=fsync` ou fallback para `sync`, com erro verificado, e termina antes
da releitura. Portanto, não é correto reduzi-la a uma escrita apenas em RAM.

No [Linux 4.19, blkdev_fsync](https://github.com/torvalds/linux/blob/v4.19/fs/block_dev.c#L618)
espera a escrita e solicita flush ao dispositivo. O fechamento do último
descritor pode invalidar páginas, mas outras referências do recovery ou
device-mapper impedem assumir que isso ocorreu.

Uma melhoria futura é invalidar explicitamente o cache do alvo com
`blockdev --flushbufs`, mantendo fsync/sync. Deve-se verificar suporte e
sucesso do ioctl após desmontar os alvos e antes da primeira escrita, para
não descobrir uma incompatibilidade depois de gravar super. Depois da escrita,
a invalidação precederia a verificação do prefixo e dos dados. O
[tratamento BLKFLSBUF no Linux 4.19](https://github.com/torvalds/linux/blob/v4.19/block/ioctl.c#L424)
não substitui a checagem de erro de fsync.

Limpar todos os caches com `echo 3 > drop_caches` é global e desnecessário para
essa finalidade. `iflag=direct` exige suporte no dd do recovery e alinhamento;
não deve ser acrescentado sem teste. Nenhuma dessas técnicas, isoladamente,
garante persistência física após perda de energia no controlador/UFS.

Essa limitação foi explicitada no README. Ela não explica um CRC do arquivo
de entrada que aborta antes da gravação, nem demonstra a causa do bootloop.

## Demais pontos

- M3 é histórico: as nove referências inválidas foram corrigidas na composição
  P1/P1r2; a última verificação contou 2.879 válidas e nenhuma inválida, incluindo
  referências de 272 arquivos init.
- C3 continua relevante: VINTF/kernel/HALs permanecem incompatíveis em verificações
  host. Não foram alterados números de versão para simular compatibilidade.
- M2 não está resolvido integralmente: consolidar os serviços NFC Samsung não
  fornece a biblioteca Oplus ausente nem comprova funcionamento do chip.
- M4/M5 continuam dependentes de adaptação e teste de hardware. Não há confirmação
  de brilho, câmera, NFC, modem ou health funcionando no HyperOS.
- M6/M7 descrevem workflows da base antiga. A distribuição P1r2 usa workflow
  próprio, release explícita, checksum, proveniência e testes adicionais. Os
  arquivos históricos não devem ser confundidos com esse fluxo.
- M8 exige respeitar as licenças próprias dos arquivos de firmware; a licença MIT
  da ferramenta não concede direitos sobre os blobs. Nenhuma redistribuição
  adicional de firmware foi feita por esta revisão de documentação.

O próximo dado decisivo continua sendo o registro do boot que falha. A revisão
do relatório não converte a P1r2 em uma ROM com boot ou hardware confirmados.
