# Estado atual do projeto

> Fotografia verificada em 2026-09-09 após a validação real 3B. Atualize este documento ao fim de cada fase;
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
- Commit funcional verificado da Etapa 3: `b28da0480bee08f533a338001284b36e2a6565bc`.
- Próxima etapa: Etapa 4, fila persistente.
- Um smoke test real posterior à Etapa 3 validou modelo `small` multilíngue, carregamento
  local, inferência CPU `int8`, português, VAD, timestamps por palavra, métricas, cinco
  exportações e recuperação da persistência em novos processos.
- O smoke test real usou áudio de aproximadamente 29,85 segundos, concluiu em cerca de
  48,11 segundos persistidos, com fator de tempo real 1,612 e pico aproximado de
  696,6 MiB; produziu 4 segmentos e 67 palavras.
- A qualidade apresentou alguns erros linguísticos observáveis, mas não havia gabarito
  textual independente e nenhuma taxa de precisão foi calculada.
- A sondagem real encontrou um dispositivo CUDA, mas faltaram `cublas64_12.dll` e
  `cudnn_ops64_9.dll`; CUDA permanece sem validação ponta a ponta.
- Fora do MVP atual: diarização, Ollama, microfone ao vivo e Home Assistant.

Referências: [contrato](PROJECT_CONTRACT.md), [arquitetura viva](FOUNDATION.md),
[roadmap](ROADMAP.md), [Etapa 1](PHASE_01_FOUNDATION.md),
[Etapa 2](PHASE_02_MEDIA_LIBRARY.md), [Etapa 3](PHASE_03_WHISPER_AND_CLI.md) e
[validação real 3B](PHASE_03B_REAL_VALIDATION.md).
