# Revisão ampliada: instalador, SELinux e compatibilidade

A reprodução com mksh real identificou a causa dos erros de instalação em
2 e 4 GiB: os scripts anteriores usavam offsets em bytes em aritmética e
comparações numéricas de 32 bits. Não há evidência de defeito do dd ou do UFS
nesses sintomas. A P0r7 corrige esses usos; as imagens da ROM continuam iguais.

## Correção concreta do instalador

No mksh R59 compilado a partir de fontes verificadas:

- `2147483648/4096` produz `-524288`, exatamente o argumento recusado na P0r5.
- `[ 4294967296 -eq 0 ]` é verdadeiro, enquanto a comparação textual não é.
  Na P0r6 isso repetia o descarte de prefixo e solicitava 131071 blocos em vez
  de 131072. O dd entregou exatamente o que o script incorreto pediu.
- A soma do cursor em bytes também voltava a zero nessa posição.

A P0r7 usa comparação textual para offset zero, cursor em blocos de 4 KiB
(capacidade inteira é só 2512896 blocos) e AWK para validar offsets/tamanhos
grandes antes de qualquer escrita. Nenhum hash, guard AVB, tamanho, montagem
ou verificação de retorno foi retirado. Não foi adicionado helper binário.

Passaram 37 cenários completos do instalador sob mksh e cinco regressões com
aritmética real, arquivo esparso de 10 GB, OUTFD=9, corrupção em 8 GiB e EOF
na última região. Os testes anteriores em bash e shim de dd não isolavam a
semântica do shell e não bastavam para descobrir a causa. A P0r6 falhou em
super-008 no teste novo usando o dd GNU normal; a P0r7 conferiu tudo.

O diagnóstico somente leitura anterior também continha comparação numérica
de offset. Foi substituído por **Diagnostico-Leitura-R8Q-r2.zip**, que usa
comparação textual e registra a versão/aritmética do shell. Mais sete cenários
passaram, incluindo a imagem P0 real de 10 GB sob mksh com ambos os leitores
nativos. O diagnóstico antigo não deve ser usado para concluir integridade.

O corretor Python aceita os ZIPs pequenos P0r5/P0r6, valida o instalador conhecido
e todos os dados, preserva origem/payloads e cria somente INSTALAR-P0r7.zip.
14 cenários do corretor e 15 do uploader passaram localmente. Não foi executado
o shell exato do tester nem Windows/OrangeFox real; ainda não há boot confirmado.

## SELinux: política isolada, não aplicada à ROM

Os dez CIL originais foram reextraídos das imagens e conferidos byte a byte.
O candidato altera somente duas declarações de tipo conflitantes e um atributo
versionado ausente. Não remove a capability `functionfs_seclabel`.

O fluxo de CI compila libsepol/secilc do commit
`6423998bc7b154da7f9fe726cfda9ace774dfa94`, que reconhece a capability, e exige
serializar/reabrir a política mantendo os seis policycaps originais. A comparação
inclui a falha original, o candidato com flags normais do init e a auditoria
neverallow adicional. A execução real confirmou compilação e serialização no
modo init com os seis policycaps. A auditoria adicional encontrou 335 registros
neverallow; um controle com tipos separados apresentou os mesmos conjuntos de
assertions/allows impressos. O job ficou vermelho por essa auditoria adicional.
Fusões de alias também unificam permissões/contextos: compilar não aprova a
semântica nem confirma carga no kernel. Ver selinux/CI-RESULTADO.md.

## Novos pontos de compatibilidade

Foram inventariados 84 XML VINTF e 387 serviços. Há divergências estáticas:

- Vendor declara FCM 4; as matrizes framework presentes começam em 7.
- A matriz Samsung exige vendor-ndk 30; framework anuncia 34. APEX VNDK30 existe,
  mas isso sozinho não valida os metadados nem a ABI.
- A matriz Samsung exige schedulerservice HIDL 1.0, sem provider declarado nos
  manifests framework examinados.
- `wait_for_keymaster` é chamado em init sem definição nos RC exportados.

Exigem checkvintf/libvintf compatível e/ou logs de boot; não são falhas de boot
observadas. Foram separadas variantes factory, overrides e serviços fornecidos
por APEX para não declarar falsamente dezenas de bugs. Nenhum requisito VINTF
foi apagado nem serviço/ABI fictício anunciado.

Candidato textual isolado de fstab alinha product/system_ext EROFS ao ramdisk
já ajustado, sem tocar userdata/criptografia. Não foi aplicado à vendor.img.

## Entregas locais e execução remota

- `output/Correcao-P0r7-Windows.zip`, 27717 bytes, SHA256
  `2a036a0accd69094737113f5ef8a8987b45aa00d1c95d1746687d335e586acf6`.
- `output/Diagnostico-Leitura-R8Q-r2.zip`, 3948 bytes, SHA256
  `1a6a14a5a35b90fa2069d313563ceee353e4a2e467fbcefa61cfba26fd57f82b`.
- `output/Auditoria-R8Q-20261031.zip`: ferramentas e evidências, não ROM flashável;
  o hash muda quando novas evidências/resultado CI são acrescentados.
- Branch remota `bonecopreparado/vendor-r8q:r8q-audit-20261031`; execução inicial:
  https://github.com/bonecopreparado/vendor-r8q/actions/runs/41249309007.

O uploader usa API oficial atual do GoFile, valida tamanho/hashes/URL, preserva
proxy/TLS e não registra tokens. O artefato do GitHub é salvo antes do espelho.
Upload inicial concluído: https://gofile.io/d/QwzAjDJr. A compilação real e o
resultado da auditoria são descritos acima. O pacote final agrega a comparação
de vendor e os relatórios posteriores, sem refazer os testes já aprovados.
Nenhum log pessoal de recovery/logcat nem imagem da ROM foi publicado no branch.

## Vendor nova: decisão após comparação real

Os jobs 41258248272 e 41258897001 baixaram o asset exato e reconstruíram uma
imagem limpa em e2fsck. A comparação mostrou 2571 hashes iguais, quatro arquivos
alterados, oito adicionados e um removido; há limites de hash/xattrs descritos
no relatório. Políticas SELinux iguais. A vendor nova mantém referência para
brightness_sync.sh removido, anuncia SM8750 em vez de SM8250 e acrescenta script
que tenta mascarar a leitura do enforcement, sem corrigir a política. Não é uma
troca integral recomendada para a P0. Manter a base atual; Face HAL novo pode ser
avaliado isoladamente após boot. Relatório completo em
vendor/COMPARACAO-CONCLUIDA.md e https://gofile.io/d/nRL4xE8l.

O próximo avanço de sistema precisa reconciliar a política e VINTF antes de
apresentar uma build como pronta para uso. Falhas após gravar super deixam
instalação incompleta: restaurar a base antes de iniciar aquele estado.
