# SELinux: reconciliação isolada e compilação integral preparada

Nenhum filesystem, boot, super, vendor ou ZIP de instalação foi alterado.
O candidato continua isolado; não foi carregado num kernel nem testado em boot.

## Bloqueios estruturais confirmados

A composição P0 combina plat/system_ext/product HyperOS com vendor Samsung.
Os identificadores de plat/system_ext/product não correspondem à política
pré-compilada do ODM Adrian. O fluxo normal do init precisa compilar os CIL.
Não atualizar os três identificadores apenas para forçar o uso da política
ColorOS original: isso ocultaria uma divergência real.

A composição original falha em uma colisão entre `(type sysfs_battery_supply)`
no system_ext e um alias com o mesmo nome no vendor. Há a mesma colisão para
`sysfs_memory`. O mapping system_ext 30.0 também referencia/expande
`vendor_smcinvoke_device_30_0` sem declarar esse atributo.

O candidato mínimo preserva os aliases vendor e seus tipos reais e remove
somente aquelas duas declarações de tipo no system_ext. Adiciona a declaração
do atributo versionado cujo typeattributeset já está presente. Não remove
regras allow, neverallow, policycaps ou contextos para fazer a compilação passar.

## Semântica da fusão por aliases

Essa mudança mantém os nomes usados pela política donor, mas as permissões
destes nomes passam a incidir sobre os tipos reais Samsung:

- `sysfs_battery_supply` resolve para `vendor_sysfs_battery_supply`: radio do
  donor passa a poder procurar diretórios e ler/consultar/abrir/observar os
  arquivos com aquele rótulo. Há seis genfscon vendor para dispositivos de
  bateria/charger/bms/wireless com o tipo real.
- `sysfs_memory` resolve para `vendor_sysfs_memory`: artd preserva search em
  diretórios; hypsys_ssi_default preserva search e read/write/getattr/open em
  arquivos. Isso precisa de avaliação funcional; não chamar a união segura
  apenas porque a AST resolve. Não foi localizado um file_contexts explícito
  para esse rótulo nos três arquivos extraídos consultados.
- `vendor_smcinvoke_device` é um tipo existente nas duas políticas e o vendor
  rotula `/dev/smcinvoke` com ele. A mudança adiciona um atributo de versão,
  não um novo tipo nem um novo dispositivo. Evidência dos contextos em
  `context-evidence.json`.

## Compilador compatível encontrado e fixado

O host tem libsepol 3.8.1 e rejeita `functionfs_seclabel` após resolver a AST.
Essa capability continua preservada. A omissão temporária feita anteriormente
foi somente diagnóstico; não integra este candidato ou o bundle.

Foi confirmado via GitHub plugin que SELinuxProject/selinux no commit
`6423998bc7b154da7f9fe726cfda9ace774dfa94` reconhece
`POLICYDB_CAP_FUNCTIONFS_SECLABEL`. Fonte imutável:
https://github.com/SELinuxProject/selinux/blob/6423998bc7b154da7f9fe726cfda9ace774dfa94/libsepol/src/polcaps.c
(blob Git `b31fdfedcca0948424f8b29947a1a599b4792140`).

Build mínimo para CI Linux, evitando link acidental com libsepol antiga:

```
make -C upstream/libsepol/src libsepol.a
cc -D_GNU_SOURCE -I upstream/libsepol/include -I upstream/libsepol/cil/include \
  upstream/secilc/secilc.c upstream/libsepol/src/libsepol.a -o secilc-host
cc -I upstream/libsepol/include policy-bundle/check_policy_caps.c \
  upstream/libsepol/src/libsepol.a -o check-policy-caps
python3 tools/run_policy_audit.py --secilc /absolute/secilc-host \
  --cap-checker /absolute/check-policy-caps \
  --inputs-dir /absolute/policy-bundle --output-dir /absolute/new-results
```

O wrapper foi disponibilizado em `tools/run_policy_audit.py` para o root.
O diretório de resultados precisa ser novo. Sintaxe Python foi verificada.
A compilação integral precisa ser executada no CI com essas fontes novas;
não houve execução desse compilador no host até este relatório.

## Bundle de auditoria entregue ao root

`selinux-policy-audit-bundle.tar.gz`, 715.635 bytes, SHA256
`e2f1f72e28e3f55ea0ce896a98b4b48e017dbf74c385538e9fb4f3484b6b2524`.

Contém dez CIL originais, três CIL genfs opcionais, dois CIL candidatos,
diffs, manifesto com hashes, driver e fonte do verificador de capabilities.
Não contém imagens ROM, política vendor binária, userdata, EFS ou logs pessoais.
O root decide onde disponibilizar esse insumo para CI; nenhuma publicação foi
feita por este agente.

O driver confere identidades antes de compilar, reproduz a falha original e
compila o candidato em dois modos: init normal (`-m -M true -G -N -c 30`) e
auditoria neverallow (sem `-N`). O teste anterior só chegava a build_policydb;
este também serializa e reabre a política binária e exige os seis policycaps
originais, incluindo functionfs_seclabel. Compilar sem capability ou retornar
um arquivo vazio não satisfaz esse fluxo. Achados neverallow ficam separados
no JSON e mantêm o resultado geral não validado.

A versão 30 foi observada no cabeçalho da política ODM Adrian original. Isso
não mede a versão máxima do kernel durante execução. O kernel r8q candidato
tem EROFS/XATTR/SECURITY e SELinux no config. A ausência da string
functionfs_seclabel no kernel não prova rejeição da política; o próprio kernel
tem mensagens de capabilities desconhecidas. Compatibilidade de carga e efeito
dessa capability ainda precisam de evidência de runtime.

## Genfs: hipótese delimitada

O donor inclui plat_sepolicy_genfs_202504/202604/202704.cil. O vendor Adrian
não tem genfs_labels_version.txt no inventário de /etc/selinux. A biblioteca
upstream consultada retorna default 202404 quando o arquivo falta; no fluxo
AOSP atual init só acrescenta o arquivo genfs que corresponde exatamente à
versão e ignora se ausente. Não existe arquivo 202404 no donor consultado.
Portanto o teste padrão mantém a lista anterior sem genfs extra; o bundle
permite selecionar exatamente um caso caso a seleção do init OEM seja provada.

Fontes de referência (não prova do comportamento do binário OEM):
https://github.com/aosp-mirror/platform_system_core/blob/main/init/selinux.cpp
https://github.com/LineageOS/android_system_sepolicy/blob/d61fd80832f558d52de026097d30d695634e8b0f/compat/libgenfslabelsversion/src/lib.rs

## Antes de aplicar em uma ROM

Ainda faltam compilação integral com capabilities preservadas, auditoria dos
neverallow, confirmação da seleção de CIL no init OEM, carga no kernel e logs
de boot. Caso seja aplicado depois, preservar metadados/xattrs do filesystem e
recalcular identificadores da política conforme o esquema real de build;
não copiar hashes novos sobre precompiled ColorOS incompatível. Nenhum binário
de política produzido pelo ensaio deve ser apresentado como ROM corrigida.
