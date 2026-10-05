# Roadmap

1. Fundação e persistência — concluída.
2. Biblioteca de mídia e exportadores — concluída.
3. Engine Faster Whisper e CLIs — concluída.
4. Fila persistente — concluída.
5. API FastAPI e SSE — concluída.
6. Interface web — concluída.
7. Integração e validação real — concluída.
7B. Aceleração CUDA local e resiliência operacional da fila — concluída.
8. Resumo Estruturado com Ollama local e integração web completa — concluída.
8B. Manutenção de baseline, validação estática e consolidação factual — concluída.
8C. Estilo e separação dos testes de retries/expiração — concluída; publicação conjunta com Etapa 8/8B autorizada em 2026-10-05.
9. Futuras fases de diarização, tempo real contínuo e Home Assistant — não iniciadas.

Após a Etapa 3, duas validações reais antecipadas confirmaram o fluxo CPU `int8` com
modelo local, exportações e persistência. Os RTFs observados foram 1,612 e 0,4778, mas
duas amostras curtas não permitem garantir desempenho em uma gravação de 1h40. A projeção
de aproximadamente 47,8 minutos derivada do segundo RTF não é uma medição real de carga
longa. A Etapa 7 adicionou uma terceira execução real curta e concluiu o caminho feliz
integrado, sem transformar essa evidência limitada em uma caracterização de carga longa.

Cada fase deve respeitar os invariantes de `PROJECT_CONTRACT.md` e incluir testes
proporcionais ao risco antes de avançar.

A Etapa 4 confirmou deterministicamente fila SQLite, worker local sequencial, progresso,
cancelamento, retry e recuperação por lease. A Etapa 7 confirmou uma execução real pela
fila, mas cancelamento, retry e recuperação continuam cobertos de modo determinístico por
engine falso até uma validação operacional específica.

A Etapa 5 expôs os serviços locais sob `/api`, com upload progressivo, fila obrigatória,
streaming controlado de mídia e exportações, SSE persistente com replay e worker integrado
ao ciclo de vida. A validação usou TestClient, mídia sintética, engine falso e runtime
temporário; não executou inferência real nem baixou modelos.

A Etapa 6 adicionou a interface web vanilla servida pela própria aplicação, sem build,
CDN ou serviço externo. Painel, matérias, biblioteca, configuração de transcrição, fila,
leitura sincronizada, exportações e modelos usam a API da mesma origem. Testes automatizados
e inspeção real no navegador usaram somente mídia, jobs e transcrições sintéticos; a Etapa
7 complementou essa evidência com uma amostra curta controlada, sem alterar a interface.

A correção complementar 5C removeu a contenção de escrita causada pelo polling do worker
com fila vazia. A pré-consulta é somente leitura, enquanto recuperação e reivindicação
continuam atômicas sob `BEGIN IMMEDIATE`; falhas SQLite transitórias recebem retry limitado.
A correção permanece preservada na Etapa 7.

A correção complementar 6B tornou o estado assíncrono do frontend monotônico. Cargas,
pesquisas, leituras, exportações e erros obsoletos não substituem mais o contexto recente;
o SSE usa cursor inicial do snapshot e sequência independente por job para rejeitar replay,
duplicação, regressão e callbacks de listeners encerrados. O schema continua v4, a operação
continua offline e foi preservada na Etapa 7.

A Etapa 7 concluiu a validação integrada do caminho feliz com mídia local controlada:
importação, FastAPI, fila, Faster Whisper em CPU `int8`, SSE persistente, FTS5, leitura,
Range e TXT, Markdown, SRT, WebVTT e JSON. O iniciador supervisionado do Windows mantém
host loopback e consumidor único. A 7B validou também CUDA `int8_float16` em uma amostra
curta após instalação explícita de CUDA 12/cuBLAS 12/cuDNN 9, sem download de modelo,
serviço externo ou alteração global de `PATH`. Ela bloqueou ainda a exclusão de gravação
enquanto há job ativo, evitando a interrupção do worker observada operacionalmente.

A Etapa 8 integrou a síntese pedagógica automatizada via Ollama local (`qwen2.5:3b`)
utilizando Map-Reduce temporal por blocos de 20 minutos, gerando artefatos sidecar
`transcript.resumo.md` e `transcript.resumo.json`. A interface web foi expandida com
painel interativo de leitura (tese central, resumo executivo, roteiro de podcast com cópia,
glossário com sincronização de timestamps no player de mídia, flashcards com revelação
ativa e downloads diretos de resumo). Foram adicionados 19 testes automatizados com mocks
(totalizando 134 testes aprovados no repositório). A política de privacidade, execução offline
e imutabilidade dos arquivos originais permanece integralmente respeitada.

A Etapa 8B realizou a manutenção e consolidação factual da baseline após a Etapa 8.
A suíte completa atingiu 141 testes Python aprovados (26 testes no módulo e rotas de resumo),
sintaxe JavaScript e compilação Python íntegras, dependências validadas pelo `pip check` e
hashes SHA-256 preservados nos oito arquivos pré-existentes da etapa. Foram registradas
as 10 advertências Ruff E501 e diferenças de formatação confinadas aos arquivos pré-existentes,
bem como a sensibilidade transitória intermitente observada no teste de retries de heartbeat
em `tests/test_queue.py` (falha na primeira execução e retries efetivos com causa desconhecida).
As contradições documentais sobre a presença do Ollama local no escopo foram saneadas sem
relaxamento de privacidade ou segurança. Etapa 9 não foi iniciada.

## Manutenção 8C

142 testes aprovados, Ruff global e formatação aprovados. Clock controlado no
teste de retries e regressão separada da margem expirada; nenhuma alteração
no heartbeat de produção ou no schema. A dívida de estilo da 8B foi resolvida;
a causa histórica da falha intermitente não foi inferida. Aviso pip de distribuição
inválida permanece, sem repair/install. Etapas futuras não iniciadas.
[Relatório 8C](PHASE_08C_STYLE_AND_HEARTBEAT_TESTS_2026-10-05.md).
