# Confirmação da reprodução e candidata EROFS-COMPAT

O baseline recriado tem o mesmo SHA256 da imagem system da TMPFIX.
A condição rejeitada pelo kernel aparece exatamente em:

- /system/lib64/libc.so: NID 32610047; inode no offset 4064, cabeçalho 32, xattrs 52, alvo 46 bytes.
- /system/bin/xxd: NID 16044031; inode no offset 4064, cabeçalho 32, xattrs 48, alvo 6 bytes.
- /system/bin/stty: NID 16042495; inode no offset 4064, cabeçalho 32, xattrs 48, alvo 6 bytes.

Na candidata, system tem 421 links e system_ext tem 49; todos usam layout FLAT_PLAIN. Product não tem links. Os 10.803 caminhos das três partições foram comparados, incluindo metadados, bytes e relações de hardlink.

Validação: 182 testes unitários, 8 fixtures EROFS, 45 cenários do instalador em mksh, 3 casos específicos de criação da tabela e 22 payloads reais lidos pelo helper ARM64 no ZIP final.

ZIP: 5387781650 bytes.
SHA256: da979bf387771b09e103864548e090ccb40f1624fd038cf76a9317b96a221f80

Build: https://github.com/bonecopreparado/vendor-r8q/actions/runs/42413135313
Atestado: https://github.com/bonecopreparado/vendor-r8q/attestations/64920684

A build concluiu a geração e as verificações, mas o primeiro upload HTTP para GoFile falhou (curl 22). A cópia verificada foi preservada para recuperação da entrega. Nenhum boot em aparelho foi realizado com esta candidata. O erro de leitura foi removido das imagens; outras falhas de boot podem aparecer depois.

## Entrega recuperada

O reenvio do mesmo ZIP concluiu com sucesso, com tamanho e MD5 remotos confirmados.

Download: https://gofile.io/d/VqaKUFUB
Release e SHA256: https://github.com/bonecopreparado/vendor-r8q/releases/tag/p1r2-erofs-experimental-delivery-1-1
Recuperação da entrega: https://github.com/bonecopreparado/vendor-r8q/actions/runs/42415335939

O instalador exibe EROFS-COMPAT revision. O nome do ZIP mantém P1r2, mas seu SHA256 é o da candidata descrita acima. A inicialização no aparelho permanece sem confirmação.
