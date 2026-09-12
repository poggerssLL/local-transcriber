# Roadmap

1. Fundação e persistência — concluída.
2. Biblioteca de mídia e exportadores — concluída.
3. Engine Faster Whisper e CLIs — concluída.
4. Fila persistente — concluída.
5. API FastAPI e SSE — concluída.
6. Interface web — concluída.
7. Integração e validação real — concluída.
8. Futuras fases de diarização, Ollama, tempo real e Home Assistant — não iniciadas.

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
host loopback e consumidor único. Não houve download de modelo, uso de CUDA ou serviço
externo. Etapa 8 não foi iniciada.
