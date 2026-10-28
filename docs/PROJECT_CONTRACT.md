# Contrato persistente do projeto

Estes invariantes orientam todas as fases do **Local Transcriber**:

- O produto funciona localmente e não depende de serviços externos para sua operação básica.
- Nenhuma API de inteligência artificial em nuvem será usada por padrão; a síntese em nuvem via ChatGPT é uma opção estritamente opt-in autorizada pelo usuário.
- `faster-whisper` será o primeiro motor de transcrição.
- FastAPI e um frontend vanilla serão implementados em fases posteriores.
- SQLite armazena metadados; arquivos grandes não são armazenados como BLOB.
- Dados de runtime permanecem fora do Git, por padrão em `%LOCALAPPDATA%\LocalTranscriber`.
- O servidor futuro ficará restrito a `127.0.0.1`.
- Nenhum recurso será carregado de CDN.
- Nenhum modelo será baixado silenciosamente; downloads exigirão ação explícita.
- O repositório `Local AI` não será alterado por este projeto.
- Diarização, microfone ao vivo e Home Assistant não fazem parte do MVP; a sumarização tem o Ollama local em localhost como padrão, com suporte opt-in a ChatGPT via plano do usuário.
- Uploads, modelos, bancos, áudios, vídeos e transcrições pessoais nunca entram no Git.
