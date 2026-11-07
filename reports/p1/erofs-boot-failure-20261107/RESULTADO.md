# Falha do boot: motivo registrado e erro EROFS anterior

Foram recebidos recovery.log, logcat.log, dmesg.log, last_kmsg e lastkmsg.txt.
O usuário confirmou a instalação da revisão TMPFIX do commit
8fa3a575bde81b7765514e8d9ad0bf791729625f, run 42407115135.

O last_kmsg contém registros misturados de boots anteriores e bootloaders.
Não se trata todo o arquivo como uma única inicialização. Quatro boots do kernel
4.19.325-st11-rc-not:A.06 repetem 20 falhas de erofs_fill_symlink no dm-0,
NID 32610047. O final de uma tentativa registra:
- 3,958 s: política SELinux carregada; capacidades desconhecidas 9/12 apenas avisadas.
- 4,017 s: second_stage do init.
- 4,434 s: execução de linkerconfig do APEX runtime.
- 4,452 s: EROFS "inline data cross block boundary @ nid 32610047".
- A mesma leitura falha em aconfigd-system, kcmdlinemodprobe e prng_seeder.
- 4,525 s: execução de boringssl_self_test64.
- 4,527 s: erro do mesmo inode no processo do autoteste.
- 4,531 s: reboot, boringssl-self-check-failed.

O motivo imediato do reinício está confirmado no registro. O erro EROFS repetido
é um bloqueador concreto de leitura anterior. O log não traz stderr do linker
do autoteste: não se afirma qual teste criptográfico falhou nem que ele chegou
a rodar. A pista pode ser uma falha na resolução do interpretador ou de outra
dependência compartilhada. A política SELinux já foi carregada e o BPF não é
o motivo registrado desta sequência.

O offset do slot desse NID em um bloco de 4096 bytes é 4064.
Kernels antigos rejeitam o fast symlink quando inode+atributos+alvo ultrapassam
o bloco, mesmo que o leitor moderno de userspace consiga ler a imagem.
A CI recria a imagem anterior com SHA c591be3f417b43c6b9734c3385ceea507c11ba2c27e0a5d5e853ef8a22addc72
e só prossegue se reproduzir o NID registrado com o mesmo erro do modelo antigo.
O relatório desse baseline identifica o caminho real do link; não se inventa
esse caminho a partir do nome do processo.

A candidata usa erofs-utils 1.8.6, commit
3689cbc2349bff05807d2f939146e92eb1bfaea1, com alteração localizada para
usar o fallback FLAT_PLAIN existente para alvos de links. As três partições
EROFS são reconstruídas, todos os alvos e metadados são comparados e nenhum
symlink inline é aceito na saída. A ferramenta original fica separada para
a reprodução do defeito. A proveniência registra código e binário da ferramenta.
Não se altera o conteúdo do BoringSSL nem se remove reboot_on_failure.

Essa correção pode remover o primeiro bloqueador observado. Não demonstra que
o restante da ROM inicia. VINTF/kernel/HAL e outras adaptações continuam abertos.
Os buffers correntes de recovery não substituem o last_kmsg do Android.
Os arquivos brutos com dados de aparelho não foram publicados.
