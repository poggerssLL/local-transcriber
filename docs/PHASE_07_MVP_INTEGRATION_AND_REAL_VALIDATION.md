# Etapa 7 — Integração e validação real do MVP

> Registro histórico da conclusão da Etapa 7 em 2026-09-11. Não contém caminhos, hashes,
> identificadores de runtime ou conteúdo da gravação usada na validação.

## Escopo concluído

A Etapa 7 validou o caminho feliz integrado do MVP local e adicionou um iniciador
supervisionado para o uso cotidiano no Windows. Não foram iniciadas funcionalidades da
Etapa 8, diarização, Ollama, microfone, Home Assistant, worker remoto, frontend adicional
ou download de modelos.

O script `scripts/start-local-transcriber.ps1`:

- verifica a existência do entrypoint em `.venv`;
- verifica se a porta local solicitada já está em escuta;
- chama `local-transcriber serve` em primeiro plano com `127.0.0.1` e um worker;
- mantém `Ctrl+C` como encerramento supervisionado;
- não altera políticas globais, runtime, OneDrive, dependências ou modelos.

O schema SQLite permaneceu v4. A correção 5C de polling ocioso sem escrita e a correção
6B de estado assíncrono monotônico foram preservadas.

## Execução real controlada

Foi usada uma amostra curta controlada e autorizada no runtime local. O conteúdo, título,
caminho, hashes e identificadores não são registrados neste documento.

| Medida | Resultado |
| --- | --- |
| Engine | Faster Whisper local |
| Modelo e perfil | `small`, CPU `int8` |
| Idioma solicitado / detectado | automático / português |
| VAD e timestamps por palavra | habilitados |
| Duração da mídia | 18,23 s |
| Processamento persistido | 14,88 s |
| RTF aproximado | 0,816 |
| Segmentos / palavras | 3 / 41 |
| Tentativas | 1 |
| Eventos persistidos | 10, incluindo conclusão |

O job foi criado pela API e consumido pelo worker integrado; nenhuma inferência ocorreu na
thread da requisição. O modelo já estava instalado e não houve acesso de rede ou download.

Uma amostragem de memória foi iniciada tarde demais para medir pico. Após o término, o
processo observado tinha cerca de 132,8 MiB de working set e 2.394,9 MiB de memória privada.
Esse valor é apenas uma referência pós-execução, não um benchmark nem pico de RAM.

## Fluxos reais verificados

- importação pela interface local para o runtime controlado;
- criação de job sob `/api`, worker local sequencial e conclusão no SQLite;
- reconstrução da fila, painel, biblioteca e leitura em nova aba do navegador;
- replay SSE: o cursor final era monotônico e `Last-Event-ID` imediatamente anterior
  retornou apenas o evento terminal;
- busca FTS5 retornou a gravação esperada;
- player recebeu mídia por endpoint controlado com `Range`, resposta `206` e
  `Accept-Ranges: bytes`; um marcador temporal foi acionado pela interface;
- leitura mostrou idioma, métricas, segmentos e probabilidades disponíveis;
- TXT, Markdown, SRT, WebVTT e JSON foram gerados pela interface e seus downloads locais
  controlados responderam com sucesso.

Não foi executado cancelamento ou retry reais nesta gravação, pois provocariam uma segunda
inferência e poderiam gerar resultado duplicado apenas para teste. Esses cenários continuam
cobertos de modo determinístico por engine falso. Não se forçou o encerramento do serviço
existente porque ele não estava anexado a uma sessão controlável.

Em observação operacional posterior, um reinício do computador durante um job em andamento
foi seguido de nova inicialização do serviço local; a fila recuperou o estado persistido e
o job concluiu. Essa evidência confirma recuperação ponta a ponta, mas não mede latência de
lease, não caracteriza cancelamento e não é benchmark de modelo.

## Evidência automatizada e inspeção

Os testes automatizados permanecem independentes de modelo, GPU e rede: usam mídia,
runtime e engine falsos temporários. Eles não medem qualidade de transcrição nem substituem
a execução real acima. A inspeção do navegador foi feita somente contra `127.0.0.1`, sem
CDN, telemetria ou serviço externo.

O iniciador foi executado em runtime temporário fora do checkout: saúde e OpenAPI
confirmaram versão 0.7.0, schema v4 e worker ativo; `Ctrl+C` completou o shutdown do
lifespan e liberou a porta. As validações finais registradas após a alteração incluem suíte
Python, testes JavaScript, Ruff, formatação, compilação Python, sintaxe JavaScript, `pip
check`, OpenAPI, ciclo do iniciador, `git diff --check` e revisão de arquivos rastreados.

### Variação temporal observada na validação

Nas duas primeiras execuções combinadas dos testes direcionados, uma asserção do heartbeat
de lease com janela de 0,15 s observou menos tentativas que o limite esperado. A execução
isolada dessa asserção, o conjunto completo de cinco testes de heartbeat e a suíte integral
posterior passaram. Não houve `PermissionError` nem evidência de regressão de produto, e a
correção 5C não foi modificada: a variação foi tratada como sensibilidade de agendamento do
teste com tempo real, não como motivo para esconder ou alterar o comportamento da fila.

## Limites preservados

- amostras curtas não caracterizam carga longa ou precisão textual;
- não há gabarito independente, portanto não foi calculada taxa de precisão;
- CUDA não foi preparado nem validado ponta a ponta;
- cancelamento, retry, lease expirada e recuperação com inferência real exigem cenário
  próprio e autorização operacional;
- o suporte de reprodução continua dependente dos codecs do navegador;
- a próxima etapa não foi iniciada.
