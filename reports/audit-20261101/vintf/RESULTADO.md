# VINTF: refinamento da auditoria com fontes Android 17

Não houve mudança de XML, política, filesystem, instalador ou artefato publicado.
O comentário do tester sobre update-binary é da P0r3; nada nesta revisão explica
aquele erro de instalação melhor que o parâmetro dd já identificado.

## A ausência de compatibility_matrix.4.xml tem dois efeitos distintos

`CompatibilityMatrix::combine` não exige por si uma matriz numerada exatamente
como o target do dispositivo. Na implementação Android 17, matrizes sem nível
recebem o target do dispositivo e níveis superiores entram como opcionais. A
composição possui três matrizes sem nível, incluindo compatibility_matrix.device.xml.
Logo, **a ausência do arquivo de nível 4 sozinha não prova que a leitura da matriz
ou o boot falha**. `getFrameworkCompatibilityMatrix` também tem fallback legado.

Por outro lado, o CLI `checkvintf --check-compat` executa `checkDeprecation` além
de `checkCompatibility`. O primeiro procura explicitamente uma matriz declarada
com o nível exato do vendor; sem ela retorna erro de FCM. Assim, o achado anterior
continua relevante para um check host/OTA completo, mas não deve ser apresentado
como execução de falha no boot ou razão para mudar o target artificialmente.

## Schedulerservice ausente não implica o check que antes se supunha

A Samsung exige android.frameworks.schedulerservice HIDL 1.0 na matriz device.
O provider não foi localizado nos manifests exportados. Porém, a implementação
Android 17 examinada de `HalManifest::checkCompatibility` faz checks VNDK,
System SDK, sepolicy e kernel; não contém uma comparação genérica de todos os
HALs required daquela matriz. O CLI ainda chama checks de depreciação e,
condicionalmente, HALs não usados; isso não torna aquele nome ausente prova
de falha no método de compatibilidade ou de serviço quebrado em runtime.

O donor tem scheduling.capex. Seu payload foi inspecionado: possui classpaths
e conteúdo do módulo, sem /etc/vintf nem /etc/init. Isso não fornece o fragment
HIDL que faltava no inventário, mas também não autoriza fingir um provider XML.

## VNDK e uma divergência adicional de sepolicy

O check VNDK examinado exige correspondência exata: device pede 30 e os
manifests framework exportados anunciam somente 34. O APEX VNDK30 foi extraído
para confirmar seu conteúdo; possui libs/listas *.libraries.30.txt, mas não
/etc/vintf. A simples existência desse APEX não acrescenta o manifest ausente.
Outros APEX/fragments e o comportamento do libvintf OEM ainda precisam entrar
num check completo; não foi executado o código ARM64 do donor.

Há ainda um dado de sepolicy mais específico: o manifest vendor declara **30.0**,
enquanto a matriz framework sem nível lista 31.0, 32.0, 33.0, 34.0, 202404,
202504 e 202604, sem 30.0. O Android 17 examinado checa esse conjunto explicitamente.
Isso é diferente da **versão binária de política 30** que o compilador validou.
Não corrigir o número declarado do vendor para 31 só para passar; ele representa
a interface/política realmente fornecida pela vendor.

Um limite importante: a própria vendor **Mi10 do donor** já declara target4,
sepolicy30.0 e VNDK30. Portanto, esses conflitos de metadados não foram criados
inteiramente pela substituição pela vendor Samsung. Precisamos considerar
alterações OEM/port no libvintf e o caminho runtime antes de atribuir causalidade.
O libvintf.so ARM64 do donor (Android API37) retém mensagens de incompatibilidade
e prólogos normais nos métodos, mas isso não prova que não existam patches internos.

## Caminho concreto para validar no GitHub sem baixar AOSP inteiro

Usar um `otatools.zip` oficial de um build Android 17 alinhado e fixar URL/build
ID/SHA256, mantendo o pacote de host tools completo. O Makefile AOSP inclui
checkvintf, check_target_files_vintf, apexd_host/deapexer, e2fs tools e secilc no
conjunto otatools. Assim não é preciso reconstruir o framework Android inteiro.
Não foi escolhido/baixado um build específico nesta tarefa.

Compilar só libvintf/checkvintf em um CMake improvisado exige cuidado: o Android.bp
também usa metadados HIDL/AIDL gerados, esquema APEX, libkver/libkernelconfigs e
outras bibliotecas. Substituir metadados por listas vazias produziria um teste
incompleto. Não há prebuilt checkvintf nos trees consultados dos repositórios
Lineage build-tools/extract-tools; não recomendar um binário antigo apenas porque
ele consegue abrir os XML.

O job futuro deve montar as cinco raízes da composição, disponibilizar fragments
APEX como o próprio build faz, passar propriedades/SKUs reais e o kernel/config
4.19.325. Invocar o CLI com `--dirmap` para cada raiz; registrar separadamente
compatibilidade, depreciação e runtime/kernel. Falha de check não é autorização
para excluir requisitos ou inventar suporte; aprovação tampouco confirma boot.

## Fontes e evidências

Fonte Android17 fixada em commit `df89ad736e14ac375f61d50fa543ae7cd746a140`:

- [CompatibilityMatrix.cpp](https://android.googlesource.com/platform/system/libvintf/+/df89ad736e14ac375f61d50fa543ae7cd746a140/CompatibilityMatrix.cpp), combine/addAllAsOptional.
- [VintfObject.cpp](https://android.googlesource.com/platform/system/libvintf/+/df89ad736e14ac375f61d50fa543ae7cd746a140/VintfObject.cpp), getFrameworkCompatibilityMatrix/checkCompatibility/checkDeprecation.
- [HalManifest.cpp](https://android.googlesource.com/platform/system/libvintf/+/df89ad736e14ac375f61d50fa543ae7cd746a140/HalManifest.cpp), checkVendorNdkCompatibility/checkCompatibility.
- [check_vintf.cpp](https://android.googlesource.com/platform/system/libvintf/+/df89ad736e14ac375f61d50fa543ae7cd746a140/check_vintf.cpp), checkAllFiles.
- [Android.bp](https://android.googlesource.com/platform/system/libvintf/+/df89ad736e14ac375f61d50fa543ae7cd746a140/Android.bp), dependências host.
- [Build Makefile](https://android.googlesource.com/platform/build/+/refs/heads/android17-release/core/Makefile), INTERNAL_OTATOOLS_MODULES.

Fontes foram lidas via mirror de GitHub e trecho primário googlesource; a versão
exata do binário OEM do donor não foi identificada com esse commit.
`audit_metadata.py` gera metadata-facts.json das exportações existentes; não
reimplementa libvintf. Payloads APEX locais foram apenas lidos por debugfs.
