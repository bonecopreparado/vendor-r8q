Comparação offline da nova vendor indicada como ColorOS 16.0.10.

O módulo não acessa rede, monta filesystems ou usa ADB. A entrada Brotli é fixada
por tamanho/SHA256 e a transfer list correspondente também tem hash fixo. O job
de CI deve obter o asset e chamar a ferramenta; a imagem produzida é somente
para análise e não deve ser publicada como uma ROM ou instalada no telefone.

```sh
python3 -m pip install -r vendor_audit/requirements.txt
python3 vendor_audit/test_audit.py
python3 vendor_audit/audit_vendor.py audit \
  --source /caminho/vendor.new.dat.br \
  --transfer vendor_audit/data/vendor.transfer.list \
  --baseline vendor_audit/data/baseline-vendor.zip \
  --output /caminho/vendor-analysis
```

Executar de `ci-r8q` ou ajustar os caminhos. Precisa de cerca de 2 GiB livres
além do asset baixado. O Ubuntu runner deve disponibilizar `e2fsck`; se presente,
ele é executado apenas com `-f -n` e um resultado não limpo interrompe a análise.
O parser ext4 não substitui fsck, não valida xattrs/checksums e não reproduz o
journal. Recursos/layouts não suportados são recusados.

O diretório de saída precisa ser novo. A ferramenta reconstrói todos os ranges
new/zero/erase de uma OTA full v4, recusando incremental, sobreposição, gaps,
truncamento e bytes Brotli sobrando. A imagem local é lida; configurações são
exportadas com hashes e o inventário inclui permissões, uid/gid e symlinks.
Arquivos acima de 64 MiB não são hasheados e aparecem explicitamente no limite.

Publicar somente `RELATORIO-VENDOR-1610.zip`, `analysis.json` e `e2fsck.txt` como
artefatos de análise. O ZIP contém os configs antigos/novos para comparação,
incluindo scripts `/bin/*.sh` da vendor nova (exportados como texto, sem executar),
não contém os APK/SO completos nem a imagem reconstruída.

`baseline-vendor.zip` foi exportado do vendor original efetivamente usado na P0:

- Imagem: 1.647.726.592 bytes, SHA256
  `18e48f734c31f263f330786ffea841738a733784da05b5b6d86b5e5217d82d5f`.
- Baseline compacta: 2.306.551 bytes, SHA256
  `320fab260c5b571fb3cde1288d30d67b904ef7c5381e4b1d73715ddf2867699e`.
- 2.819 arquivos e 371 configs exportados, incluindo todos os arquivos SELinux
  (também os contextos sem extensão) e `.conf` de hardware; 166 hashes coincidiram
  com extrações anteriores independentes feitas com debugfs.

Para refazer a baseline a partir da cópia original verificada:

```sh
python3 vendor_audit/audit_vendor.py export-baseline \
  --image /caminho/vendor-original-r8q.img --output /caminho/baseline-nova
```

O nome ColorOS 16.0.10 é uma informação fornecida pelo usuário, não um fato
confirmado pelo nome do asset. `analysis.json` mostra as propriedades declaradas
por arquivo, sem confundir isso com a ordem efetiva de carregamento no Android.
Diferenças de conteúdo, Android declarado, números de versão ou tamanho não
demonstram uma base melhor, boot funcional ou compatibilidade SELinux/HAL/ABI.
