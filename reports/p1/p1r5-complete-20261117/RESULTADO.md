# P1r5: ROM completa para um unico flash no recovery

Objetivo: instalar a ROM completa sem exigir P1r4 anterior, R2, R3 ou ENABLE
separados. Boot/hardware permanecem sem confirmacao. A preparacao de bootloader,
recovery e vbmeta desabilitado continua sendo um requisito separado.

## Conteudo integrado

- O kernel compilado e verificado do commit 3827a7dcee14c621ed4b230c36609502509be5ea
  habilita MEMCG, PSI e freezer v1, incluindo a reparacao de sincronizacao do
  IDR de shrinkers. KernelSU, todas as opcoes SUSFS e NFLOG sao preservados.
- O plano Vendor inclui os oito arquivos substituidos pela R2, derivados de
  dois programas ELF Samsung assinados e fixados por SHA256. Os doze arquivos
  relacionados, incluindo os quatro segmentos de codigo imutaveis, precisam
  corresponder a R2 na imagem Vendor realmente reconstruida.
- Os onze rotulos de raiz/contextos/politica sao corrigidos offline e a
  conferencia de firmware ocorre novamente na mesma imagem apos a correcao.
- O hash dessa Vendor e vinculado a leitura LP independente e ao hash do
  Super que entra no pacote. Nao ha reparacao posterior que invalide os hashes
  de payload/readback.
- Sao mantidas as correcoes anteriores de scheduler, display, ueventd, modo
  EROFS para kernel antigo, mapeamentos opcionais e diagnostico V6.

Os dois ELF sao programas de firmware stock, com certificados publicos
embutidos. Nao foram incluidos EFS, calibracao, logs ou dados pessoais.

## Instalador e verificacao

O guard de APNHLOS confere os seis arquivos do perfil stock em montagem
temporaria somente leitura, antes de qualquer gravacao. Firmware diferente
aborta; nao se elimina autenticacao SCM nem se escreve APNHLOS/modem.

O helper nativo agora oferece flush/fdatasync + BLKFLSBUF e leituras alinhadas
O_DIRECT com offsets de 64 bits. A capacidade de flush/leitura e exercitada em
Super, DTBO e boot ja desmontados antes de iniciar o flash. Depois de cada
gravacao, os hashes sao calculados por leitura direta, incluindo a preservacao
dos primeiros 4096 bytes de Super. O modo de fixture exige macro de compilacao
e nao pode ser habilitado por ambiente no executavel de producao.

Guardas existentes de bateria, modelo, capacidades, AVB flags=3, montagens,
armazenamento do ZIP, SHA256 e CRC continuam ativos. Nao ha Format Data nem
mudancas em recovery, bootloader, vbmeta, EFS ou Persist. Vindo da stock, a
compatibilidade dos dados/criptografia nao e resolvida automaticamente.

## Validacao e limites

Localmente, 425 testes passaram, com 17 skips por ferramentas indisponiveis.
Novos testes executam as leituras nativas em arquivos esparsos acima de 4 e
8 GiB, rejeitam modo de teste por ambiente, verificam o guard stock real e
impedem aceitar evidencias de Vendor/Super diferentes. A CI instala as
ferramentas e executa tambem os fixtures ext4, reconstruindo e lendo as imagens
reais e o ZIP completo em host e AArch64 emulado.

O workflow usa o build de kernel bem sucedido por commit e artefatos atuais
verificados, sem ID de artefato expiravel fixo. O ZIP completo sera publicado
via GoFile, com checksum e atestacao no GitHub Release; o coletor sera tambem
um download pequeno separado. O complemento R3 existente continua destinado
somente a instalacoes P1r4 anteriores.

Compilacao, hashes e testes nao provam boot. Permanecem os achados conhecidos
de VINTF/HAL legado e a causa ainda nao confirmada do SIGSEGV camopt do LMKD.
