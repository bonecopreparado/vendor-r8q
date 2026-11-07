# Diagnóstico v1 instalado, mas sem captura; revisão v2

O usuário confirmou a mensagem de ativação do v1. O último last_kmsg recebido
tem uma tentativa Android de cerca de 181 s, ainda sem erro de EROFS/BoringSSL,
com userdata montada e o último exec visível do vdc em 11,712 s.
Não há R8QBOOT em nenhum dos buffers recebidos. O recovery.log é da coleta,
não traz o histórico da instalação; boot-android.txt continua sendo recovery.

A captura v1 usava apenas on property:init.svc.logd=running. A semântica AOSP
documenta que ações de propriedade sem evento não são verificadas antes do
one-time check depois do evento boot, mesmo quando a propriedade muda.
Isso torna o gatilho inadequado para investigar uma espera anterior ao fim
do boot. É um defeito do diagnóstico, não evidência de erro do tester.
A ausência dos marcadores, sozinha, não identifica todas as possíveis falhas
de execução no aparelho.

Referências:
https://github.com/aosp-mirror/platform_system_core/blob/main/init/README.md#triggers
https://github.com/aosp-mirror/platform_system_core/blob/main/init/init.cpp

A v2 usa on init com start assíncrono. O script emite BEGIN antes de esperar,
por até 20 segundos, pelo socket do logd. Conserva o filtro de buffers sem
kernel e o limite 120 s/1500 linhas/900 bytes. Também coleta duas fotografias
limitadas de processos e stacks em 20 e 60 s. Só subcomandos vdc expressamente
permitidos aparecem; senhas/outros argumentos não são copiados.

O modelo de ordem de eventos em teste reproduz a propriedade v1 inacessível
antes de uma espera em userdata e exige que a v2 comece antes dela. Trata-se
de um modelo limitado da ordem documentada, não de execução do init Xiaomi.
Testes adicionais verificam remoção do v1 e instalação limpa do v2. Os hashes
legados foram obtidos do ZIP v1 original, verificado por seu SHA256 publicado.

O usuário deve instalar V2 REMOVE primeiro, depois V2 ENABLE, manter ENABLE
durante o boot de teste e só remover depois de guardar last_kmsg.
V2 ENABLE não sobrescreve silenciosamente arquivos de outra versão.

Esta revisão corrige a instrumentação. A causa do bloqueio da ROM perto da
preparação de userdata segue sem diagnóstico conclusivo. Nenhuma imagem
completa, chave de criptografia ou configuração de autenticação ADB foi alterada.
Os arquivos brutos do aparelho não foram publicados.
