# Correção complementar 6B — confiabilidade assíncrona e SSE

## Escopo

Esta correção complementar da Etapa 6 impede que respostas HTTP antigas ou eventos SSE
repetidos e fora de ordem substituam o contexto mais recente da interface. Ela preserva o
frontend vanilla, a operação offline, a API sob `/api`, o worker local da correção 5C e o
schema SQLite v4. A Etapa 7 não foi iniciada.

Baseline verificado antes das alterações:

- branch `main` alinhada com o remoto no commit `95a741e`;
- versão 0.6.1 e schema v4;
- working tree limpa;
- 107 testes Python aprovados.

## Causas

A interface aguardava cargas globais, pesquisas, leituras e exportações sem associar a
resposta ao contexto que as iniciou. Quando uma operação A terminava depois de uma operação
B, seu resultado ou erro ainda podia atualizar a tela de B.

O `EventSource` também não mantinha no frontend uma última sequência aceita por job. O
replay persistente do backend era correto, mas snapshots HTTP, reconexões e callbacks de um
listener já fechado podiam reapresentar progresso antigo ou aplicar eventos fora de ordem.

## Implementação

O módulo local `async_state.js` adiciona duas primitivas sem dependências externas:

- `LatestRequest` gera tokens monotônicos, cancela a requisição anterior com
  `AbortController` quando aplicável e valida geração e contexto após cada `await`;
- `JobEventTracker` mantém geração do listener e última sequência por job, rejeitando ID
  inválido, zero, repetido, menor, divergente do payload ou pertencente a listener inativo.

`loadAll`, pesquisa e leitura usam escopos independentes. Falhas abortadas ou obsoletas não
alteram o estado de serviço nem criam avisos. A leitura valida a gravação após carregar
transcrições e novamente após carregar exportações.

A criação de exportação captura transcrição, formato e contexto de leitura. O download usa
o ID e o formato retornados para a solicitação original mesmo se a tela mudar; controles,
mensagens e nova listagem de artefatos só são aplicados se a leitura original continuar
ativa.

Cada resposta HTTP de job inclui `last_event_sequence`. A consulta SQLite é parametrizada,
filtra somente o job e usa `MAX(sequence)` sobre o índice já existente. O cursor é lido
antes do snapshot atualizado: uma corrida pode repetir um evento, que o navegador elimina,
mas não pode avançar o cursor além do estado e ocultar um terminal.

O SSE aceita o cursor opcional `after_sequence` sob a rota existente. O backend usa o maior
valor entre ele e `Last-Event-ID`, preservando consumidores anteriores e a reconexão nativa.
O frontend abre cada job no cursor do snapshot, mantém sequências independentes, descarta
callbacks tardios e limpa o rastreador quando um job deixa a coleção conhecida.

Não houve migração: o schema permanece v4.

## Testes com doubles

Uma suíte JavaScript comportamental usa somente o executor nativo do Node durante o
desenvolvimento, sem `npm`, build ou dependência de produção. Promessas e respostas
controladas verificam deterministicamente:

- leitura A lenta seguida de B rápida;
- pesquisa A lenta seguida de B rápida;
- exportação de A concluída depois da abertura de B;
- duas chamadas de carga global concluídas fora de ordem;
- falha obsoleta de uma seleção anterior;
- evento SSE duplicado e evento fora de ordem;
- replay anterior ao cursor do snapshot;
- reconexão a partir da última sequência;
- callback tardio de listener encerrado;
- acompanhamento simultâneo e independente de dois jobs.

Os testes Python verificam ainda o cursor no contrato HTTP, combinação com
`Last-Event-ID`, rejeição de cursor negativo e preservam a cobertura existente de replay,
heartbeat, terminal, fila, lifecycle e contenção 5C. A suíte final aprovou 108 testes
Python; os 11 testes JavaScript comportamentais também foram aprovados.

Uma primeira corrida integral registrou atraso de agendamento no teste de heartbeat com
lease sintética de 150 ms: a margem de segurança encerrou corretamente após duas tentativas,
antes do limite nominal de quatro esperado pela asserção. O arquivo e a operação foram
identificados, o caso passou isoladamente e nenhuma política do worker ou teste histórico
foi alterada para ocultar a ocorrência.

## Validação em navegador real

Um navegador Chromium real acessou o FastAPI em `127.0.0.1` com banco, mídias e
transcrições sintéticos em diretório temporário fora do checkout. Uma resposta de leitura A
e uma pesquisa A foram atrasadas de forma controlada; B foi iniciada logo depois e
permaneceu visível mesmo após A terminar. O servidor local foi interrompido e reiniciado no
mesmo runtime, e a interface anunciou desconexão e depois reconexão SSE sem erro no console.

Nenhuma inferência foi executada, nenhum modelo foi baixado e nenhum áudio pessoal foi
usado. Os arquivos temporários de validação não fazem parte do produto nem do Git.

## Validações não executadas

Não foram executadas inferência Faster Whisper, carga longa, download de modelo, CUDA,
qualidade acústica nem transcrição de áudio pessoal. Esses cenários não são necessários
para a correção de concorrência do navegador e continuam fora desta evidência; a validação
real abrangente permanece atribuída à Etapa 7, que não foi iniciada.

## Observação sobre temporários no Windows

Uma execução direcionada que removeu a configuração de `basetemp` encontrou
`PermissionError` ao tentar enumerar o diretório global antigo do pytest fora do checkout.
ACL e listagem desse diretório também foram negadas e não havia processo Python ou pytest
concorrente; portanto, a ocorrência não envolveu um handle do produto nem um temporário no
repositório sincronizado. As validações subsequentes usaram diretórios temporários únicos
fora do checkout, sem alterar ACL, configuração global do pytest ou OneDrive.

## Verificações finais

- 7 testes Python direcionados da 6B e da interface;
- 11 testes JavaScript comportamentais;
- 6 regressões de contenção SQLite da 5C;
- 51 testes combinados de fila, API e contenção;
- suíte integral com 108 testes Python;
- Ruff sem violações e 45 arquivos Python formatados;
- compilação de `src` e `tests`;
- sintaxe dos quatro módulos JavaScript;
- `pip check` sem dependências quebradas;
- OpenAPI 0.6.2 com cursor SSE e rotas de documentação HTML ausentes;
- inspeção real em localhost e `git diff --check`.

## Resultado

- versão: 0.6.2;
- schema SQLite: v4;
- frontend vanilla, offline e sem build obrigatório;
- correção 5C e retries SQLite limitados preservados;
- CSP, DOM seguro, loopback, fila obrigatória e downloads explícitos de modelo preservados;
- Etapa 7 não iniciada.
