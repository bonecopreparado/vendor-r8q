# Revisao das referencias Lineage e do SELinux efetivo

Analise em 2026-11-16. As referencias estao fixadas por commit nos JSONs
adjacentes. A existencia do ramo lineage-24.0 foi confirmada; nao foi usada
como prova de certificacao, release oficial publicada ou boot deste port.

## Repositorios do ata-kaner

O mantenedor tem uma arvore do proprio r8q em lineage-24.0. A arvore comum
e o kernel nesse ramo apontam exatamente para os commits Lineage ja
revisados. Comparacao de todos os blobs da arvore r8q encontrou apenas
configs/display/displayconfig.xml diferente: curva de brilho/HBM importada
do r8s. Isso nao estabelece uma correcao de boot e nao foi aplicado ao port.
O vendor r8q tambem coincide. O HEAD do vendor comum remove o prebuilt
argosd para compila-lo de fonte; nao justifica remover esse servico da ROM.

## SELinux: opcao de compilacao, parametro e estado sao coisas diferentes

O IKCONFIG extraido do Image realmente entregue na P1r4 confirma:

```text
CONFIG_SECURITY_SELINUX=y
CONFIG_SECURITY_SELINUX_DEVELOP=y
# CONFIG_SECURITY_SELINUX_PERMISSIVE is not set
# CONFIG_SECURITY_SELINUX_BOOTPARAM is not set
```

O kernel permite alternar enforcing/permissive, mas nao esta compilado para
forcar permissive. SECURITY_SELINUX_BOOTPARAM controla selinux=0, nao a
interpretacao de androidboot.selinux. No fonte fixado, hooks.c interpreta
enforcing=; selinuxfs.c so ignora pedidos de enforcing quando a opcao
customizada SECURITY_SELINUX_PERMISSIVE esta habilitada.

As linhas de boot retidas contem androidboot.selinux=permissive. Contudo,
os registros Android anteriores a R2 incluem hwservicemanager recusando
IQSEECom com permissive=0 e contexto default_android_hwservice. Isso
confirma verificacoes enforcing nesse ponto da inicializacao. Um getenforce
executado apos retornar ao recovery descreve o recovery, nao esse boot.

O init de referencia Android 17 usa ALLOW_PERMISSIVE_SELINUX=0 por padrao;
o build debuggable muda para 1. SelinuxSetEnforcement pode mudar o estado
apos carregar a politica. Isso explica por que o parametro nao garante o
estado final, mas nao prova a implementacao exata do init binario Xiaomi.
Nao foi feita alteracao para forcar permissive nem declarado que isso
resolveria o boot. R2 ja corrige os rotulos de Vendor comprovadamente
errados; seu resultado em hardware ainda precisa de novos logs.

## Correcao experimental de interfaces de memoria

O Image atual desabilita MEMCG, PSI e o controlador freezer v1, enquanto
o Vendor monta e utiliza freezer v1. A referencia do mantenedor habilita
esses tres recursos. A compilacao experimental adiciona esses controladores
e suas dependencias, mantendo KernelSU, todas as opcoes SUSFS e NFLOG.
Heimdall permanece desativado para evitar mudar implicitamente a semantica
de contabilizacao/reclaim. Nenhuma mudanca de fstab, criptografia, FTRACE,
ashmem, firmware ou politica SELinux foi misturada.

Os guardas agora tambem impedem mudar os controles SELinux acidentalmente,
inclusive habilitar a opcao force-permissive que nao existia na configuracao
antiga. A configuracao apos olddefconfig, simbolos definidos e o IKCONFIG
do Image vinculado sao verificados separadamente. O workflow produz apenas
artefatos de revisao, explicitamente nao instalaveis.

MEMCG/PSI ausentes sao lacunas reais de integracao. Sem o tombstone completo
nao e possivel atribuir a eles o SIGSEGV camopt_killer do lmkd. Tampouco o
sucesso da compilacao prova boot. Nao foi pedido Format Data nem alterado
o aparelho durante esta analise.

## Primeira compilacao: defeito latente de sincronizacao MEMCG

O run 43968203666 passou os guardas e olddefconfig, mas parou em sete usos
de shrinker_rwsem sem declaracao em mm/vmscan.c. O caminho global havia
mudado para locks de lista/delecao por shrinker, enquanto o caminho MEMCG
ainda exigia o rwsem antigo. A reparacao separada memory-shrinker.patch
restaura o rwsem apenas para o IDR/lifetime de MEMCG e serializa tambem
idr_replace na publicacao do shrinker. Simplesmente declarar o objeto sem
proteger esse escritor deixaria uma corrida.

Os locks e o algoritmo do caminho global sao preservados. Os hashes
antes/depois estao fixados, incluindo o Git blob canonico do arquivo. Um
teste C executa as funcoes reais extraidas do fonte reparado com stubs que
verificam protecao do IDR, ordem sleeping-lock/spinlock, registro e limpeza
de erro. Isso nao substitui lockdep nem prova concorrencia no kernel. A
segunda compilacao usa a identificacao r8q-memcg-staging2 e mantem todos
os recursos solicitados; nao desabilita MEMCG_KMEM para ocultar a falha.
