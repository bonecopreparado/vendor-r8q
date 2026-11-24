# Histórico do port

A distribuição começou com a Vendor de ColorOS. O primeiro problema prático era conseguir gravar o pacote inteiro no recovery. Quando o flash passou, a investigação avançou para o kernel, a montagem de Data e o serviço de chaves do aparelho. [Estado atual](../STATUS.md) · [Mapa das branches](BRANCHES.md)

## Antes do ZIP único

Na linha **P0**, o recovery de um tester recusou o caminho que exigia `dd iflag=fullblock`. Nos kits seguintes, o instalador pequeno e os payloads ficavam separados. Na P0r5 o shell produziu um deslocamento negativo. Na P0r6, o cálculo voltou ao início ao chegar à nona parte de Super. A P0r7 passou a trabalhar com blocos e a revisão P0r8 adicionou verificações de bateria. Os arquivos de auditoria também eram ZIPs, o que levou à tentativa de instalar um pacote de relatórios no recovery. [Reprodução dos erros de leitura](../reports/audit-20261031/overnight/reader/LEITURA-MKSH.md) · [Identidade dos payloads](../delivery/Ready-P0r7/PROVENANCE.md) · [Revisão da P0](../reports/review-20261103/RESULTADO.md)

## Releases públicas

As 31 entradas estão em ordem de publicação no GitHub (UTC). Abra a versão para consultar os assets e a proveniência daquela entrega. Para o teste atual, use os [downloads da página inicial](../README.md#downloads).

| Data | Entrega | Mudança |
| --- | --- | --- |
| 21/09/2026 | [Vendor ColorOS](https://github.com/bonecopreparado/vendor-r8q/releases/tag/0.0.1) | Entrada de Vendor publicada antes da linha HyperOS. O asset é Color.os.build.zip. |
| 02/11/2026 | [P1 · ROM](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1-single-experimental-3-1) | Primeira entrega P1 em um ZIP de recovery, com as imagens e o instalador juntos. |
| 02/11/2026 | [BOOTLOG · recovery](https://github.com/bonecopreparado/vendor-r8q/releases/tag/r8q-bootlog-collector-2-1) | Coleta de evidências do boot anterior direto no celular. |
| 02/11/2026 | [P1r1 · ROM](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r1-mapping-experimental-2-1) | Experimento que omite 15 arquivos de mapping em system_ext e oito em product. |
| 03/11/2026 | [P1r2 · ROM](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r2-single-experimental-1-1) | Corrige o ZIP64 e valida os 22 payloads com o leitor ARM64. |
| 07/11/2026 | [BOOTLOG v3 · recovery](https://github.com/bonecopreparado/vendor-r8q/releases/tag/r8q-bootlog-collector-3-1) | Revisão que preserva registros de falhas do boot anterior e sinaliza problemas de coleta. |
| 07/11/2026 | [P1r2 TMPFIX · ROM](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r2-tmpfix-experimental-3-1) | Corrige a execução do instalador quando o mksh do recovery não consegue criar o arquivo temporário do heredoc. |
| 07/11/2026 | [P1r2 EROFS · ROM](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r2-erofs-experimental-delivery-1-1) | Corrige o caso de link simbólico inline que impedia a leitura correta de libc no aparelho. |
| 07/11/2026 | [BOOTDIAG v1 · addon](https://github.com/bonecopreparado/vendor-r8q/releases/tag/r8q-bootdiag-1-1) | Ativação e remoção do registro temporário de logs Android pela Vendor. |
| 07/11/2026 | [BOOTDIAG v2 · addon](https://github.com/bonecopreparado/vendor-r8q/releases/tag/r8q-bootdiag-v2-2-1) | Antecipa a coleta para init e acrescenta amostras dos processos. |
| 07/11/2026 | [BOOTDIAG v3 · addon](https://github.com/bonecopreparado/vendor-r8q/releases/tag/r8q-bootdiag-v3-3-1) | Persiste evidências limitadas em metadata durante a espera pelo boot. |
| 08/11/2026 | [UEVENTD · addon](https://github.com/bonecopreparado/vendor-r8q/releases/tag/r8q-ueventd-compat-1-1) | Adiciona o import canônico das regras de dispositivos do r8q. |
| 08/11/2026 | [UEVENTD R2 · addon](https://github.com/bonecopreparado/vendor-r8q/releases/tag/r8q-ueventd-compat-r2-2-1) | Reconhece os caminhos de System usados no recovery antes de ativar a correção. |
| 08/11/2026 | [BOOTDIAG v4 · addon](https://github.com/bonecopreparado/vendor-r8q/releases/tag/r8q-bootdiag-v4-1-1) | Coleta modos do composer e evidência de configuração do kernel para investigar NFLOG. |
| 10/11/2026 | [PC v4 · Windows](https://github.com/bonecopreparado/vendor-r8q/releases/tag/r8q-pc-v4-collector-1-1) | Ferramenta para puxar pelo ADB os registros disponíveis no recovery. |
| 12/11/2026 | [BOOTDIAG v5 · addon e coletor](https://github.com/bonecopreparado/vendor-r8q/releases/tag/r8q-bootdiag-v5-2-1) | Acrescenta dump nativo do composer e coleta pelo telefone. |
| 15/11/2026 | [P1r3 · ROM](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r3-complete-experimental-2-1) | Integra NFLOG e SUSFS 2.2, correção Group32 no SurfaceFlinger, import ueventd e diagnóstico V6. |
| 15/11/2026 | [P1r4 · ROM](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r4-complete-experimental-1-1) | Inclui a correção do índice de CPU no scheduler identificado durante o boot. |
| 16/11/2026 | [P1r4 IPA · addon](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r4-ipa-stock-fix-2-1) | Adapta o conjunto IPA ao perfil de firmware Samsung conferido. |
| 16/11/2026 | [P1r4 SECURITY R2 · addon](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r4-security-r2-1-1) | Alinha também o IPA UC e repara rótulos da raiz e dos arquivos de contexto da Vendor. |
| 17/11/2026 | [P1r4 MEMORY R3 · addon](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r4-memory-r3-2-1) | Reúne R2 e kernel com MEMCG, PSI e freezer v1 para a P1r4. |
| 17/11/2026 | [P1r4 MEMORY R3 · revisão](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r4-memory-r3-3-1) | Atualiza o pacote e esclarece quais arquivos e rótulos da Vendor dentro de Super são alterados. O ZIP tem novo SHA-256. |
| 17/11/2026 | [P1r5 · ROM](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r5-complete-experimental-1-1) | Passa a entregar firmware R2 e kernel de memória em uma única instalação, com releitura direta. |
| 21/11/2026 | [P1r5 R8QTRACE · ROM](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r5-r8qtrace-experimental-2-1) | Insere marcadores para localizar a última fase atingida pelo init. |
| 22/11/2026 | [P1r5 R8QTRACE KMSG · ROM](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r5-r8qtrace-kmsg-experimental-3-1) | Conserva os marcadores no log do kernel e inclui o coletor em TAR. |
| 22/11/2026 | [P1r5 LATEFS · ROM](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r5-late-fs-experimental-4-1) | Distingue os passos do checkpoint, da montagem de Data e da espera por QSEE. |
| 22/11/2026 | [MOUNT-WAIT · boot](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r5-late-fs-mount-wait-1-1) | Amostra o estado dos processos enquanto o init aguarda mount_all. |
| 22/11/2026 | [VOLD-LOG · boot](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r5-late-fs-vold-log-2-1) | Conserva as mensagens iniciais de armazenamento e o estado de saída dos serviços. |
| 23/11/2026 | [KEYSTORE-LOG · boot](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r5-late-fs-keystore-log-3-1) | Captura o aborto inicial da keystore2 e o erro ao criar o TEE obrigatório. |
| 23/11/2026 | [P1r5 KEYMASTER-TEE · ROM](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r5-keymaster-tee-experimental-5-1) | Integra quatro arquivos do conjunto Samsung Keymaster. O tester confirmou os hashes em Vendor e reproduziu a parada. |
| 23/11/2026 | [TEE-HAL-LOG · boot](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r5-tee-hal-log-4-1) | Registra como o serviço Samsung e o hwservicemanager inicializam e como o cliente descobre o TEE. Aguardando a próxima coleta. |

## Registro de commits

Para localizar uma mudança que não gerou release, este índice reúne os commits alcançáveis pelas branches públicas no momento do levantamento, antes desta revisão da documentação. As mensagens originais permitem cruzar a tabela com `git log`.

<details>
<summary>2026-11 · 95 commits</summary>

| Data do commit | Alteração | Revisão |
| --- | --- | --- |
| 2026-11-23 | Package TEE registration diagnostics over the installed KEYMASTER-TEE boot | [2d5e365](https://github.com/bonecopreparado/vendor-r8q/commit/2d5e365e9a4e2fa92e85b1cde058dfdad071bccf) |
| 2026-11-23 | Record early Samsung Keymaster registration and HIDL discovery | [1354a09](https://github.com/bonecopreparado/vendor-r8q/commit/1354a099bb6b5635b4fac0e35beecfa66f7711e0) |
| 2026-11-23 | Restore Samsung Keymaster with its verified r8q legacy crypto backend | [f1351e4](https://github.com/bonecopreparado/vendor-r8q/commit/f1351e4a92f1db4e1dfcf167acb0e8f443547350) |
| 2026-11-23 | Supply a keystore diagnostic upgrade and exact VOLD-LOG rollback | [23798ec](https://github.com/bonecopreparado/vendor-r8q/commit/23798ec96c7706d8e9c6817048246a52f7a7a461) |
| 2026-11-23 | Preserve the early keystore2 abort message in the recovery-readable log | [80fd383](https://github.com/bonecopreparado/vendor-r8q/commit/80fd3830478095a4cdeae4e1e708f30b9ca5cef8) |
| 2026-11-22 | Package early storage logs over the exact tested MOUNT-WAIT boot | [619bc34](https://github.com/bonecopreparado/vendor-r8q/commit/619bc34c46a4f6c4c0ab76594466fb5296da3fcc) |
| 2026-11-22 | Retain bounded early vdc and vold errors and record service exit status | [0fc3f65](https://github.com/bonecopreparado/vendor-r8q/commit/0fc3f65af331c896e5404e2e7b12c8e78cc3dd72) |
| 2026-11-22 | Deliver mount-wait diagnostics as a guarded boot-only addon | [6f2b0f9](https://github.com/bonecopreparado/vendor-r8q/commit/6f2b0f942e6bc0b56a291800bc11acc07a8d4170) |
| 2026-11-22 | Sample blocked init, vdc and vold tasks during the observed mount stall | [55d17b0](https://github.com/bonecopreparado/vendor-r8q/commit/55d17b0053d9ee47c3f71edafc482933e303ee99) |
| 2026-11-22 | Trace the late-fs checkpoint, userdata mount and QSEE wait in order | [7fac1b8](https://github.com/bonecopreparado/vendor-r8q/commit/7fac1b8faa9f862f5044c369c14b6d1ece6772c2) |
| 2026-11-22 | Keep bounded vendor init boot traces in last_kmsg | [269a6c2](https://github.com/bonecopreparado/vendor-r8q/commit/269a6c27a45dbdd192592ff3fcbfc412f87b1bef) |
| 2026-11-22 | Deliver a complete trace ROM with the verified kernel and TAR collector | [4c90f6c](https://github.com/bonecopreparado/vendor-r8q/commit/4c90f6cfba281ad17135ba43eb7d6fd669336fae) |
| 2026-11-22 | Preserve early R8QTRACE messages from Android init in the kernel log | [4c19d89](https://github.com/bonecopreparado/vendor-r8q/commit/4c19d89f8e60031855185ded02d470ab2331c1d0) |
| 2026-11-21 | Build the published P1r5 base with early boot trace markers | [9e45cff](https://github.com/bonecopreparado/vendor-r8q/commit/9e45cfffc96c1abb7b210e4f3309c1553fe0646a) |
| 2026-11-21 | Collect recovery logs as uncompressed TAR | [5288561](https://github.com/bonecopreparado/vendor-r8q/commit/52885612ee4866612ed5ded0ad3be00e54b07829) |
| 2026-11-21 | Verify recovery gzip by fully decoding when gzip -t is unavailable | [74ba470](https://github.com/bonecopreparado/vendor-r8q/commit/74ba4701ea267d870547538f87eae4de47151b2e) |
| 2026-11-21 | Let the recovery collector save to mounted SD or USB when Data is unavailable | [54a0d33](https://github.com/bonecopreparado/vendor-r8q/commit/54a0d33f731d0b213b85bb1302a1f656f2ad9a13) |
| 2026-11-21 | Trace early Android init milestones in the retained kernel log | [aed7c4d](https://github.com/bonecopreparado/vendor-r8q/commit/aed7c4dca0010c3506f8fc96b250a3d6cf04984e) |
| 2026-11-18 | R8Q-CI-03: rebuild and gate the isolated test revision | [a5b329b](https://github.com/bonecopreparado/vendor-r8q/commit/a5b329bb0203bf67656e4cdadc8eae87031e057d) |
| 2026-11-18 | R8Q-K-01: remove inherited boot-state overrides from repacked boot | [b350bb4](https://github.com/bonecopreparado/vendor-r8q/commit/b350bb45188975f388ddd18823fa245284e5a241) |
| 2026-11-18 | R8Q-CI-02: reject unexpected actual-image checkvintf results | [a1983ef](https://github.com/bonecopreparado/vendor-r8q/commit/a1983ef64a9f4ff0676748cc3634a2d93f29972c) |
| 2026-11-18 | R8Q-CI-01: set the firmware fixture mode explicitly | [a29f930](https://github.com/bonecopreparado/vendor-r8q/commit/a29f930045ee915a294a7bb766b825e2ab6b8991) |
| 2026-11-18 | R8Q-PT-01: confirm mount state after a failed unmount | [11f843b](https://github.com/bonecopreparado/vendor-r8q/commit/11f843ba3309359a971cf82036f7906f390236c2) |
| 2026-11-16 | Build complete P1r5 with baked Samsung IPA R2, SUSFS memory kernel and direct storage readback | [3bfa2a2](https://github.com/bonecopreparado/vendor-r8q/commit/3bfa2a23ab912ea91b71c7574e357d7ea31b589a) |
| 2026-11-16 | Clarify that cumulative Vendor file repairs modify contents inside Super | [2865d70](https://github.com/bonecopreparado/vendor-r8q/commit/2865d70bfbd54cc4815cd1f30f23856d6e88b7d7) |
| 2026-11-16 | Enable package delivery from the recovery branch after interrupted ref updates | [15421aa](https://github.com/bonecopreparado/vendor-r8q/commit/15421aaf3b42b105aa1c4c1835809b0bd8a3d26e) |
| 2026-11-16 | Encode cumulative security script bytes and test the final package integration | [502bdd6](https://github.com/bonecopreparado/vendor-r8q/commit/502bdd6ed12da46cf9460fce99a774486295b914) |
| 2026-11-16 | Package cumulative memory experiment with persistent boot backup and direct readback | [024e770](https://github.com/bonecopreparado/vendor-r8q/commit/024e77022185df8cfeb56d550de17f2a3678aab0) |
| 2026-11-16 | Restore memcg shrinker IDR lifetime synchronization without changing global reclaim | [3827a7d](https://github.com/bonecopreparado/vendor-r8q/commit/3827a7dcee14c621ed4b230c36609502509be5ea) |
| 2026-11-16 | Audit Android 17 r8q references and review memory controllers with SUSFS preserved | [102bc19](https://github.com/bonecopreparado/vendor-r8q/commit/102bc198a805eb8c4de8f18decb970c2564c03aa) |
| 2026-11-16 | Repair Vendor root/context labels and use coherent device-stock IPA UC | [4b21a79](https://github.com/bonecopreparado/vendor-r8q/commit/4b21a7972feea751f88e7180a170d8bc9ebea784) |
| 2026-11-15 | Avoid the mksh hash alias in the IPA installer&#x27;s SHA256 helper | [04dc707](https://github.com/bonecopreparado/vendor-r8q/commit/04dc7076f64f371a315b71d8636b95ecf1825544) |
| 2026-11-15 | Publish the tested IPA addon with a direct Release ZIP and build attestation | [bde75b7](https://github.com/bonecopreparado/vendor-r8q/commit/bde75b70edcdeb61210675bb30f62eb5005280e0) |
| 2026-11-15 | Use device-stock Samsung IPA authentication files in a guarded recovery addon | [9297064](https://github.com/bonecopreparado/vendor-r8q/commit/929706449b211bc39b15e88dfb8afd1225620579) |
| 2026-11-15 | Accept verified r8q TWRP recovery context in V6 collection | [b5bf86d](https://github.com/bonecopreparado/vendor-r8q/commit/b5bf86d7e43670f6f588aba037fd2ac1eb16ff2b) |
| 2026-11-14 | Build P1r4 with the observed scheduler CPU-index crash corrected | [bcef946](https://github.com/bonecopreparado/vendor-r8q/commit/bcef94669e9ef298a7235944b5fc88638cfd67a2) |
| 2026-11-14 | Fix scheduler capacity value used as CPU index in observed boot Oops | [3c2ca68](https://github.com/bonecopreparado/vendor-r8q/commit/3c2ca68e482037d69fd4d7c1868dd526def51251) |
| 2026-11-14 | Bind ueventd staging to exact original init bytes and test real baseline | [54819d5](https://github.com/bonecopreparado/vendor-r8q/commit/54819d534f37f66b8b9b9cb5d105811066951c9b) |
| 2026-11-14 | Build complete P1r3 with verified SUSFS NFLOG kernel and display boot fixes | [99a6ca7](https://github.com/bonecopreparado/vendor-r8q/commit/99a6ca70b00aa2a40880876865689a649436f833) |
| 2026-11-14 | Embed and independently verify the actual built kernel configuration | [9d69eb8](https://github.com/bonecopreparado/vendor-r8q/commit/9d69eb86e7e566c2f139330f985099b250ca77d1) |
| 2026-11-14 | Fix the stale zero-delta scheduler call exposed by the vmlinux link | [0a28913](https://github.com/bonecopreparado/vendor-r8q/commit/0a289134b3e4f85e8bb66239e85685f502de6f4e) |
| 2026-11-14 | Use the public WARN API for MMC power-IRQ timeout diagnostics | [cc4e2a1](https://github.com/bonecopreparado/vendor-r8q/commit/cc4e2a1193e78892b29fe77ce94d34577cd81879) |
| 2026-11-14 | Include the real SUSFS redirect macros in the adapted open path | [4a310bc](https://github.com/bonecopreparado/vendor-r8q/commit/4a310bcfd358804b7e0b5ddf834543a7d5bb12ee) |
| 2026-11-14 | Compile a complete pinned SUSFS22 and NFLOG source candidate for offline review | [19f0a4d](https://github.com/bonecopreparado/vendor-r8q/commit/19f0a4d9ab79d4bcd77495ac59cf840e07b16467) |
| 2026-11-14 | Stage both boot fixes without losing policy operations or Python hash guards | [282db95](https://github.com/bonecopreparado/vendor-r8q/commit/282db95c76126a627fc0124c535e6ddf9419e6c8) |
| 2026-11-14 | Correct truncated SurfaceFlinger display group comparison with exact-file guards | [139960d](https://github.com/bonecopreparado/vendor-r8q/commit/139960df91988c28e7ed99496c82f9573ab7ef8c) |
| 2026-11-12 | Restore real CPU isolation access for RMNET and document required SUSFS integration | [bfb9138](https://github.com/bonecopreparado/vendor-r8q/commit/bfb9138984f629cdb638889e7046997ca8c724ca) |
| 2026-11-12 | Handle both no-clobber mv statuses and make capture fixtures umask-independent | [9008396](https://github.com/bonecopreparado/vendor-r8q/commit/90083966ce38ad0626532e6f15eaa30e79124e52) |
| 2026-11-11 | Deliver native composer diagnostics and guarded phone-only log collector | [7a2bb7d](https://github.com/bonecopreparado/vendor-r8q/commit/7a2bb7df0c4e96be38cb6dc8d36bc46745df88f2) |
| 2026-11-10 | Guard optional MAX77705 CPU frequency votes by their real provider | [5d0a6d9](https://github.com/bonecopreparado/vendor-r8q/commit/5d0a6d99cd3e8f269b3c2f3f48cb1f556ec0dfb0) |
| 2026-11-10 | Retain native probe license notices and inventory runtime dependencies | [c087cdc](https://github.com/bonecopreparado/vendor-r8q/commit/c087cdc12dd24541c4a063e95f2116cd290b4452) |
| 2026-11-10 | Adapt mq-deadline and zram to pinned 4.19 block APIs without disabling features | [c5ca2d3](https://github.com/bonecopreparado/vendor-r8q/commit/c5ca2d3a5898b4ecac009ed41f41794895b0cec3) |
| 2026-11-10 | Reset inherited alarm disposition before bounded composer dump | [1e642ca](https://github.com/bonecopreparado/vendor-r8q/commit/1e642cae31c72bf87562b14ab8fdba0f990227da) |
| 2026-11-10 | Use existing Bionic locale APIs with pinned VNDK30 libc++ headers | [4d0aac7](https://github.com/bonecopreparado/vendor-r8q/commit/4d0aac703aa71ec6fd1566930de803d07b9599a4) |
| 2026-11-10 | Build read-only composer dump client with pinned VNDK30 platform ABI | [e3728d3](https://github.com/bonecopreparado/vendor-r8q/commit/e3728d39b415bf18db55b05f7b3f359998889f45) |
| 2026-11-10 | Preserve network BPF while disabling broken debug UMD and verify compiler cache | [2d6976a](https://github.com/bonecopreparado/vendor-r8q/commit/2d6976a5e455208e560ad9f1b0e68b7055f38583) |
| 2026-11-10 | Provide a Windows collector that rejects empty recovery archives and preserves failures | [8b4677b](https://github.com/bonecopreparado/vendor-r8q/commit/8b4677b0aea54df40290815f622dfe469b6607ba) |
| 2026-11-10 | Use required ThinLTO relocation settings and cap linker workers for the current kernel | [cdea8c3](https://github.com/bonecopreparado/vendor-r8q/commit/cdea8c30d04cb7a70370e966a58a5497d08a36ba) |
| 2026-11-10 | Compile a pinned current NFLOG kernel experiment after conservative configuration checks | [820fcf4](https://github.com/bonecopreparado/vendor-r8q/commit/820fcf4cf20cbb2c57ee3661835830dd4839adb4) |
| 2026-11-10 | Audit the pinned current kernel configuration as a separate NFLOG upgrade experiment | [2a81813](https://github.com/bonecopreparado/vendor-r8q/commit/2a81813437d239187ffe2ca5c35db07eaad76e74) |
| 2026-11-07 | Capture display HAL modes after ueventd progress and pin the NFLOG kernel source plan | [03d1f29](https://github.com/bonecopreparado/vendor-r8q/commit/03d1f29578ed8f340f57d852462470aa7f019166) |
| 2026-11-07 | Reproduce the exact shipped boot and inspect its embedded kernel configuration | [68397fe](https://github.com/bonecopreparado/vendor-r8q/commit/68397fe6e8c56fda443f9d3989c7c5d9ae0b87fc) |
| 2026-11-07 | Validate recovery System aliases by filesystem and inode before ueventd activation | [0888580](https://github.com/bonecopreparado/vendor-r8q/commit/0888580106adfd6aefc0a4349f53d2f2d5d3a0e1) |
| 2026-11-07 | Provide a guarded canonical import for unchanged r8q hardware permissions | [ed53735](https://github.com/bonecopreparado/vendor-r8q/commit/ed537354a56d0d590186f95edf53c8ada27920e0) |
| 2026-11-07 | Inspect pinned device permission rules behind Keymaster startup failures | [c95bdde](https://github.com/bonecopreparado/vendor-r8q/commit/c95bddec35a6bf684f1093c997f798c18be8726f) |
| 2026-11-07 | Capture stalled Android boot in bounded private metadata files | [bc59884](https://github.com/bonecopreparado/vendor-r8q/commit/bc59884e6ee9dc074936a18a69643775998f201a) |
| 2026-11-07 | Start diagnostic capture on init before deferred property actions; add bounded process snapshots | [69861dd](https://github.com/bonecopreparado/vendor-r8q/commit/69861dd1cf5758ca095950534ac8c4c70edf130a) |
| 2026-11-07 | Add reversible vendor boot-log mirror for the userdata startup wait without Android ADB | [8d7f725](https://github.com/bonecopreparado/vendor-r8q/commit/8d7f7256549f644f27c39f9c9ffe53a9f5d7b84a) |
| 2026-11-07 | Record exact libc symlink failure, verified compatibility candidate and recovered delivery | [5249841](https://github.com/bonecopreparado/vendor-r8q/commit/5249841ccbebe3ab2a5d77b861a0a797df9da0fa) |
| 2026-11-07 | Recover exact verified EROFS candidate for delivery and report safe HTTP upload status | [f0649e2](https://github.com/bonecopreparado/vendor-r8q/commit/f0649e2ce8c19ba92660443a07a9133e19bcba2c) |
| 2026-11-07 | Reproduce logged EROFS symlink boundary failure and build plain-target compatibility candidate | [eff9b37](https://github.com/bonecopreparado/vendor-r8q/commit/eff9b377466d669e2edabba74be08690d2f8ad4f) |
| 2026-11-07 | Remove mksh heredoc backing-file dependency from payload table | [8fa3a57](https://github.com/bonecopreparado/vendor-r8q/commit/8fa3a575bde81b7765514e8d9ad0bf791729625f) |
| 2026-11-07 | Fix recovery mksh temporary directory before payload heredoc; reproduce invalid TMPDIR failures | [7e302ee](https://github.com/bonecopreparado/vendor-r8q/commit/7e302ee74447d987ba6d9e4887988149946629ab) |
| 2026-11-07 | Document boot audit findings and phone-only test capture instructions | [9029414](https://github.com/bonecopreparado/vendor-r8q/commit/9029414dd7949122f4469c9b530cf2faa309f367) |
| 2026-11-07 | Preserve latest persistent boot crash records and report collector failures | [d32fa30](https://github.com/bonecopreparado/vendor-r8q/commit/d32fa308301182105dea153b65f1302e1ee58969) |
| 2026-11-03 | Document current P1r2 source, resolve historical review scope, and qualify buffered readback | [17669ef](https://github.com/bonecopreparado/vendor-r8q/commit/17669efee036c538e10ed0d6f3f5ee524c1b3fc1) |
| 2026-11-03 | Build P1r2 complete ZIP with corrected installer and full Android ARM64 payload verification | [a036e2e](https://github.com/bonecopreparado/vendor-r8q/commit/a036e2ed34f82eab1cf6bea34b8ae8c81b6a0fa8) |
| 2026-11-02 | Fix optional ZIP64 records and incomplete package publication; exercise ARM64 CRC boundaries | [f7621c6](https://github.com/bonecopreparado/vendor-r8q/commit/f7621c6b15879e774cab73fa7f52c29c446b28f9) |
| 2026-11-02 | Validate P1r1 delivery before rebuilding and preserve verified ZIP on upload failure | [dcbcce1](https://github.com/bonecopreparado/vendor-r8q/commit/dcbcce1b4e55d66ca7e50f398c0cbbbeef3533a1) |
| 2026-11-02 | Build P1r1 experiment omitting only system_ext and product mapping files | [53834c2](https://github.com/bonecopreparado/vendor-r8q/commit/53834c2b9f0fe51c0bce054cf28f182d05dde066) |
| 2026-11-02 | Exercise collector fixtures under mksh without hiding context-copy errors | [9c6ce23](https://github.com/bonecopreparado/vendor-r8q/commit/9c6ce239db472c04cebcd77dd1a553e62e7a585a) |
| 2026-11-02 | Collect previous boot evidence on-device without changing ROM partitions | [8f006d1](https://github.com/bonecopreparado/vendor-r8q/commit/8f006d181e096c5096d7ae3e443b7745610317e9) |
| 2026-11-01 | Resolve clean-run ext4 reader paths before P1 source reconstruction | [8a06af6](https://github.com/bonecopreparado/vendor-r8q/commit/8a06af65b76c124b32674af8782be494d6637890) |
| 2026-11-01 | Include static Android runtime notices in the complete P1 ZIP | [081aaaa](https://github.com/bonecopreparado/vendor-r8q/commit/081aaaa039585b8ba2f543e2cefaa692547ae46f) |
| 2026-11-01 | Build and distribute one complete experimental P1 recovery ZIP with a native ZIP64 reader | [60267ef](https://github.com/bonecopreparado/vendor-r8q/commit/60267ef2c283589b124e19fe8221178b86bc2bfc) |
| 2026-11-01 | Probe pinned public source endpoints with bounded read-only requests | [da19a10](https://github.com/bonecopreparado/vendor-r8q/commit/da19a10fafce8bc4a27484b7c743d0c54e945a27) |
| 2026-11-01 | Build and validate P1 filesystem candidate with reconciled policy and telephony/NFC init fixes | [0d1d0bc](https://github.com/bonecopreparado/vendor-r8q/commit/0d1d0bcdfb3da2ad34ff2dc7b7291119c92eebe8) |
| 2026-11-01 | Split diagnostic host transport into bounded verified parts | [510c1ef](https://github.com/bonecopreparado/vendor-r8q/commit/510c1ef6ac9cc86f364c88ffab2bad14a62ddbbe) |
| 2026-11-01 | Export reviewed host tool closure and corresponding SELinux relink material for P1 validation | [d84897d](https://github.com/bonecopreparado/vendor-r8q/commit/d84897d8cba4fb06abb4ad9deaa2220e26bdcdff) |
| 2026-11-01 | Consolidate R8Q research, battery guards and reproducible compatibility audits | [d182004](https://github.com/bonecopreparado/vendor-r8q/commit/d18200456efe25821fe9a03746cc18a05db83cb1) |
| 2026-11-01 | Record actual Android 17 incompatibility and measured context findings without clearing ROM hold | [c26eb37](https://github.com/bonecopreparado/vendor-r8q/commit/c26eb37167041cb2f119c9d346e72ee473caa942) |
| 2026-11-01 | Test exact-commit report importing and reject unsafe or mixed workflow evidence | [f423ac5](https://github.com/bonecopreparado/vendor-r8q/commit/f423ac55e8fa99091f3e6fd14fba5f3fabff7e8e) |
| 2026-11-01 | Harden installer power checks and validate clean-source, SELinux and official VINTF evidence | [07df5a9](https://github.com/bonecopreparado/vendor-r8q/commit/07df5a9c05b0add173afb48272b4c5efdecdc566) |
| 2026-11-01 | Normalize test fixture paths when CI supplies a relative installer path | [4e7adca](https://github.com/bonecopreparado/vendor-r8q/commit/4e7adcaaee33c6c96378e7080f39e53da06205a8) |
| 2026-11-01 | Deliver a ready recovery installer for phone-only testers with verified P0 payload identities | [9c3a694](https://github.com/bonecopreparado/vendor-r8q/commit/9c3a6942473c8eb3266221961e7b2554dcfab61b) |

</details>

<details>
<summary>2026-10 · 5 commits</summary>

| Data do commit | Alteração | Revisão |
| --- | --- | --- |
| 2026-10-31 | Clarify historical P0r3 error and record independent installer and VINTF review | [8a87362](https://github.com/bonecopreparado/vendor-r8q/commit/8a873624a3395cf80d5c0ac8513cda709cc06bc0) |
| 2026-10-31 | Package reviewed P0r7 tools, policy evidence and vendor comparison | [3c67e73](https://github.com/bonecopreparado/vendor-r8q/commit/3c67e73b6a278ea7657b2a92e427c57e19ced182) |
| 2026-10-31 | Export vendor init shell scripts as text for review without execution | [3a8fc2a](https://github.com/bonecopreparado/vendor-r8q/commit/3a8fc2a1f87bb861a33b4eada330faf8bcb38bf5) |
| 2026-10-31 | Compare exact ColorOS vendor asset against the verified r8q baseline | [5f53d34](https://github.com/bonecopreparado/vendor-r8q/commit/5f53d3482f733653f4bc282d4ee4f0991b01fa9d) |
| 2026-10-31 | Audit r8q port: fix 32-bit mksh offsets and validate SELinux inputs | [d95b855](https://github.com/bonecopreparado/vendor-r8q/commit/d95b855b7d84ab0b1c591415b8e6d3930d779f28) |

</details>

<details>
<summary>2026-09 · 1 commits</summary>

| Data do commit | Alteração | Revisão |
| --- | --- | --- |
| 2026-09-21 | Initial commit | [28b1491](https://github.com/bonecopreparado/vendor-r8q/commit/28b14910c8eb9ef557e1589ff55122aa55b7802c) |

</details>
