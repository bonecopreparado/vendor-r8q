# P1r3: candidato completo com kernel NFLOG/SUSFS e correções de boot

O kernel de referência foi compilado e seu Image foi conferido independentemente
no run [43655210425](https://github.com/bonecopreparado/vendor-r8q/actions/runs/43655210425),
commit de receita `9d69eb86e7e566c2f139330f985099b250ca77d1`.
O Image dessa execução tem SHA256
`1a256615f2400b24b08d3075ff05fa0b262d52b938e183bb9e681352ce9fe987`.
A configuração embutida corresponde à usada pelo compilador, SHA256
`cc45d3126cefe52746a2e8c3b246810d97a47b12856c1a73b48dc5f6a7007a2e`.
NFLOG e as dez opções SUSFS ativadas na base foram preservados. Isso comprova
compilação/link/configuração, não boot ou funcionamento no aparelho.

A adaptação mantém os cinco reparos de compatibilidade anteriores e adiciona
23 arquivos de source/headers com identidades exatas. O SUSFS 2.2 agora tem
consumidores reais de lookup/readdir/map/AVC e worker de caminhos, sem os hooks
manuais conflitantes da primeira referência. Foram corrigidos a posse de IDs
de montagem, a chamada obsoleta do escalonador, o aviso do driver MMC e a regra
que embutia um stock-defconfig antigo no Image. A verificação do binário real
detectou esse último problema depois de uma compilação aparentemente verde.

## Imagens e pacote

P1r3 exige um kernel realmente linkado, relatório confiável, helper diagnóstico
compilado e validado, ferramentas VINTF e modo de symlinks compatível com o kernel
antigo. Não existe fallback silencioso para o kernel antigo sem NFLOG.

O preparo copia os planos existentes e integra o patch group32 da biblioteca
SurfaceFlinger, a importação canônica do ueventd e os três arquivos de diagnóstico
V6. Os demais ajustes de política, mapeamentos e hardware são preservados. A
reconstrução verifica os bytes e metadados dos sistemas de arquivos, depois os
hashes das partições no super com um leitor independente.

O novo boot é regenerado a partir do boot original exato e do Image conferido.
Ramdisk, DTB, DTBO, cmdline e endereços de carga Android são preservados. O header
do Image não é editado para esconder seu text_offset zero; o suporte do bootloader
e a compatibilidade do DTB antigo continuam pendentes de teste físico.

Antes de aceitar o boot novo, o empacotador repete a geração e compara o resultado
ao relatório, em vez de aceitar apenas um marcador JSON. O ZIP contém os payloads
completos, as licenças do helper nativo e o coletor opcional V6 dentro de extras/.
Não é necessário gerar instalador nem aplicar ENABLE separado. V6 usa uma nova
pasta de captura e preserva V3/V4/V5. Salva um snapshot tardio de crashes para não
depender apenas das primeiras mil linhas do boot.

## Workflow

O workflow completo tem dois jobs: compila o kernel e, após seu sucesso, baixa e
confere o artefato da própria execução antes de reconstruir as imagens. A origem,
commit, job, digest do ZIP e hashes de Image/vmlinux/System.map são conferidos.
Não depende de IDs fixos de artefatos antigos com retenção de duas semanas.

O ZIP só é publicado após verificação de payloads, CRCs, gzip, leitor ZIP64 nativo
e readback ARM64 em emulação. A publicação mantém SHA256 e attestation do ZIP
inteiro. Verificações de bateria, vbmeta, partições montadas, capacidade e prefixo
de super permanecem no instalador.

## Limites

A reconstrução completa desta revisão ainda precisa terminar no workflow. Não
há afirmação de boot testado, hardware funcional ou ausência de todos os bugs.
As divergências conhecidas de kernel/FCM/HAL do VINTF continuam registradas; o
teste com kernel agora usa a configuração extraída do novo Image, não a antiga.
O teste físico seguinte deve registrar o novo resultado e os logs V6.
