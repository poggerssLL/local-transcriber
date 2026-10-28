# Integra??o MCP local do Graphify ? 2026-10-25

## Resultado

Servidor Graphify adicionado ? configura??o MCP do projeto, por stdio, com caminhos absolutos para execut?vel, grafo e diret?rio de trabalho. Configura??es anteriores preservadas. Prefer?ncias de uso de Graphify e GitHub registradas em AGENTS.md.

## Instala??o e valida??o real

O execut?vel existia, mas faltava a depend?ncia mcp. Instalado o extra graphifyy[mcp] mantendo graphifyy 0.9.92 no ambiente pipx existente; mcp 2.3.0 instalado. Nenhuma depend?ncia do aplicativo foi alterada.

- TOML analisado e caminhos conferidos.
- Codex reconheceu servidor habilitado com transporte stdio.
- Inicializa??o e tools/list reais: dez ferramentas.
- graph_stats real: 1.586 n?s, 4.542 rela??es, 89 comunidades.
- query_graph real sobre TranscriptSummarizer: recupera??o de n?s e localiza??es, sem erro.
- pip check no ambiente Graphify: sem requisitos quebrados.

## Limites

O grafo informa commit anterior ao HEAD atual; n?o foi reconstru?do. A consulta teve or?amento de 500 tokens e resultado truncado. Nenhuma ferramenta de PR, opera??o GitHub ou acesso Graphify Cloud foi executado. As ferramentas de PR do Graphify podem usar gh internamente.

Reabrir a sess?o ? necess?rio para descobrir o novo servidor no agente; o teste ocorreu com cliente MCP independente usando a mesma configura??o. Testes do aplicativo n?o foram executados porque s? houve configura??o de ferramentas e documenta??o. Sem commit ou push. Altera??es preexistentes preservadas.
