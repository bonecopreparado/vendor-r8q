# R8Q: comparação truncada de grupos de modos no SurfaceFlinger

Foi localizado um defeito concreto na biblioteca recebida do aparelho. A
comparação de grupos de modos lê 32 bits do candidato e somente 8 bits do modo
padrão. A correção offline troca essa segunda leitura por 32 bits. A ROM ainda
não foi reconstruída ou testada com essa correção.

## Vínculo com o crash

O Build ID da biblioteca enviada é `37802932c7e56f8bdcec511be7bb1e90`, igual ao
registrado no abort em `constructAvailableRefreshRates`, PC `0x493c9c`.
Os logs mostram `allowGroupSwitching=false` e faixas de frequência abertas,
mas o SurfaceFlinger termina com:

`No matching frame rate modes for primary range even after ignoring the render range`

Os atributos SDM registrados nos três boots mostram configurações 0 e 1 com
1080×2400, DPI iguais e frequências 120 e 60 Hz. Não são valores inventados para
contornar a seleção de modos.

## Caminho no código de máquina recebido

No compositor com SHA256
`39b509d355bd642f57a111521df31ef817c7938fbf7a736dbe0cfad255d51c3a`,
`sdm::HWCDisplay::GetDisplayAttribute` começa em `0x64784`. O atributo 7,
CONFIG_GROUP, chega ao ramo `0x64984`. Havendo uma configuração correspondente
em geometria, DPI e flags, o ramo termina em `0x64bd4`, armazenando `w22`.
Esse registrador contém a largura após a compensação de bordas, normalmente
1080 neste painel. O código retorna um inteiro, não um booleano. A própria
biblioteca do SurfaceFlinger consulta o atributo 7 em `0x395bc8` e armazena
a resposta com `str w0` em `0x395bd8` no caminho de configurações legadas.

O predicado de seleção do SurfaceFlinger começa em `0x49b8b8`. Após verificar
resolução e DPI, e quando a troca de grupos não está permitida, executa:

```asm
0x49b950: ldr  w10, [x19, #0x30]  // grupo candidato, 32 bits
0x49b954: ldrb w8,  [x8,  #0x30]  // grupo padrão, somente 8 bits
0x49b958: cmp  w10, w8
```

Para grupo 1080 (`0x438`), a segunda leitura produz 56 (`0x38`). Assim, o modo
padrão e o outro modo do mesmo grupo são rejeitados. Também existe o erro
inverso: candidato 56 pode passar como se pertencesse ao grupo 1080.
Outras comparações de grupo no seletor usam cargas de 32 bits.

A correção substitui somente `ldrb w8` por `ldr w8` no mesmo endereço. Mantém
as verificações de grupo, geometria, DPI e faixas de frequência. Não remove
asserts, não força 60/120 Hz e não altera o compositor, kernel, KernelSU ou SUSFS.

## Validação executada

- O patcher foi aplicado à biblioteca privada recebida. SHA256 do resultado:
  `f11986fff4ce9d9f1b59d282722d529b8f847f78bac4e4f0a308fe80d911abd6`.
  O tamanho permanece 13.826.216 bytes. Somente dois bytes mudam.
- O caminho de atributos do compositor foi emulado usando suas instruções
  reais e uma árvore de configurações sintética. CONFIG_GROUP retornou sucesso
  e 1080 para as duas configurações de painel modeladas. WIDTH, HEIGHT e
  VSYNC_PERIOD também foram conferidos para validar a montagem do objeto.
- O predicado inteiro recebido foi emulado antes/depois: candidatos 60 e
  120 Hz do grupo 1080 passam depois da correção; resolução divergente, grupos
  diferentes e frequências fora da faixa continuam rejeitados. A falsa
  equivalência entre 56 e 1080 desaparece. Foram testados os retornos false e
  true da chamada externa de flag, totalizando 24 pares de resultados.
- Oito testes automatizados adicionais verificam a comparação ARM64 para 100
  pares int32, reversão exata, rejeição de arquivos desconhecidos/já alterados,
  estrutura ELF, contexto da instrução e proteção contra sobrescrita.

O relatório sanitizado `received-function-emulation.json` e o script
`tools/display_group/review_received.py` permitem reproduzir a revisão sem
publicar os binários ou logs privados. A emulação usa memória sintética,
substitui duas chamadas externas iniciais e ignora PAC; não reproduz Android,
Binder, hardware nem um boot completo. O grupo 1080 é derivado do código e dos
atributos registrados; não foi obtido por uma captura direta de getDisplayAttribute
no Binder enquanto o sistema rodava.

## O que ainda impede anunciar uma ROM corrigida

`system_ext` é EROFS. A biblioteca corrigida precisa entrar na reconstrução
com preservação de metadados e compatibilidade de symlinks do kernel antigo;
os hashes de super, payloads e ZIP devem ser regenerados. A receita e os
SHA256 exatos estão em `tools/display_group/README.md`. Ainda não existe um
novo ZIP de ROM contendo essa alteração.

Os mesmos logs também mostram uma falha independente em netd: o kernel
instalado não oferece NFLOG, a instalação das regras iptables falha e o
processo termina. A integração completa do kernel com SUSFS continua pendente,
conforme a escolha do usuário de manter SUSFS. Esta correção gráfica não
resolve NFLOG e não justifica dizer que a ROM já dá boot. Não há indicação
de que repetir Format Data ou simplesmente esperar mais resolva esses aborts.
