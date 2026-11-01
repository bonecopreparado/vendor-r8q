# Vendor ColorOS 16.0.10: comparação concluída

O asset indicado pelo usuário foi baixado no GitHub Actions, conferido por tamanho
e SHA256, reconstruído com a transfer list recebida e aprovado por `e2fsck -fn`.
Não foi aplicado a nenhuma imagem P0 nem instalado em aparelho.

Execução final: https://github.com/bonecopreparado/vendor-r8q/actions/runs/41258897001
Relatório/configs: https://gofile.io/d/nRL4xE8l
SHA256 do RELATORIO-VENDOR-1610.zip:
52611e12807255db3b37ea82ff4a483b2ae0686ca710843db1776de475d48e27.

## Identidades e resultado

Asset Brotli: 936.067.987 bytes, SHA256
2d80788f5336cf82aa1a3e8c625f8942aac410be014a820186369173946199af.
Imagem reconstruída: 1.687.379.968 bytes, SHA256
6f1b7fb4a70e72e040fb8f68e56e196a542af84047ca24ef7b20441503a30695.
Baseline P0: 1.647.726.592 bytes, SHA256
18e48f734c31f263f330786ffea841738a733784da05b5b6d86b5e5217d82d5f.

Comparação: 2571 arquivos regulares com hash igual, quatro com conteúdo diferente,
oito arquivos adicionados, um removido. Há 243 entradas comuns sem comparação
de hash, incluindo symlinks e arquivos acima do limite de 64 MiB. Não declarar
que absolutamente todos os drivers foram comparados ou que hashes validam ABI.
Os modos/uid/gid/symlinks comparados não mudaram; xattrs não foram comparados.

As políticas e contextos SELinux exportados são idênticos. A nova vendor não
resolve o conflito estrutural com o framework HyperOS. O rótulo ColorOS 16.0.10
vem do usuário; o conteúdo isolado de vendor não comprova a versão da ROM inteira.

## Mudanças relevantes

- Adiciona Face HAL AIDL `android.hardware.biometrics.face` versão 4, serviço
  `vendor.facehal` e cinco bibliotecas/componentes de face/TensorFlow. O serviço
  configura `LD_LIBRARY_PATH=/vendor/lib64` e inicia em post-fs-data. Presença
  não comprova registro Binder, contextos, dependências nem desbloqueio facial.
- Altera somente duas propriedades em build.prop: densidade 480 para 430 e
  `ro.soc.model=SM8250` para `SM8750`. O segundo valor não corresponde ao SoC
  do S20 FE Snapdragon e não representa melhoria do hardware.
- Acrescenta system_ext **ext4** à fstab, mas não resolve o uso EROFS de
  system_ext/product da nossa composição. Remove entradas keydata/keyrefuge;
  isso exige revisar criptografia, não copiar como se fosse correção universal.
- Remove `/bin/brightness_sync.sh` e mantém o serviço `brightness_sync`
  apontando para esse executável em init.qcom.rc. É uma referência quebrada.
- Acrescenta comandos `settings put secure ...` diretamente ao init.qcom.rc,
  com chaves de AOD OPlus. `settings` é comando de shell, não builtin do init
  Android padrão. O init HyperOS extraído também não contém a string literal
  `settings`, embora contenha os nomes normais setprop/exec/start. Isso não
  sustenta considerar esse bloco como correção de AOD para HyperOS.
- Adiciona serviço root `vendor_enforce` para executar `/vendor/bin/enforcing.sh`.

O script novo escreve `1` em `/dev/enforce` e tenta bind-mount desse arquivo
sobre `/sys/fs/selinux/enforce`; também tenta ajustar propriedades ro.* para
anunciar enforcing. Não carrega uma política válida nem altera o enforcement
real do kernel como `setenforce` faria. Pode mascarar a leitura de estado e
atrapalhar o diagnóstico. Como depende de post-fs-data, tampouco resolve falha
anterior de compilação/carregamento da política pelo init. Não foi executado.

## Decisão para o projeto

Manter a vendor original como base da P0 enquanto reconciliamos SELinux/VINTF.
Não incorporar a nova vendor inteira como uma melhoria demonstrada. O Face HAL
pode ser avaliado isoladamente depois do boot básico, com dependências, rótulos,
registro AIDL e comportamento reais; isso não autoriza declarar face funcional.

O comparador antigo tinha um erro de API de listagem; o módulo novo corrigiu,
validou os ranges full OTA/Brotli, exportou contextos sem extensão e scripts
como texto, sem executá-los. Treze cenários passaram no CI e localmente com a
dependência Brotli. Os relatórios não contêm a imagem reconstruída ou ROM flashável.
