# Validação 8H após publicação — Windows independente

Data: 2026-10-13. Commit de instalação/licença publicado: `d157c5c`.
Push em main confirmado pelo Git remoto; somente os 13 arquivos da entrega.
Mudanças locais 8D–8G, source do summarizer e fixtures ficaram fora do commit.

O workflow [Windows installation](https://github.com/poggerssLL/local-transcriber/actions/runs/38486327574)
concluiu com status **success** num runner `windows-latest` do GitHub,
independente do computador do autor, com Python 3.13 x64 e checkout novo.
Instalação normal sem extra dev/modelos e smoke de pacote instalado passaram:
assets da interface, HTTP local e banco SQLite sintético. Licença pessoal/não
comercial incluída; nenhum dado pessoal/modelo foi enviado ao GitHub.

Essa evidência complementa o teste local registrado na manutenção 8H. O runner
possui componentes de sistema pré-instalados; não é homologação de todo hardware
Windows, instalação offline inicial, Linux/macOS/ARM, GPU ou inferência de fala.
Não houve modelo baixado/inferência no workflow. Qualidade de transcrição/resumo
e as pendências semânticas 8G continuam independentes da aprovação de instalação.
