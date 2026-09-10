# Estado atual do projeto

> Fotografia verificada em 2026-09-10 após a correção complementar 4B. Atualize este documento ao fim de cada fase;
> não reescreva os relatórios históricos de fases concluídas.

O **Local Transcriber** é uma aplicação local para catalogar gravações e persistir o
ciclo de vida de transcrições. A arquitetura atual é um pacote Python com modelos de
domínio, biblioteca de mídia, engine desacoplado, fila persistente, worker local, CLI,
exportadores determinísticos e persistência de metadados em SQLite; mídias, modelos e
demais dados de runtime ficam fora do repositório.

- Versão do pacote: `0.4.1`.
- Schema SQLite: v4.
- Etapas concluídas: 1, fundação e persistência; 2, biblioteca de mídia e exportadores;
  3, Faster Whisper, gerenciamento explícito de modelos e CLI; 4, fila persistente.
- Funcionalidades disponíveis: configuração de runtime, catálogo de matérias e gravações,
  importação e inspeção de mídia por PyAV, duplicidade exata por SHA-256, pesquisa FTS5,
  persistência do domínio, transcrição síncrona, enfileiramento, worker local sequencial,
  progresso e eventos persistentes, cancelamento, retry, recuperação por lease e exportação
  TXT, Markdown, SRT, WebVTT e JSON; um único entrypoint expõe esses serviços.
- Dependências de runtime validadas: PyAV 16.1.0, Faster Whisper 1.2.1 e CTranslate2 4.8.2.
- Última validação registrada nesta fotografia: 72 testes aprovados.
- Commit funcional verificado da Etapa 3: `b28da0480bee08f533a338001284b36e2a6565bc`.
- Próxima etapa: Etapa 5, API FastAPI e SSE.
- A fila usa estados públicos preservados e fases operacionais separadas. A reivindicação
  é transacional e condicionada ao estado; a posse usa worker e lease renovável.
- Falhas SQLite transitórias do heartbeat têm retry limitado enquanto há margem segura.
  Perda definitiva ativa um sinal cooperativo e usa `LeaseOwnershipLost`, sem classificar
  a tentativa obsoleta como falha do engine nem alterar o job recuperado por outro worker.
- Execução após crash é `at least once`: jobs recuperados podem reiniciar a inferência.
  Somente a lease válida permite persistir progresso ou publicar. Pode haver breve
  sobreposição de computação até o worker obsoleto atingir um ponto cooperativo, mas a
  publicação final é transacional e limitada a uma transcrição por job.
- O cancelamento é cooperativo, o worker padrão processa um job por vez e não há timeout
  total artificial para gravações longas.
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
[validação real 3B](PHASE_03B_REAL_VALIDATION.md),
[segunda validação real 3C](PHASE_03C_SECOND_REAL_VALIDATION.md) e
[Etapa 4](PHASE_04_PERSISTENT_QUEUE.md) e
[correção complementar 4B](PHASE_04B_LEASE_RELIABILITY.md).
