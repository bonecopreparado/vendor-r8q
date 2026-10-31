# Compatibilidade offline: auditoria da composição P0

Nenhuma imagem ou ZIP entregue foi alterado. Os logs novos são do recovery,
portanto esta auditoria não declara boot, HALs ou framework executando.

Foram lidos 84 documentos VINTF e 387 declarações de serviço nos RC exportados
das cinco partições usadas na P0. `audit_offline.py` refaz o inventário e consulta
as imagens somente por `dump.erofs --path` e `debugfs stat`. Não executa os
binários Android e não abre as imagens para escrita.

## Achados novos com prioridade

| Prioridade | Evidência | Implicação e limite |
|---|---|---|
| Alta | `vendor/etc/vintf/manifest.xml` anuncia `target-level="4"`; as matrizes system presentes têm níveis 7, 8, 202404, 202504 e 202604. | Falta uma matriz de framework correspondente ao nível original do dispositivo. Validar com libvintf/checkvintf compatível antes de modificar. Isso não é uma falha de boot observada. |
| Alta | A matriz device Samsung exige `vendor-ndk` 30; os manifests framework anunciam somente 34 em `system_ext/etc/vintf/manifest.xml`. | APEX VNDK30 presente não resolve por si só a divergência de metadados. É necessário confirmar os requisitos de libvintf e a ativação/ABI das bibliotecas antes de declarar suporte 30. |
| Alta | A matriz device Samsung exige explicitamente `android.frameworks.schedulerservice@1.0::ISchedulingPolicyService/default`, `optional="false"`; esse nome não aparece em nenhum manifest framework exportado de system/system_ext/product. | Há requisito declarado sem provider framework declarado na composição. Não inventar um XML afirmando que o serviço existe; validar a necessidade runtime e disponibilizar implementação/compatibilidade real. |
| Média | `init.target.rc` chama `exec_start wait_for_keymaster`; nenhum dos 387 serviços exportados tem esse nome. | Referência legada precisa ser reconciliada com o boot moderno e keymaster/vold Samsung. Não concluir que isso bloqueia boot: um `exec_start` de nome ausente pode só registrar erro. Não substituir por serviço que retorna sucesso sem esperar a inicialização real. |
| Média | Fstab do ramdisk P0 já tem product/system_ext EROFS; vendor continua com product ext4 e sem system_ext. | Existe inconsistência textual. First stage já usa o ramdisk ajustado, logo não há prova de que a inconsistência seja a causa de um bootloop. Candidato mínimo isolado preparado abaixo. |

`vintf-inventory.json` preserva arquivos, hashes, atributos, versões, interfaces e
fqnames. A comparação é por nome e inventário, não reimplementa libvintf: não
resolve intervalos de versões HIDL, instâncias regex, overrides, filtros por
nível, manifests dentro de APEX ou a semântica v9 de `optional`. Em particular,
os 293 registros de nomes ausentes em matrizes suplementares OEM **não são 293
bugs comprovados ou requisitos obrigatórios**. Não remover essas linhas em lote.

Allocator, HIDL manager e token existem em fragments de system_ext, e não são
serviços ausentes. O máximo de nível declarado nesses fragments é 8, portanto
o target 4 não os exclui por esse atributo.

## Serviços e arquivos

Inventário: 310 declarações têm executável presente; 73 apontam a arquivo não
encontrado (46 caminhos distintos); duas dependem de APEX, uma de expansão de
propriedade e uma de outra raiz/mount. As 73 declarações incluem modos factory,
variantes, serviços `disabled` e overrides intencionais; isso não corresponde a
73 serviços ativos quebrados. `services-inventory.json` inclui origem, opções e
resultado literal do stat para cada declaração.

Exemplos que não devem gerar correção cega:

- `adbd` em `/system/bin/adbd` não aparece como arquivo solto, mas a declaração
  é `updatable` e o donor fornece `com.android.adbd.capex`. A ativação APEX precisa
  substituir o serviço; a simples ausência desse caminho não prova ADB quebrado.
- `derive_sdk`, `derive_classpath`, `art_boot` e `mainline_aconfigd_init` são nomes
  não encontrados nos RC soltos e potencialmente fornecidos por APEX. Separados
  da referência Samsung `wait_for_keymaster` no inventário.
- Os quatro `vendor.ril-daemon*` apontando a `rild-dummy` fazem parte de overrides
  Samsung para desativar caminhos Qualcomm; `ril-daemon` real em `/vendor/bin/hw/rild`
  existe. Remover os overrides não é uma correção de SMS/VoLTE.
- `miuibpfservice` está `disabled` e seu arquivo está ausente; o `netbpfload` de
  Android é outra etapa. Não usar essa ausência para declarar BPF inteiramente
  quebrado nem forçar `bpf.progs_loaded=1`.
- `mqsasd` ausente e `hypsys_system` presente disputam nomes de sockets nas
  declarações, mas a substituição de serviços/RC do port precisa de logs antes
  de remover arquivos. Os dois nomes não são o mesmo serviço.

Os executáveis de SurfaceFlinger, vold, hwservicemanager, vndservicemanager,
composer QTI, audio HAL, Bluetooth, keymaster/gatekeeper, health Samsung, câmera
Samsung e fingerprint Samsung foram encontrados. Presença não valida suas
dependências, namespaces do linker, registro Binder nem hardware.

O ODM mantém NFC OPlus/NXP além dos serviços Samsung do vendor. A auditoria
anterior já identificou `libpnscr2_aidl.so` não encontrada em diretórios soltos.
Essa é prioridade para diagnóstico NFC posterior; não explica o erro de leitura
dd do instalador e não é autorização técnica para apagar todos os serviços OPlus.

## Propriedades e componentes que parecem contraditórios

O framework system tem identidade `generic` e system_ext `missi`; isso por si só
não demonstra que o ZIP seja uma GSI. A composição Xiaomi/QSSI OEM inclui essas
identidades de partição. Não substituir todas as identidades por `umi`: os imports
Samsung dependem de `ro.product.vendor.device=r8q` e de `ro.product.vendor.name`.
A ordem de propriedades está declarada `odm,vendor,product,system_ext,system`.

Há configuração Xiaomi de cust, mas as esperas por uma partição física `cust`
exigem `ro.miui.preinstall_to_data` vazio. O product define `=1`, usa caminho
`/data/preinstall/cust.img` e `cust_data_keeper` real está em `/system/bin/uncrypt`.
Não se comprovou espera infinita por uma partição Samsung inexistente; verificar
a execução de `xiaomi_mount_cust` e a origem de cust.img no primeiro boot.

O kernel P0 é 4.19.325 e possui EROFS, binder/hwbinder/vndbinder, binderfs, ashmem,
memfd, FS_ENCRYPTION e DM_DEFAULT_KEY nas flags extraídas. Portanto não há base
para trocar o kernel só pelo número da versão ou pela idade da vendor. A auditoria
SELinux continua prioritária: permissive não corrige uma política inválida.

## Candidato de fstab preparado, sem distribuição

`prepare_fstab_alignment.py` confere o SHA256 da origem e produz apenas texto em
`vendor-fstab-candidate/`. Adiciona product EROFS e alternativas system_ext ext4/
EROFS com os mesmos flags do ramdisk já preparado. Todo o restante precisa ser
idêntico byte a byte; `/data`, criptografia, AVB e firmware não foram alterados.
O status é `NON_SHIPPING_TEXT_ALIGNMENT_CANDIDATE`. Não foi aplicado a vendor.img,
super ou ZIP e não é apresentado como correção de boot comprovada.

## Próxima verificação que exige ferramenta compilada

Executar `checkvintf --check-compat` com libvintf alinhada ao framework e as cinco
raízes da composição. Preservar target-level original 4 e propriedades/SKUs reais;
não mudar o target só para adequar a uma matriz disponível. Incluir kernel real
4.19.325 e seu config no teste, além dos manifests APEX após extração/ativação.
O resultado deve identificar incompatibilidades completas; a tarefa de CI não deve
tratar a presença dos XML ou comparação por nome como validação de libvintf.

As correções de VINTF acima dependem da validação e do caminho runtime. Não foi
produzido um patch para remover requisitos, falsificar providers ou anunciar ABI
sem sustentação. A resolução de conflitos SELinux e a leitura do recovery precisam
seguir em paralelo antes de chamar uma candidata de bootável.
