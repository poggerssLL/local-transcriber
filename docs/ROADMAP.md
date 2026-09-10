# Roadmap

1. Fundação e persistência — concluída.
2. Biblioteca de mídia e exportadores — concluída.
3. Engine Faster Whisper e CLIs — concluída.
4. Fila persistente — concluída.
5. API FastAPI e SSE — concluída.
6. Interface web — concluída.
7. Integração e validação real — próxima etapa.
8. Futuras fases de diarização, Ollama, tempo real e Home Assistant.

Após a Etapa 3, duas validações reais antecipadas confirmaram o fluxo CPU `int8` com
modelo local, exportações e persistência. Os RTFs observados foram 1,612 e 0,4778, mas
duas amostras curtas não permitem garantir desempenho em uma gravação de 1h40. A projeção
de aproximadamente 47,8 minutos derivada do segundo RTF não é uma medição real de carga
longa. Isso não conclui a Etapa 7, que continua responsável pela integração e validação
abrangente do MVP.

Cada fase deve respeitar os invariantes de `PROJECT_CONTRACT.md` e incluir testes
proporcionais ao risco antes de avançar.

A Etapa 4 confirmou deterministicamente fila SQLite, worker local sequencial, progresso,
cancelamento, retry e recuperação por lease. Nenhuma inferência real foi executada nessa
etapa; a validação real abrangente permanece na Etapa 7.

A Etapa 5 expôs os serviços locais sob `/api`, com upload progressivo, fila obrigatória,
streaming controlado de mídia e exportações, SSE persistente com replay e worker integrado
ao ciclo de vida. A validação usou TestClient, mídia sintética, engine falso e runtime
temporário; não executou inferência real nem baixou modelos.

A Etapa 6 adicionou a interface web vanilla servida pela própria aplicação, sem build,
CDN ou serviço externo. Painel, matérias, biblioteca, configuração de transcrição, fila,
leitura sincronizada, exportações e modelos usam a API da mesma origem. Testes automatizados
e inspeção real no navegador usaram somente mídia, jobs e transcrições sintéticos; a
validação real abrangente permanece na Etapa 7.
