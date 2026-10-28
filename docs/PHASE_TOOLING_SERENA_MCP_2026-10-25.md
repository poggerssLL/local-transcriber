# Serena MCP — validação de ferramentas (2026-10-25)

## Escopo e instalação

Manutenção local de desenvolvimento, sem commit/push e sem alterações no runtime,
`src/local_transcriber/`, `tests/`, `pyproject.toml` ou `.venv` do aplicativo.
Baseline: branch `main`, HEAD `c53695a8d364020a61d75fe3326f3d3686da182d`,
upstream `origin/main`; working tree já continha alterações, preservadas.

Serena instalado isoladamente por `pipx install git+https://github.com/oraios/serena.git
--python 3.13` (comando em uma linha): pacote `serena-agent 2.1.1.dev0`, origem oficial
fixada na instalação pelo commit `abb0a0f01b94bc8050086f0fb860077d17730324`.
Executável resolvido em `~/.local/bin/serena.exe`; caminho absoluto confirmado
localmente e gravado somente na configuração da máquina. `serena --help` e
`serena start-mcp-server --help` executados com sucesso. `uv 0.13.5` instalado
separadamente via pipx para satisfazer a inicialização do Pyright por uvx.

## Configuração

Adicionado `[mcp_servers.serena]` em `.codex/config.toml`, com executável absoluto,
`start-mcp-server --context ide-assistant --project <raiz absoluta>`, cwd na raiz
e `startup_timeout_sec = 120`. Flags adicionais desativam abertura e serviço de
dashboard. Os quatro blocos anteriores permaneceram byte a byte intactos;
sintaxe validada com `tomllib`.

`.serena/project.yml` seleciona Python/Pyright, backend LSP e `agent_interface:
tools`: esta versão usa REPL por padrão, que não expõe `find_symbol` individual.
`.serena/.gitignore` exclui artefatos gerados e permite somente a configuração.

## Validação real, sem mocks

- `initialize`: servidor Serena 2.1.1.dev0, resposta em 4,66 s na execução final.
- `tools/list`: 21 ferramentas, incluindo `get_symbols_overview`, `find_symbol`
  e `find_referencing_symbols`.
- Pyright 1.1.403 iniciado por uvx em ambiente isolado; primeiro uso baixou suas
  dependências. Ausência inicial de uv e interface REPL foram identificadas e
  corrigidas na configuração/provisionamento, antes da validação final.
- Graphify MCP `query_graph` encontrou `_reduce_synthesis`, sua classe
  `TranscriptSummarizer` e relações com `summarize`, `_call_ollama` e `_extract_json`.
- Serena `find_symbol`, com `name_path_pattern=TranscriptSummarizer/_reduce_synthesis`,
  `relative_path=src/local_transcriber/summarizer.py` e `include_body=true`, retornou
  um único método, linhas humanas 673–744 (72 linhas; índices LSP 672–743).
  O arquivo tem 1.212 linhas; seu conteúdo integral não foi carregado no contexto.
  O grafo orientou a localização e o LSP confirmou o símbolo no código atual.
- Hashes SHA-256 dos arquivos preexistentes conferidos: nenhum arquivo fora da
  allowlist documental/configuração foi modificado nesta manutenção.

## Regras e limites

`AGENTS.md` estabelece Graphify → Serena → leitura em lote de docs, proíbe o
conector `codex_apps.github.*`, restringe memória externa a pedido nominal e
impede revisão de release não solicitada em pedidos diretos de commit/push.
As instruções de prioridade superior continuam prevalecendo.

A pesquisa obrigatória de README/pyproject oficial via MCP `github` separado
**não foi concluída**: chamadas da sessão e inicialização direta pelo iniciador
do projeto falharam com `fetch failed`/timeout de conexão. Uma tentativa com
preferência IPv4 também falhou. Nenhum conector interno foi utilizado. Os argumentos
foram confirmados pelo CLI instalado, o que não substitui essa pesquisa via MCP.

O teste stdio direto prova o servidor configurado; não prova descoberta automática
pela sessão atual. Reabrir a sessão é necessário para carregar o novo MCP.
O grafo é salvo e pode estar desatualizado; não foi reconstruído. Não houve
inferência/transcrição, teste funcional do aplicativo ou nova fase de produto.
