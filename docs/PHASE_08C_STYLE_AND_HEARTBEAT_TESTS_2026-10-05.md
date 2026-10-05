# Manutenção 8C — Estilo e testes de heartbeat

Data: 2026-10-05. Baseline Git `5d58eeb`, incluindo alterações preexistentes
da Etapa 8/8B copiadas por allowlist para checkout isolado fora de pasta sincronizada.
Autorização: manutenção paralela recomendada, confirmada por Erick.
Versão `0.7.1` e schema v4 preservados. Entrega local sem commit/push.

## Alterações delimitadas

- Formatação e comprimento de linha somente em `api.py`, `summarizer.py`,
  `test_api_summary.py` e `test_summarizer.py`. Comparação AST comprovou igualdade
  funcional; em três docstrings do teste da API houve apenas reflow, comprovado
  com normalização de whitespace das docstrings. Strings de produção preservadas.
- `test_heartbeat_bounds_retries_when_sqlite_does_not_recover` recebe FakeClock
  estável na fila e no worker. O teste continua exigindo exatamente quatro
  tentativas, sinal de perda, primeira exceção SQLite, thread encerrada, job running,
  ausência de erro persistido e nenhuma transcrição publicada após callback stale.
- Novo teste `test_heartbeat_stops_retry_when_confirmed_lease_margin_is_exhausted`
  avança o relógio na falha de renovação e prova parada após a primeira tentativa,
  sinal de perda e LeaseOwnershipLost, sem sleeps ou thread no teste novo.
- Código de produção do heartbeat/leases, migrações, frontend e demais alterações
  preexistentes preservados. Relatório histórico 8B não reescrito.

O teste original competia com duas condições legítimas de parada: limite de
retries e margem segura de uma lease real de 150 ms. A inspeção comprova essas
duas ramificações; a mudança separa suas provas. Não comprova retrospectivamente
qual evento do ambiente causou a falha histórica 8B, nem remove a proteção de
expiração da implementação. Timeouts externos de sincronização continuam limites.

## Validação atual

Usado o intérprete do ambiente existente, sem instalação. PYTHONPATH foi apontado
ao `src` isolado e a origem importada de local_transcriber foi confirmada dentro
desse checkout; não se assumiu o destino do editable install.

| Critério | Evidência | Natureza / limite |
| --- | --- | --- |
| Fila | 24 testes aprovados, 10,63 s | Engines falsos, SQLite e fixtures sintéticos |
| Suíte completa | 142 aprovados, 25,14 s, exit 0 | Mocks/fixtures, sem inferência real |
| Ruff global | `ruff check src tests`, exit 0 | Nenhum E501 remanescente |
| Formatação | `ruff format --check src tests`, 28 já formatados, exit 0 | Check global |
| Sintaxe Python | Compile de todos os `.py` em src/tests, sem gravar bytecode | Exit 0 |
| Equivalência funcional de estilo | AST de quatro arquivos comparada ao baseline protegido | Três docstrings apenas refluídas |
| Dependências | `pip check`, exit 0, no broken requirements | Aviso de distribuição inválida ~ocal-transcriber permanece |
| Git | `git diff --check`, exit 0 | Mudanças existentes preservadas; sem release |

Temporários de pytest foram direcionados a diretórios novos exclusivos da
manutenção, fora do checkout original, com `-p no:cacheprovider` e `-B`.
Não houve limpeza recursiva nem alteração de `.test-tmp`, fixtures antigas ou
resíduos da 8B no checkout original. A primeira checagem de origem importada teve
erro de quoting no shell; a checagem corrigida passou antes da suíte completa.

Não houve serviço Ollama real, nova inferência CPU/CUDA, modelo/download, mídia
pessoal, servidor real ou monitoramento de isolamento da rede do sistema.
O aviso de ambiente não foi reparado; nenhuma configuração global foi alterada.
Etapas futuras permanecem não iniciadas.
