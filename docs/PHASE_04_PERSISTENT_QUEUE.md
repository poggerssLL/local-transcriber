# Etapa 4 — fila persistente de transcrição

## Resultado

A Etapa 4 adiciona uma fila SQLite e um worker local sequencial. Enfileirar apenas valida
as referências e persiste o trabalho; a inferência ocorre depois, quando um worker o
reivindica. A versão passa a ser `0.4.0` e o schema SQLite passa a ser v4.

FastAPI, SSE HTTP, interface web, worker remoto e demais fases futuras não foram
implementados.

## Máquina de estados

Os estados públicos foram preservados:

- `pending`: aguardando uma tentativa;
- `running`: reivindicado por um worker;
- `succeeded`: transcrição completa publicada;
- `failed`: tentativa encerrada com erro sanitizado;
- `cancelled`: cancelamento concluído.

A fase operacional é persistida separadamente:

```text
queued → claiming → loading_model → transcribing → finalizing → completed
                         └────────────→ cancelling ────────────→ completed
```

Retry de `failed` ou `cancelled` retorna o job a `pending`/`queued`, desde que o limite
persistido de tentativas ainda não tenha sido atingido.

## Migração v4

A migração acrescenta aos jobs:

- fase e percentual;
- segundos processados e duração total;
- configurações solicitadas;
- quantidade e limite de tentativas;
- timestamps de início, término e solicitação de cancelamento;
- identificador do worker e expiração da lease.

A tabela `transcription_job_events` persiste eventos com sequência monotônica por job,
fase, mensagem, segmentos concluídos, progresso temporal, duração total, percentual e
timestamp. Bancos vazios e bancos provenientes de v1, v2 e v3 migram até v4 sem alterar
as migrações publicadas.

## Reivindicação, concorrência e leases

O worker usa `BEGIN IMMEDIATE`, seleciona o próximo job elegível e aplica compare-and-set
condicionado a `pending`. A posse fica vinculada ao identificador do worker e à lease; as
atualizações de progresso e a publicação final rejeitam um worker que perdeu a posse.

A concorrência padrão é 1. Cada worker executa um único job por vez e não conserva vários
modelos carregados. Uma rotina de heartbeat renova a lease durante carregamento e
inferência. A duração do áudio não recebe timeout total artificial.

## Recuperação e idempotência

Ao procurar trabalho, o worker recupera leases expiradas de forma determinística:

- cancelamento já solicitado termina como `cancelled`;
- limite de tentativas atingido termina como `failed`;
- caso contrário o job volta a `pending`/`queued` e pode ser reivindicado novamente.

O Faster Whisper atual não retoma do ponto acústico exato. Portanto, uma tentativa
recuperada reinicia a inferência desde o começo. A semântica é **at least once** para a
execução, não “exactly once”. A publicação final continua transacional, a chave única por
job permite no máximo uma transcrição e uma repetição da publicação já concluída devolve
o resultado existente.

Segmentos parciais permanecem em memória e eventos de progresso; nunca são publicados
como transcrição concluída.

## Cancelamento e progresso

Cancelamento de job pendente é imediato e persistente. Em execução, a solicitação muda a
fase para `cancelling` e é verificada cooperativamente durante o consumo lazy dos
segmentos, antes da finalização e durante a recuperação.

O cancelamento pode não ser instantâneo enquanto o modelo está sendo carregado ou durante
uma operação indivisível do engine. `KeyboardInterrupt` e `SystemExit` encerram o loop do
worker sem serem registrados como falhas normais; a lease permite recuperação posterior.

Eventos de progresso informam fase, mensagem, segmentos concluídos, segundos processados,
duração total e percentual quando calculável. O percentual fica abaixo de 100% até a
publicação transacional final. Falhas em callbacks externos são tratadas como falhas de
observação e não mudam um job já persistido como `succeeded`.

## CLI

Foram adicionados:

```powershell
local-transcriber jobs enqueue RECORDING_ID
local-transcriber jobs list
local-transcriber jobs show JOB_ID
local-transcriber jobs cancel JOB_ID
local-transcriber jobs retry JOB_ID
local-transcriber worker run
local-transcriber worker run --once
```

`jobs enqueue` aceita as opções de modelo, perfil, idioma, beam size, timestamps, VAD e
limite de tentativas. O comando `transcribe` preserva a execução síncrona da Etapa 3.

## Validação determinística

A suíte de 63 testes, sem rede, GPU ou modelo real, cobre:

- migração de bancos vazios e provenientes de v1, v2 e v3;
- reivindicação atômica e dois workers concorrentes;
- lease, heartbeat, expiração e recuperação após crash;
- cancelamento pendente, em execução e durante recuperação;
- retry e limite de tentativas;
- eventos persistentes, ordenados e progresso por tempo;
- áudio simulado de duas horas sem timeout total;
- erros do engine e de persistência sem resultado parcial;
- publicação idempotente e no máximo uma transcrição por job;
- callback defeituoso depois do sucesso;
- `KeyboardInterrupt` no worker;
- comandos da CLI e regressão integral das etapas anteriores.

## Não validado em inferência real

Nenhum áudio pessoal, modelo real ou runtime operacional foi lido nesta etapa. Não foram
medidos desempenho, latência de cancelamento, recuperação durante Faster Whisper real nem
comportamento prolongado da lease sob carga real. Essas verificações continuam
pertencendo à Etapa 7.

## Limitações

- recuperação pode repetir a inferência completa;
- cancelamento depende de pontos cooperativos;
- uma falha abrupta permanece visível como `running` até a expiração da lease;
- o worker é local e sequencial, sem coordenação remota;
- eventos representam progresso persistido, não checkpoints acústicos retomáveis;
- não há API, SSE HTTP nem interface web.
