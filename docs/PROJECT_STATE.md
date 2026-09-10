# Estado atual do projeto

> Fotografia verificada em 2026-09-10 após as validações reais 3B e 3C. Atualize este documento ao fim de cada fase;
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
- Duas validações reais posteriores à Etapa 3 confirmaram o modelo `small` multilíngue,
  carregamento local, inferência CPU `int8`, português, VAD, timestamps por palavra,
  métricas, cinco exportações e recuperação da persistência em novos processos.
- A primeira execução registrou RTF 1,612. A segunda usou áudio de aproximadamente
  50,97 segundos, produziu 5 segmentos e 78 palavras e registrou cerca de 24,35 segundos
  persistidos, 25,26 segundos de parede, RTF 0,4778 e pico aproximado de 709,9 MiB.
- A segunda execução ficou aproximadamente 2,09 vezes mais rápida que tempo real. Caches,
  aquecimento, conteúdo e duração podem influenciar a diferença entre as duas medições.
- A estrutura temporal e os números principais foram validados, com erros observados em
  vocabulário técnico. Sem gabarito textual independente, nenhuma taxa de precisão foi
  calculada.
- A sondagem real encontrou um dispositivo CUDA, mas faltaram `cublas64_12.dll` e
  `cudnn_ops64_9.dll`; CUDA permanece sem validação ponta a ponta.
- Fora do MVP atual: diarização, Ollama, microfone ao vivo e Home Assistant.

Referências: [contrato](PROJECT_CONTRACT.md), [arquitetura viva](FOUNDATION.md),
[roadmap](ROADMAP.md), [Etapa 1](PHASE_01_FOUNDATION.md),
[Etapa 2](PHASE_02_MEDIA_LIBRARY.md), [Etapa 3](PHASE_03_WHISPER_AND_CLI.md),
[validação real 3B](PHASE_03B_REAL_VALIDATION.md) e
[segunda validação real 3C](PHASE_03C_SECOND_REAL_VALIDATION.md).
