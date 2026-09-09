# Regras obrigatórias do repositório

Este arquivo define as regras obrigatórias do Local Transcriber. O contexto detalhado,
o estado e o histórico de decisões ficam nos documentos versionados em `docs/`.

## Ordem de leitura para novas tarefas

1. `docs/PROJECT_CONTRACT.md`
2. `docs/PROJECT_STATE.md`
3. `docs/FOUNDATION.md`
4. `docs/ROADMAP.md`
5. `docs/DECISIONS.md`
6. `docs/KNOWN_ISSUES.md`
7. documento da fase mais recente relevante
8. seções relevantes do `README.md`

## Escopo e fases

- Implemente somente a etapa explicitamente solicitada.
- Não antecipe funcionalidades de fases futuras nem amplie o escopo sem necessidade ou autorização.
- Ao concluir uma fase, atualize a documentação de estado e crie `docs/PHASE_XX_*.md`.

## Documentação obrigatória ao concluir uma etapa

- `docs/PROJECT_STATE.md` representa a fotografia factual e curta do sistema atual.
- `docs/FOUNDATION.md` representa a arquitetura técnica viva e cumulativa atual.
- `docs/PHASE_XX_*.md` preserva historicamente o que foi implementado e validado naquela etapa.
- `docs/ROADMAP.md` registra o progresso confirmado e identifica a próxima etapa.
- `docs/DECISIONS.md` recebe novas decisões arquiteturais e suas consequências.
- `docs/KNOWN_ISSUES.md` remove limitações resolvidas e registra as limitações restantes.
- `README.md` deve permanecer coerente com a experiência atual do usuário.
- Documentação desatualizada conta como etapa incompleta.
- Separe explicitamente resultados de testes com mocks de validações em execução real.
- Não reescreva silenciosamente relatórios históricos de fases concluídas; crie um novo
  registro quando um evento posterior mudar a evidência disponível.
- Uma validação posterior que altere o estado factual, mesmo sem mudança de código, deve
  atualizar `PROJECT_STATE.md`, `FOUNDATION.md` e `KNOWN_ISSUES.md`, criando um relatório
  de validação quando apropriado.
- Nenhum documento pode conter transcrição pessoal, identificadores de runtime, hashes de
  mídia, caminhos pessoais absolutos, credenciais ou outros dados sensíveis.

## Arquitetura obrigatória

- A operação é local e não usa APIs de IA em nuvem.
- Faster Whisper é o primeiro engine de transcrição.
- SQLite armazena apenas metadados; arquivos grandes não entram como BLOB.
- Dados de runtime ficam em `%LOCALAPPDATA%\LocalTranscriber`.
- O futuro servidor será limitado a `127.0.0.1`; não haverá dependência de CDN.
- Modelos nunca serão baixados silenciosamente.
- FastAPI e frontend vanilla entram somente nas fases previstas.
- Diarização, Ollama, microfone ao vivo e Home Assistant estão fora do MVP atual.

## Dados e Git

- Nunca versione áudios, vídeos, bancos SQLite, modelos, transcrições pessoais,
  exportações geradas, caches, temporários, credenciais ou dados pessoais.
- Preserve mudanças não relacionadas e verifique o diff antes do commit.
- Nunca leia nem modifique o repositório irmão `Local AI` nesta tarefa.

## Banco e compatibilidade

- Migrações publicadas são imutáveis; mudanças estruturais exigem nova migração versionada.
- Migrações devem funcionar em banco vazio e existente, com compatibilidade anterior testada.
- Consultas devem permanecer parametrizadas.
- Caminhos armazenados devem permanecer relativos e controlados.

## Modos de trabalho

- Análise ou revisão: somente leitura.
- Diagnóstico: investigue e explique sem corrigir, salvo autorização explícita.
- Implementação: altere somente o escopo autorizado.
- Monitoramento: observe sem realizar mudanças não solicitadas.

## Validação

Após alterações funcionais, execute testes relevantes e depois a suíte completa, Ruff,
verificação de formatação, compilação de sintaxe, `pip check` e `git diff --check`.
Não repita avaliações caras sem motivo técnico.
