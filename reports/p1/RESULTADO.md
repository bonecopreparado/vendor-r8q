# P1: alterações aplicadas às imagens, boot ainda não testado

A P1 é uma nova composição real de filesystem. Foram aplicadas 13 operações em
quatro partições; product, boot e dtbo permanecem com os bytes da composição P0.
Nenhum aparelho foi gravado e nenhuma imagem original foi modificada.

## Correções integradas

- Duas declarações CIL conflitantes removidas em favor dos aliases Samsung já
  existentes, e declaração do atributo de mapping já referenciado adicionada.
- Regra de telefonia inválida removida: permanece o domínio Qualcomm existente,
  sem transformar um tipo de serviço em domínio de aplicativo.
- Dezoito seletores Samsung inativos removidos após inventário de 401 APKs
  assinados de fábrica, incluindo os APEX. Três duplicações adicionais foram
  eliminadas; a regra de dados SystemHelper do framework foi preservada.
- Serviço NFC Samsung consolidado com seus quatro bindings HIDL. A dependência
  ausente da extensão Oplus permanece pendente; NFC funcional não foi comprovado.
- Serviço Samsung logdumpd desabilitado e inválido, que gravava diretamente numa
  partição de logs, e seu único trigger foram removidos. Logcat normal permanece.
- Cache de política pré-compilada ColorOS e três hashes acompanhantes removidos
  de ODM: o init deve compilar os CIL correspondentes ao framework desta imagem.
- Declarações de suporte sepolicy30.0 e VNDK30 alinhadas aos mappings e providers
  efetivamente presentes, preservando VNDK34, versões vendor e todos os HALs.

## Evidência obtida

A política relida das imagens reais compila com os seis policycaps e reproduz
o SHA256 revisado `70278111389ef8affecddf0eee346f4d3cba4b72fe7bc907e512f7c610d769ad`.
O checker binário moderno validou **2.879 contextos, zero inválidos**, coletados
de 27 arquivos de contextos e 272 arquivos init reais. Os nove achados da P0
não foram apenas aceitos em uma baseline: suas referências foram corrigidas ou
removidas da candidata, com as justificativas acima.

As duas EROFS passaram em fsck e comparação completa: 5.026 entradas em system
e 3.669 em system_ext, incluindo dados, links, proprietários, modos, timestamps
e xattrs. Mantidos LZ4, blocos de 4 KiB e bits incompatíveis 1→1.

A vendor passou em uma segunda leitura por implementação ext4 independente:
todos os arquivos regulares foram hashados, sem omitir arquivos grandes, e os
links/diretórios conferidos. Somente quatro operações planejadas diferem.
O método final evita a otimização automática de diretórios que a primeira
tentativa de e2fsck fazia; metadados não planejados permanecem iguais.

O super tem 10.292.822.016 bytes e SHA256
`b05fa49fa8db78ace925669d738cd693bd27a696f9bbf1477945e3407e712659`.
O builder verificou todas as regiões e um parser LineageOS independente releu
as cinco partições com hashes correspondentes.

## Bloqueios remanescentes

O checkvintf oficial Android17 executou novamente sobre XMLs relidos das imagens
P1. O erro anterior de sepolicy desapareceu. Sem kernel, o fluxo chega ao erro
de depreciação pela ausência da matriz FCM4 (exit70). Com o kernel 4.19.325 real,
o check completo retorna INCOMPATIBLE (exit65): não há entrada de requisitos
para esse kernel; a matriz FCM4 e HALs fora das matrizes também permanecem.
Isso não é aprovação da compatibilidade nem uma contagem de bugs de runtime.

Uma matriz AOSP antiga foi usada apenas como diagnóstico. Ela exige áudio5.0,
enquanto o vendor declara6.0; copiar esse XML para calar o erro seria inadequado.
É necessário revisar o contrato real do kernel e o comportamento libvintf OEM.
Não foram alterados números de versão, removidos requisitos ou desativadas
checagens para produzir um resultado verde.

Os 338 registros neverallow da política isolada continuam pendentes. A compilação
com `-N` reproduz o caminho normal do init; não equivale a aprovar as assertions
ou os acessos no kernel. Boot, rádio, IMS, câmera, NFC, biometria, AOD, Bluetooth
e brilho ainda exigem validação. Overlays de 120Hz, charger e brilho opcionais
continuam separados, sem alterar APKs assinados ou aplicar mudanças não testadas.

## Arquivos e reprodução

- `composition.json`, `super-build.json`, `super-independent-readback.json`:
  identidades e layout da composição real.
- `policy-final/result.json`: CIL, policycaps e zero contextos inválidos.
- `vintf-actual/`: comandos e respostas do checkvintf sobre imagens reais.
- `vendor-fixes-only-tree-diff.json`: comparação independente completa.
- `system-rebuild.json`, `system_ext-rebuild.json`, `vendor-build.json`,
  `odm-build.json`: reconstrução, hashes e verificações dos filesystems.
- `patches/0004` a `0007`: evidências e planos de cada alteração.

As imagens grandes permanecem fora do Git. Este relatório e os scripts não são
um ZIP de instalação. A candidata continua sob revisão; não é uma ROM estável.
