# Logo Samsung após espera longa e Format Data

O usuário relata persistência da logo depois de reiniciar e formatar userdata.
O novo last_kmsg contém um último boot Android de aproximadamente 456,586 s.
Nesse trecho não voltou a ocorrer o erro EROFS inline nem boringssl-self-check-failed.
O F2FS de userdata foi montado em 11,887 s; o último exec visível de vdc é em
11,912 s. Não há evidência de zygote/app_process/boot_completed nesse trecho.
Os registros do kernel continuam enquanto a inicialização de userspace não
mostra novos execs. O boot termina com o registro de reset pelos botões.

Isso é consistente com outra espera/trava de inicialização, não apenas um
primeiro boot que foi interrompido depois de dois minutos. Não demonstra um
erro de operação do usuário. Armazenamento/criptografia/vold/vdc são o próximo
ponto de investigação, mas o comando exato que espera e a causa não estão
comprovados pelo kernel sozinho.

boot-android.txt contém First stage mount skipped (recovery mode) e o processo
recovery até seu fim. Portanto esse arquivo foi capturado já no OrangeFox.
O usuário confirma que ADB só fica disponível no recovery. Não se atribuem
erros exclusivos desse ambiente aos binários da ROM.

Foi preparado um addon temporário para capturar logcat do Android depois de
logd iniciar, antes de depender do término da preparação de userdata. Ele
espelha apenas buffers main/system/crash filtrados em /dev/kmsg durante
120 segundos, até 1500 linhas de no máximo 900 bytes. O buffer kernel é excluído
e marcadores do próprio espelho são ignorados para prevenir realimentação.
O último boot fica legível em last_kmsg no recovery.

ENABLE instala dois arquivos novos em vendor ext4, com guarda do aparelho,
origem dm/vendor e SHA256 do init.qcom.rc efetivamente reconstruído no run
42413135313 (9971fef6dfa6951ec593bd82351203deb71e6185a4eea5354fe2fef3912114ea).
Não usa o baseline incompleto do repositório como identidade da imagem final.
Os labels vêm de arquivos existentes. Os dois temporários são preparados antes
da ativação; o rc é instalado por último. Falha de ativação do rc reverte o
script recém-instalado. REMOVE só apaga os dois arquivos com os hashes esperados.

Este addon é diagnóstico. Não formata, altera chaves, libera ADB inseguro,
desabilita autotestes ou grava imagens de partições. A mudança persistente
limita-se aos dois arquivos de diagnóstico em vendor, reversível pelo REMOVE
ou por reinstalação da ROM completa. O kernel recebe mensagens temporárias.

Testes de guardas, origem errada, payload corrompido, arquivos estranhos/symlink,
remount/label failure, rollback, remoção e filtro sem buffer kernel usam
partições/mounts simulados. A execução no telefone continua pendente.
Os logs brutos do aparelho não foram publicados.
