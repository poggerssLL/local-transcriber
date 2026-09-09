# Decisões arquiteturais

Este arquivo registra por que decisões foram tomadas, para que novas tarefas não
revertam escolhas anteriores sem compreender suas consequências.

## ADR-001 — Operação local

- Data: 2026-09-09
- Status: aceita
- Decisão: operar localmente, sem APIs de IA em nuvem.
- Motivo: preservar privacidade e independência de serviços externos.
- Consequências: processamento e dados permanecem no computador do usuário.

## ADR-002 — Primeiro engine

- Data: 2026-09-09
- Status: aceita
- Decisão: usar Faster Whisper como primeiro engine de transcrição.
- Motivo: é o engine definido pelo contrato para a primeira integração real.
- Consequências: a Etapa 3 deve integrá-lo sem antecipar engines posteriores.

## ADR-003 — Papel do SQLite

- Data: 2026-09-09
- Status: aceita
- Decisão: armazenar no SQLite somente metadados, nunca arquivos grandes como BLOB.
- Motivo: separar o catálogo dos arquivos gerenciados.
- Consequências: o banco referencia caminhos relativos de arquivos no runtime.

## ADR-004 — Runtime fora do repositório

- Data: 2026-09-09
- Status: aceita
- Decisão: manter runtime em `%LOCALAPPDATA%\LocalTranscriber`.
- Motivo: impedir que dados pessoais e artefatos operacionais entrem no código-fonte.
- Consequências: testes e desenvolvimento podem usar um diretório absoluto configurado.

## ADR-005 — Inspeção com PyAV

- Data: 2026-09-09
- Status: aceita
- Decisão: usar PyAV e as bibliotecas FFmpeg de sua distribuição para inspecionar e decodificar mídia.
- Motivo: validar contêiner, stream de áudio e decodificação real.
- Consequências: a disponibilidade de codecs depende do wheel do PyAV instalado.

## ADR-006 — Importação progressiva

- Data: 2026-09-09
- Status: aceita
- Decisão: copiar mídia em blocos para um temporário antes da movimentação atômica.
- Motivo: limitar o uso de memória e validar o arquivo antes de publicá-lo no runtime.
- Consequências: falhas normais limpam temporários e compensam a persistência parcial.

## ADR-007 — Duplicidade exata

- Data: 2026-09-09
- Status: aceita
- Decisão: detectar duplicidade pelo SHA-256 dos bytes.
- Motivo: oferecer uma identidade determinística do conteúdo importado.
- Consequências: arquivos perceptualmente iguais com bytes diferentes não são duplicados.

## ADR-008 — Caminhos relativos controlados

- Data: 2026-09-09
- Status: aceita
- Decisão: persistir apenas caminhos relativos normalizados e confinados ao runtime.
- Motivo: evitar path traversal e não expor caminhos físicos do sistema.
- Consequências: caminhos absolutos, prefixos de unidade, barras invertidas e `..` são rejeitados.

## ADR-009 — Migrações incrementais

- Data: 2026-09-09
- Status: aceita
- Decisão: manter migrações publicadas imutáveis e adicionar versões incrementais.
- Motivo: atualizar bancos existentes sem reescrever seu histórico.
- Consequências: cada mudança estrutural exige nova migração para banco vazio e existente.

## ADR-010 — Pesquisa com FTS5

- Data: 2026-09-09
- Status: aceita
- Decisão: usar SQLite FTS5 para pesquisa textual.
- Motivo: pesquisar título, matéria e transcrição localmente com suporte a Unicode.
- Consequências: triggers mantêm o índice sincronizado; ranking e filtros avançados não existem ainda.

## ADR-011 — Exportadores determinísticos

- Data: 2026-09-09
- Status: aceita
- Decisão: produzir exportações determinísticas em UTF-8 com quebras `LF`.
- Motivo: garantir resultados estáveis e testáveis entre execuções.
- Consequências: formatação, arredondamento de timestamps e escaping seguem regras explícitas.

## ADR-012 — API e interface em fases futuras

- Data: 2026-09-09
- Status: aceita
- Decisão: implementar FastAPI e frontend vanilla somente nas fases previstas.
- Motivo: manter a evolução por etapas definida no roadmap.
- Consequências: a versão atual não oferece API, SSE nem interface web e não usa CDN.

## ADR-013 — Downloads explícitos

- Data: 2026-09-09
- Status: aceita
- Decisão: nunca baixar modelos silenciosamente.
- Motivo: manter consumo de rede e armazenamento sob controle do usuário.
- Consequências: qualquer download futuro exigirá ação explícita.

## ADR-014 — Separação do Local AI

- Data: 2026-09-09
- Status: aceita
- Decisão: manter o Local Transcriber completamente separado do repositório `Local AI`.
- Motivo: são projetos e históricos Git distintos.
- Consequências: tarefas deste projeto não usam, modificam nem versionam o repositório irmão.

## ADR-015 — Abstração do engine

- Data: 2026-09-09
- Status: aceita
- Decisão: expor transcrição por um `TranscriptionEngine` estruturalmente tipado e manter
  Faster Whisper em um adaptador.
- Motivo: separar o domínio do backend local e permitir um executor remoto futuro.
- Consequências: a CLI usa `TranscriptionService`; detalhes do Faster Whisper não entram
  na persistência nem na biblioteca de mídia.

## ADR-016 — Modelos explícitos e locais

- Data: 2026-09-09
- Status: aceita
- Decisão: instalar modelos somente pelo comando `models download MODEL --confirm`, sob
  `RuntimePaths.models`, e transcrever apenas com `local_files_only=True`.
- Motivo: impedir downloads silenciosos e manter arquivos grandes fora do Git.
- Consequências: um modelo ausente gera erro acionável antes da criação do job.

## ADR-017 — Perfis de execução conservadores

- Data: 2026-09-09
- Status: aceita
- Decisão: CPU usa `int8`; CUDA usa `int8_float16`; `auto` só escolhe CUDA após sondar
  CTranslate2 e as bibliotecas CUDA/cuDNN exigidas.
- Motivo: a presença da GPU não comprova que o runtime de inferência está completo.
- Consequências: `auto` relata o motivo do fallback; CUDA explícita nunca faz fallback.

## ADR-018 — Publicação transacional

- Data: 2026-09-09
- Status: aceita
- Decisão: consumir integralmente os segmentos lazy antes de publicar e inserir a
  transcrição junto da transição do job para `succeeded` na mesma transação SQLite.
- Motivo: impedir que falhas publiquem resultados parciais como concluídos.
- Consequências: falhas deixam o job como `failed`, com mensagem técnica sanitizada e sem
  uma transcrição parcial persistida.

## ADR-019 — CLI com argparse

- Data: 2026-09-09
- Status: aceita
- Decisão: usar um único entrypoint `local-transcriber`, implementado com `argparse`.
- Motivo: oferecer operação completa sem adicionar outro framework de CLI.
- Consequências: comandos chamam repositório, biblioteca, exportador e serviço existentes.
