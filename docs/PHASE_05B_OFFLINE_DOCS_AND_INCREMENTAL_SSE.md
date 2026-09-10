# Etapa 5B — documentação offline e SSE incremental

## Escopo

Esta correção complementar permanece dentro da Etapa 5. Ela não implementa frontend,
worker remoto nem funcionalidades futuras. O relatório histórico
`PHASE_05_LOCAL_API_AND_SSE.md` permanece inalterado.

A versão passa a `0.5.1`. O schema SQLite continua v4, pois a tabela de eventos já possui
índice por `(job_id, sequence)` e a correção exige apenas uma consulta diferente.

## OpenAPI sem CDN

O Swagger UI padrão do FastAPI foi desabilitado com `docs_url=None`; ReDoc já permanecia
desabilitado. A especificação OpenAPI JSON continua disponível em
`/api/openapi.json`.

Assim, a aplicação não serve HTML que referencie `cdn.jsdelivr.net` ou qualquer outro
recurso HTTP/HTTPS externo. Um visualizador OpenAPI offline poderá ser avaliado somente em
uma etapa futura explicitamente autorizada; nenhum asset Swagger foi baixado ou
incorporado nesta correção.

## Consulta incremental de eventos

`Repository.list_job_events` preserva a chamada histórica `list_job_events(job_id)` e
passa a aceitar `after_sequence` e `limit`. A consulta usa parâmetros para:

- restringir `job_id`;
- selecionar `sequence > after_sequence`;
- ordenar por `sequence` crescente;
- limitar o lote quando solicitado.

Cursores negativos e limites fora de 1 a 1000 são rejeitados antes de consultar o banco.
Cursor zero retorna desde o primeiro evento; cursor igual ou superior ao último retorna
lista vazia.

## SSE em lotes

O SSE usa lote padrão de 100 eventos. Depois de cada lote não vazio, consulta novamente
imediatamente a partir da última sequência entregue. O `poll_interval` só é aguardado após
uma consulta vazia, eliminando a releitura do histórico e evitando atraso artificial ao
drenar backlog.

Após uma consulta vazia, o estado do job é lido em conexão separada. Se ele for terminal,
uma última consulta incremental cobre a transição concorrente e entrega o evento final
antes de encerrar. Desconexão continua sendo verificada entre lotes e antes da espera;
heartbeat e `Last-Event-ID` foram preservados. Exceções de banco encerram o produtor em vez
de criar busy loop, e nenhum handle SQLite permanece aberto durante a espera assíncrona.

## Validação determinística

O baseline `872f9aaae1734bcdaebccc27b80a07576c051475` foi confirmado limpo e alinhado a
`origin/main`, com versão `0.5.0`, schema v4 e 89 testes aprovados.

As novas regressões verificam OpenAPI JSON, ausência de `/api/docs`, `/redoc` e variantes,
ausência de URLs externas em respostas HTML, execução sem rede, cursores zero/intermediário/
final/acima do final, limite por lote, ordenação, backlog em vários lotes, chegada terminal
durante polling, `Last-Event-ID`, heartbeat sem eventos e rastreamento das chamadas
incrementais feitas pelo SSE.

A suíte resultante possui 95 testes e usa runtime e diretório temporário fora do checkout
sincronizado. Também foram verificados Ruff, formatação, compilação, `pip check`, OpenAPI,
inicialização real em localhost, rotas de documentação, referências a CDN e
`git diff --check`. Nenhum modelo foi baixado e nenhuma inferência real foi executada.

## Limitações preservadas

- não existe visualizador OpenAPI HTML offline;
- SSE ainda usa polling conservador quando não há evento novo;
- a fila e o SSE continuam sem validação com inferência real nesta correção;
- recuperação permanece `at least once` e pode reiniciar a inferência.
