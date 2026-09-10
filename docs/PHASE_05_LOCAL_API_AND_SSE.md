# Etapa 5 — API HTTP local e eventos SSE

## Resultado

A Etapa 5 adiciona uma API FastAPI versionada sob `/api`, integrada à fila persistente e
restrita a `127.0.0.1`. A versão passa a `0.5.0`; o schema SQLite permanece v4 porque os
eventos necessários já eram persistidos pela Etapa 4.

Não foram implementados frontend, worker remoto, diarização, Ollama, microfone ou Home
Assistant. Nenhum áudio pessoal foi transcrito e nenhum modelo foi baixado.

## Contratos HTTP

A API expõe:

- `/api/health`, `/api/version` e `/api/capabilities`;
- criação e listagem de matérias;
- upload, listagem, detalhes, exclusão e mídia de gravações;
- pesquisa FTS5;
- modelos instalados e diagnóstico do runtime;
- criação, listagem, detalhes, cancelamento e retry de jobs;
- transcrições, segmentos e palavras;
- criação, listagem e download de exportações;
- eventos persistidos de jobs por SSE;
- OpenAPI local em `/api/openapi.json` e documentação em `/api/docs`.

As respostas públicas não incluem caminhos físicos, caminhos relativos internos, worker
ID nem lease. Operações de arquivo recebem IDs controlados; nenhum endpoint aceita caminho
de filesystem.

## Upload e streaming

Uploads `multipart/form-data` são processados por spool e copiados em blocos pela mesma
biblioteca da Etapa 2. O fluxo limita bytes, sanitiza o nome e combina validação do
Content-Type declarado com extensão, inspeção do contêiner, presença de áudio e
decodificação por PyAV. Falhas removem temporários pelos mecanismos já existentes.

O endpoint de mídia resolve o arquivo somente a partir da gravação persistida. Ele suporta
resposta completa e uma faixa `bytes`, inclusive ranges abertos e sufixos. Seek recebe
206 e `Content-Range`; ranges inválidos recebem 416. Exportações são entregues por ID de
artefato e nome de download controlado.

## Fila e ciclo de vida

Criar uma transcrição pela API apenas enfileira o job e devolve 202. O lifespan inicia um
worker local sequencial em thread própria; nenhuma inferência prolongada roda na thread da
requisição. O shutdown impede novas reivindicações e aguarda a operação corrente antes de
liberar o recurso.

O comando `local-transcriber serve` aceita somente host `127.0.0.1` e um worker Uvicorn.
Além dessa validação, um lock de processo por runtime recusa um segundo consumidor para o
mesmo banco. Isso protege contra inicialização insegura fora do comando recomendado.

## SSE

`GET /api/jobs/{job_id}/events` usa como `id` a sequência monotônica persistida do job.
`Last-Event-ID` recupera eventos posteriores, heartbeat mantém a conexão ociosa e o stream
termina corretamente após sucesso, falha ou cancelamento.

Eventos são classificados como estado, fase, progresso, falha, cancelamento ou conclusão.
As leituras SQLite abrem e fecham conexões antes de cada espera; nenhuma transação fica
aberta durante o intervalo assíncrono. Uma releitura ao observar estado terminal evita
perder o evento final em uma transição concorrente. Desconectar o cliente encerra somente
o stream e não solicita cancelamento do job.

## Segurança

- bind público é recusado;
- `Host` aceita apenas loopback, localhost e o host interno de testes;
- mutações com `Origin` externo são recusadas e não existe CORS wildcard;
- nomes são sanitizados e Content-Type não é aceito como prova isolada;
- erros não retornam stack trace nem caminho do runtime;
- respostas aplicam `nosniff`, bloqueio de frame, `no-referrer`, CSP restritiva e
  `no-store`;
- o OpenAPI não contém exemplos com dados pessoais;
- download de modelo permanece exclusivamente na CLI com `--confirm`.

## Validação

Primeiro, o baseline `ed05e425537e7249f556fd60b442077136e08f02` foi confirmado limpo,
alinhado a `origin/main`, em versão `0.4.1` e schema v4. A frase de entrada que pedia
confirmar `0.4.0` corresponde ao marco histórico da Etapa 4; a correção 4B publicada já
havia elevado o baseline real a `0.4.1`. Os 72 testes existentes passaram antes da edição.

A Etapa 5 foi validada com TestClient, WAV sintético, engine falso, modelo fictício e
runtime temporário fora do checkout sincronizado. Os cenários novos cobrem contratos e
códigos HTTP, upload válido e inválido, tamanho, traversal no nome, Host, Origin, fila,
cancelamento, retry, SSE inicial, replay, heartbeat, desconexão, Range, exportações,
ausência de caminhos absolutos, lock de consumidor, startup e shutdown.

A validação final aprovou 89 testes e inclui Ruff, formatação, compilação, `pip check`,
schema OpenAPI, inicialização HTTP real em localhost e `git diff --check`. Testes automatizados
com doubles não demonstram qualidade, desempenho ou comportamento do Faster Whisper real;
essa validação continua reservada à Etapa 7.

As versões HTTP exercitadas foram FastAPI 0.116.2, Starlette 0.48.0, Uvicorn 0.52.4,
python-multipart 0.0.32 e HTTPX 0.28.1. O OpenAPI 3.1.0 gerado contém 21 caminhos e 21
schemas e não inclui o caminho físico do runtime.

## Limitações preservadas

- o frontend pertence à Etapa 6;
- shutdown pode aguardar carregamento ou inferência indivisível já iniciada;
- SSE usa consultas periódicas conservadoras e pode ter pequena latência;
- fila, cancelamento e SSE não foram validados com inferência real nesta etapa;
- recuperação continua `at least once` e pode reiniciar a inferência.
