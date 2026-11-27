# Retomar o trabalho no r8q

O primeiro teste ao voltar é o **TEE-HAL-LOG sobre a P1r5 KEYMASTER-TEE**. A pergunta é se o serviço de chaves da Samsung inicia, registra a instância padrão via HIDL e fica visível para a `keystore2`. A montagem de Data e o boot completo vêm em seguida. [Última observação no aparelho](../STATUS.md)

## Compatibilidade do perfil IPA no teste de 26/11/2026

Um SM-G780G que identifica o firmware como `G780GXXSHEYJ1` tentou instalar a P1r5. A bateria de 24% estava carregando e passou. O AVB também passou com flags 3. O pacote parou ao conferir `ipa_fws.b01`, antes de qualquer gravação. O perfil publicado contém o hash `8bc6bf3243e4a76cd18e5128cccf1cf1b7c6653ee228116d16b3b8e086cf8231`, proveniente do perfil testado com G781BXXSIHYJ2. A release menciona G780G e G781B, então essa diferença precisa ser resolvida no perfil de firmware antes de outro flash nessa versão. Preserve o `recovery.log` com `adb pull /tmp/recovery.log recovery-p1r5-26nov.log`. A foto e a linha de erro estão resumidas em [STATUS](../STATUS.md).

## Para quem está com o telefone

1. **Se o aparelho está na stock**, leia os pré-requisitos da release completa. Ela exige um SM-G780G ou SM-G781B compatível, bootloader desbloqueado, recovery compatível, AVB já em flags 3 e o perfil esperado de firmware. Guarde os dados pessoais e os arquivos de restauração fora do aparelho. O instalador confere a carga e o firmware antes da escrita de `super`, `dtbo` e `boot`. O ZIP completo tem **5.389.737.668 bytes** e excede o limite de arquivo único do FAT32. Confira o SHA-256, salve o ZIP inteiro no armazenamento interno, em um cartão exFAT ou em USB OTG e selecione **Install** no recovery. Aguarde a confirmação de sucesso da P1r5. Em caso de erro, guarde o `/tmp/recovery.log` antes de reiniciar. Após o sucesso, reinicie primeiro em **Recovery** para recarregar as partições e siga a etapa 2 para o teste com diagnóstico. [Release da base e instruções](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r5-keymaster-tee-experimental-5-1)
2. **Se a KEYMASTER-TEE já está instalada**, baixe o diagnóstico e confira o SHA-256 na tabela abaixo. No TWRP, abra **Advanced → ADB Sideload** e deslize para iniciar. No CMD do Windows, dentro de `platform-tools`, rode o comando abaixo. [Baixar TEE-HAL-LOG](https://github.com/bonecopreparado/vendor-r8q/releases/download/p1r5-tee-hal-log-4-1/R8Q-P1r5-LATEFS-TEE-HAL-LOG.zip)

   ```bat
   adb sideload "%USERPROFILE%\Downloads\R8Q-P1r5-LATEFS-TEE-HAL-LOG.zip"
   ```

3. Ao aparecer `R8Q boot image verified`, escolha **Reboot → Recovery** e, ao voltar, **Reboot → System**. Pule o Format Data. Se o Android iniciar, anote se chegou à tela de configuração ou à tela inicial. Se ficar na logo por cerca de **três minutos**, volte diretamente ao recovery.
4. Abra o ADB Sideload novamente e rode o coletor. Guarde o TAR no local indicado por ele, inclusive quando terminar em `PARTIAL.tar`. Se o sideload do diagnóstico falhar, salve o `recovery.log` **antes** de reiniciar o recovery. [Baixar coletor V6](https://github.com/bonecopreparado/vendor-r8q/releases/download/p1r5-keymaster-tee-experimental-5-1/R8Q-BOOTDIAG-V6-COLLECT-ONLY.zip)

   ```bat
   adb sideload "%USERPROFILE%\Downloads\R8Q-BOOTDIAG-V6-COLLECT-ONLY.zip"
   ```

   Saia da tela de sideload, volte ao ADB normal do recovery e copie o registro da sessão.

   ```bat
   adb pull /tmp/recovery.log recovery-do-teste.log
   ```

5. Junto com o TAR, anote o modelo, a versão do firmware Samsung, o recovery utilizado, os nomes dos ZIPs e se o aparelho ficou na logo ou reiniciou sozinho. O pacote de retorno repõe somente a imagem de boot que acompanhou a KEYMASTER-TEE. [Baixar restauração do boot](https://github.com/bonecopreparado/vendor-r8q/releases/download/p1r5-tee-hal-log-4-1/R8Q-P1r5-LATEFS-RESTORE-KEYSTORE-LOG.zip)

### Integridade dos downloads

| Arquivo | SHA-256 publicado |
| --- | --- |
| `HyperOS4-R8Q-P1r5-KEYMASTER-TEE-SINGLE-EXPERIMENTAL.zip` | `0da9b84f2a5d3c92d5e60fdd51a1c11de2bbf4815034394f95bb9fd0205ca150` |
| `R8Q-P1r5-LATEFS-TEE-HAL-LOG.zip` | `4d5151dd705b642ad73c2755f5dd6764212da756b995d959d19798735cad94af` |
| `R8Q-BOOTDIAG-V6-COLLECT-ONLY.zip` | `0b4e7e1e9d0d762be559f39d16b0fb62e4cbefb3d5b3bedffa623791a3f889af` |
| `R8Q-P1r5-LATEFS-RESTORE-KEYSTORE-LOG.zip` | `40dee9625050e8f4a3a950e757ec1e3ba1acacb66cbe0d5fbf413b50894a19fa` |

Para conferir o diagnóstico no CMD, rode o comando abaixo e compare os 64 caracteres com a tabela.

```bat
certutil -hashfile "%USERPROFILE%\Downloads\R8Q-P1r5-LATEFS-TEE-HAL-LOG.zip" SHA256
```

A ROM grande é distribuída pelo GoFile. Guarde uma cópia verificada para retomar os testes caso o link externo expire. O GitHub guarda o manifesto, o checksum e a proveniência. [Arquivos da base](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r5-keymaster-tee-experimental-5-1) · [Arquivos do diagnóstico](https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r5-tee-hal-log-4-1)

## Para quem vai investigar o próximo TAR

Abra `last_kmsg`, localize a **última** ocorrência de `Booting Linux` e considere os marcadores daquela tentativa. No último teste o ADB só apareceu no recovery. Um TAR parcial foi suficiente para localizar o aborto da `keystore2`.

| Primeira observação no boot novo | O que verificar em seguida |
| --- | --- |
| `R8QTEE` do linker relata biblioteca ou símbolo ausente | Identificar o executável, a biblioteca, o símbolo e o namespace exatos. Comparar com Vendor, sistema e VNDK 30 da mesma build. |
| O gerenciador informa HIDL indisponível, ou o serviço não consegue registrar | Conferir o manifesto efetivo, `/dev/hwbinder`, rótulos e a instância `android.hardware.keymaster@4.0::IKeymasterDevice/default`. |
| A Samsung relata serviço pronto, mas a `keystore2` ainda aborta | Correlacionar os horários de registro, descoberta do TEE e retorno do adaptador legado. |
| `mount-all:end` e `post-fs-data` aparecem | Anotar o primeiro estágio novo e investigar a próxima falha. Para confirmar boot completo, registrar a tela atingida e, quando houver ADB no Android, `adb shell getprop sys.boot_completed`. |
| Faltam marcadores | Conferir o ZIP e o SHA do boot, a mensagem de instalação e qual boot foi retido. O marcador de processo `running` sozinho é insuficiente para concluir que houve registro. |

## Para quem vai mexer no código

| Entrega | Revisão | Receita e última execução verificada |
| --- | --- | --- |
| ROM KEYMASTER-TEE | `f1351e4` | [Workflow da ROM](https://github.com/bonecopreparado/vendor-r8q/blob/f1351e4a92f1db4e1dfcf167acb0e8f443547350/.github/workflows/r8q-p1r5-singlezip.yml) · [Execução](https://github.com/bonecopreparado/vendor-r8q/actions/runs/45089674475) |
| Kernel que produz `R8QTEE` | `1354a09` | [Workflow do kernel](https://github.com/bonecopreparado/vendor-r8q/blob/1354a099bb6b5635b4fac0e35beecfa66f7711e0/.github/workflows/r8q-memory-kernel-review.yml) · [Execução](https://github.com/bonecopreparado/vendor-r8q/actions/runs/45097900380) |
| ZIP do diagnóstico e restauração | `2d5e365` | [Workflow dos ZIPs](https://github.com/bonecopreparado/vendor-r8q/blob/2d5e365e9a4e2fa92e85b1cde058dfdad071bccf/.github/workflows/r8q-mount-wait-addon.yml) · [Execução](https://github.com/bonecopreparado/vendor-r8q/actions/runs/45098026380) |

Para ler a fonte exata do diagnóstico e executar os testes locais de validação da imagem e do reempacotamento, use Git e Python 3.12 em Linux.

```sh
git clone https://github.com/bonecopreparado/vendor-r8q.git
cd vendor-r8q
git switch --detach 2d5e365e9a4e2fa92e85b1cde058dfdad071bccf
python3 -m unittest discover -s ci-r8q/tests -p 'test_susfs22*.py' -v
```

Ao compilar um kernel sucessor, preserve os pins de fonte, configuração, KernelSU e SUSFS. O empacotador procura a compilação pelo commit e confere o digest do artefato. Se o artefato temporário expirar, a receita correspondente precisa rodar novamente na revisão correta. Para atualizar a ROM completa, parta da branch KEYMASTER-TEE. [Mapa das branches](BRANCHES.md)

A base de comparação inclui as árvores LineageOS do r8q e do sm8250-common, os blobs TheMuppets e as versões 23.2 e 24.0. Os commits usados na análise estão registrados por componente. [Referências e pins](https://github.com/bonecopreparado/vendor-r8q/tree/f1351e4a92f1db4e1dfcf167acb0e8f443547350/reports/p1/lineage-reference-20261116) · [Fonte do kernel Not](https://github.com/notkernel-oss/not_samsung.sm8250-4.19) · [Vendor externa do port ColorOS](https://github.com/bonecopreparado/aaa-67-vendor/releases/tag/Vendor)

## Guardar o projeto para depois

O GitHub conserva as branches, tags, receitas e documentação independentemente desta conversa. Para guardar uma cópia offline de todas as referências públicas, execute estes comandos no computador com Git. Escolha uma pasta nova e copie também os ZIPs de teste e seus checksums para fora da pasta do repositório.

```sh
git clone --mirror https://github.com/bonecopreparado/vendor-r8q.git vendor-r8q-espelho.git
git -C vendor-r8q-espelho.git bundle create ../vendor-r8q.bundle --all
git -C vendor-r8q-espelho.git bundle verify ../vendor-r8q.bundle
```

Para abrir o histórico salvo, execute `git clone vendor-r8q.bundle vendor-r8q-retomada`. A ROM no GoFile e os assets de Releases ficam fora do banco de objetos Git.
