# Estado atual do projeto

> Fotografia verificada em 2026-09-09 após a Etapa 3. Atualize este documento ao fim de cada fase;
> não reescreva os relatórios históricos de fases concluídas.

O **Local Transcriber** é uma aplicação local para catalogar gravações e persistir o
ciclo de vida de transcrições. A arquitetura atual é um pacote Python com modelos de
domínio, biblioteca de mídia, engine desacoplado, CLI, exportadores determinísticos e
persistência de metadados em SQLite; mídias, modelos e demais dados de runtime ficam
fora do repositório.

- Versão do pacote: `0.3.0`.
- Schema SQLite: v3.
- Etapas concluídas: 1, fundação e persistência; 2, biblioteca de mídia e exportadores;
  3, Faster Whisper, gerenciamento explícito de modelos e CLI.
- Funcionalidades disponíveis: configuração de runtime, catálogo de matérias e gravações,
  importação e inspeção de mídia por PyAV, duplicidade exata por SHA-256, pesquisa FTS5,
  persistência do domínio, transcrição síncrona local e exportação TXT, Markdown, SRT,
  WebVTT e JSON; um único entrypoint `local-transcriber` expõe esses serviços.
- Dependências de runtime validadas: PyAV 16.1.0, Faster Whisper 1.2.1 e CTranslate2 4.8.2.
- Última validação registrada nesta fotografia: 48 testes aprovados.
- Baseline da Etapa 3: `4ed553dde925fb63e6c066e5b68ab1dff7b9afc8`.
- Próxima etapa: Etapa 4, fila persistente.
- Modelo Whisper real não foi baixado; inferência CPU e GPU permanecem não validadas
  ponta a ponta até um teste opt-in com modelo local.
- A sondagem real encontrou um dispositivo CUDA, mas faltaram `cublas64_12.dll` e
  `cudnn_ops64_9.dll`; por isso `auto` selecionou CPU `int8`.
- Fora do MVP atual: diarização, Ollama, microfone ao vivo e Home Assistant.

Referências: [contrato](PROJECT_CONTRACT.md), [roadmap](ROADMAP.md),
[fundação](FOUNDATION.md) e [relatório da Etapa 2](PHASE_02_MEDIA_LIBRARY.md).
