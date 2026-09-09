# Estado atual do projeto

> Fotografia verificada em 2026-09-09. Atualize este documento ao fim de cada fase;
> não reescreva os relatórios históricos de fases concluídas.

O **Local Transcriber** é uma aplicação local para catalogar gravações e persistir o
ciclo de vida de transcrições. A arquitetura atual é um pacote Python com modelos de
domínio, biblioteca de mídia, exportadores determinísticos e persistência de metadados
em SQLite; mídias e demais dados de runtime ficam fora do repositório.

- Versão do pacote: `0.2.0`.
- Schema SQLite: v2.
- Etapas concluídas: 1, fundação e persistência; 2, biblioteca de mídia e exportadores.
- Funcionalidades disponíveis: configuração de runtime, catálogo de matérias e gravações,
  importação e inspeção de mídia por PyAV, duplicidade exata por SHA-256, pesquisa FTS5,
  persistência do domínio e exportação TXT, Markdown, SRT, WebVTT e JSON.
- Dependência principal de runtime: PyAV (`av>=15,<17`). Dependências de desenvolvimento:
  pytest e Ruff.
- Última validação registrada nesta fotografia: 33 testes aprovados.
- Commit verificado nesta fotografia: `aa43366601d22c876655df536a4aba3b65c4145c`
  (`feat: add media library and transcript exporters`).
- Próxima etapa: Etapa 3, engine Faster Whisper e CLIs.
- Fora do MVP atual: diarização, Ollama, microfone ao vivo e Home Assistant.

Referências: [contrato](PROJECT_CONTRACT.md), [roadmap](ROADMAP.md),
[fundação](FOUNDATION.md) e [relatório da Etapa 2](PHASE_02_MEDIA_LIBRARY.md).
