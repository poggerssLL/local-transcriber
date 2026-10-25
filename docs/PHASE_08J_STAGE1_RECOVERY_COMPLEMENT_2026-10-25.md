# Fase 8J — Complemento posterior de recuperação da Etapa 1 / Etapa 0

Data: 2026-10-25. Baseline: `main`, HEAD `eb6415e11a15308a5729660c2b9044b11f6bea4a`,
upstream `origin/main`. Pacote `0.7.1`; SQLite core v4 preservado.
Estado da entrega: implementação local pronta para revisão independente do coordenador.
Este relatório não aprova o gate e não autoriza Etapa 2, commit, push ou publicação.

## Revisão posterior e escopo

O relatório histórico `PHASE_08J_STAGE1_HARDENING_2026-10-25.md` declarou fechamento
do gate e cobertura de concorrência/ctypes. A revisão posterior identificou falhas
restantes no protocolo de recuperação e ausência de testes específicos dessas garantias.
Esse relatório anterior permanece intacto; as evidências atuais são as registradas aqui.

O complemento corrige exclusivamente a Etapa 1 remota, também chamada Etapa 0 de
hardening. Não implementa seleção de matérias, rate limiting, upload resumable ou UI.

## Correções e evidência observável

| Achado | Comportamento implementado | Evidência dedicada |
| --- | --- | --- |
| Erros de consulta/off podiam apagar recuperação em stop | Erro propaga antes de limpar; após off, outra consulta comprova ausência do mapping | `test_stop_network_failure_preserves_and_recovers` cobre consulta, off, off sem efeito e consulta posterior indisponível, com retry seguro |
| Serve era ativado antes da persistência | Journal em fases antes dos efeitos; ativação incerta aciona reconciliação seletiva; rollback incompleto conserva prova | `test_persistence_failures_at_each_phase`, `test_activation_error_rolls_back_only_proven_mapping`, `test_activation_rollback_failure_retains_journal`, `test_active_write_and_rollback_failure_keep_previous_intent`, `test_fsync_failure_prevents_process_and_network_effects` |
| Primeiro Proxy não provava posse integral da porta | Exige TCP HTTPS exclusivo, host DNS da sessão, única rota raiz e único Proxy exato; desconhecido/static/TCP/services/múltiplos hosts ou handlers bloqueiam | `test_start_rejects_nonexclusive_or_unknown_serve`, `test_stop_never_deletes_third_party_handlers`, `test_uncertain_activation_with_third_party_preserves_all_evidence`, `test_unrelated_port_survives_start_and_stop` |
| Limpeza stale ignorava falhas e estado corrompido equivalia a ausência | Stale usa a mesma reconciliação de stop; corrupção e journal incompleto bloqueiam sem apagar evidência | `test_stale_start_preserves_recovery_on_network_failure`, `test_corrupt_session_blocks_mutations_and_reports_status`, `test_prepared_journal_requires_manual_reconciliation`, `test_recovery_from_interrupted_start` |
| Faltavam testes Win32/concorrência específicos | Testes próprios de passagem de HANDLE alto e exclusão real no SO | `test_win32_ctypes_signatures_preserve_64bit_handle`, `test_concurrent_lifecycle_operations_are_excluded` |

### Journal e recuperação

1. `prepared`: grava intenção e marcador antes de criar o subprocesso. Falha inicial de
   persistência não cria processo nem ativa Serve; temporário parcial permanece como evidência.
2. `gateway`: grava PID e tempo de criação antes de readiness/ativação. Falhas anteriores
   à ativação revertem o subprocesso pelo objeto Popen original, sem kill de PID não provado.
3. `activating`: persistido antes do comando Serve. O comando pode falhar após produzir
   efeito; a recuperação consulta a configuração inteira e só executa off se ela for própria.
4. `active`: só persistido após conferir o resultado da ativação. Se essa escrita falhar,
   o journal anterior `activating` continua disponível; rollback que falha não o apaga.

Cada snapshot usa temporário exclusivo, flush/fsync e replace. Temporários de escrita
que falha são preservados até limpeza comprovada. `stop` reconcilia journals completos
mesmo após reinício do controlador: consulta, off seletivo quando necessário, consulta
posterior, término comprovado e só então limpeza. Falhas conservam journal e retornam erro.
`status` permanece observacional, inclusive diante de corrupção/estado incompleto.

### Posse de Serve

Não se deduz porta livre por ausência de Proxy. Estado vazio válido é distinguido de
stdout vazio, JSON não objeto e estrutura inválida. A configuração da porta selecionada
precisa ser integralmente conhecida; hosts/rotas adicionais bloqueiam mesmo quando o
primeiro Proxy aponta ao gateway. Não há normalização nem remoção de serviços terceiros.
Portas distintas continuam preservadas. É feita nova inspeção imediatamente antes da
ativação e conferência posterior; nenhum comando global reset/down é introduzido.

## Validações executadas

Ambiente existente `.venv`, Python 3.13 de 64 bits, sem instalar dependências.
Basetemp, logs, inventário/hashes prévios, cópias anteriores e patch consolidado de revisão
foram mantidos fora do checkout. Não há transcrições, mídia, credenciais, IDs de runtime
ou caminhos pessoais neste relatório.

| Verificação final | Resultado |
| --- | --- |
| `pytest tests/test_remote_session.py tests/test_cli.py tests/test_remote_gateway.py -rA` | 194 aprovados em 29,03 s: 101 sessão, 8 CLI, 85 gateway |
| `pytest -rA` — suíte completa | 384 aprovados em 62,94 s |
| `ruff check .` | Aprovado |
| `ruff format --check .` | 133 arquivos formatados, aprovado |
| `compileall` em `src` e `tests` com `sys.pycache_prefix` em temporário externo | Aprovado |
| `pip check` | Nenhuma dependência quebrada |
| `git diff --check` | Aprovado |

As execuções pytest usaram `--basetemp` exclusivo fora do checkout e `-p no:cacheprovider`.
A primeira tentativa da nova coleta encontrou helper definido abaixo de um parametrizador;
foi corrigida antes das execuções finais. A primeira invocação de compilação com prefixo
via ambiente falhou com `OSError: Invalid argument`; a execução corrigida definiu
`sys.pycache_prefix` no processo Python e compilou ambos os diretórios com sucesso.
Não foi identificada falha preexistente nos checks finais.

Tailscale, processos de gateway e falhas de disco/rede são simulados. O teste Win32 passa
um HANDLE maior que 32 bits por callbacks C de ctypes e verifica assinaturas/fechamento;
não chama OpenProcess real. A concorrência executa threads com start/start, start/stop,
stop/start e stop/stop usando a trava real de arquivo do SO; não mede concorrência entre
clientes Tailscale externos. Testes CLI existentes usam subprocessos de teste locais.
Nada disso constitui homologação de Tailscale real, TLS real, iPad, rádio móvel ou hardware
de transcrição. Não foram ativados serviços reais, modelos ou APIs de IA.

## Arquivos e preservação do workspace

Código alterado apenas em `src/local_transcriber/remote_session.py` e
`tests/test_remote_session.py`. CLI, gateway, launcher, configurações MCP, UI,
sumarização, autenticação e migrações não precisaram de edição.

Documentos vivos atualizados: `PROJECT_STATE.md`, `FOUNDATION.md`, `ROADMAP.md`,
`DECISIONS.md`, `KNOWN_ISSUES.md`, `REMOTE_ACCESS_NEXT_IMPLEMENTATIONS.md`,
`REMOTE_ACCESS_INTEGRATION_PLAN.md` e `README.md`, além deste relatório.
ADR-042 registra a decisão posterior sem reescrever ADRs/relatórios históricos.

O inventário anterior incluiu arquivos rastreados e não rastreados não ignorados.
Comparação SHA-256 ao término comprovou que as diferenças deste worker se restringem
à allowlist acima, acrescidas deste relatório novo. As alterações anteriores dos demais
arquivos foram preservadas. `git diff --stat` foi inspecionado; o diff detalhado do worker
foi consolidado somente para os dois arquivos de código/testes, incluindo os não rastreados.
Nenhum diff detalhado de Markdown foi executado. Não houve stage, commit, push ou mudança
de branch; as implementações remotas anteriores e este complemento continuam locais.

O MCP Graphify não estava exposto nesta sessão; a CLI disponível consultou o grafo salvo
por `RemoteSessionManager` sem reindexação. O resultado limitado a 1000 tokens foi truncado
e suas posições estavam defasadas; fontes e testes atuais sustentam as conclusões.
Não houve necessidade de consulta remota ao GitHub.

## Limites e próxima autorização

- Se houver crash entre spawn e persistência do PID, `prepared` conserva o marcador,
  mas não há prova suficiente para matar ou declarar morto o processo automaticamente.
  A aplicação bloqueia start/stop e exige reconciliação manual local de processo/rede.
  Estado corrompido ou temporário sem journal também exige inspeção; apagar evidência
  para contornar o bloqueio não é procedimento de recuperação.
- Schemas Serve não reconhecidos e serviços são recusados conservadoramente. A
  compatibilidade com a versão real instalada de Tailscale não foi homologada.
- A trava cobre somente os comandos desta aplicação. Sem transação/CAS do CLI contra
  outros clientes, não se deve editar Serve externamente durante a sessão. Queda de
  energia e falha física do armazenamento não foram homologadas.
- Falha de consulta/off pode manter gateway e mapping ativos enquanto o journal é
  preservado. Após resolver a causa, repetir `stop` efetua nova inspeção e recuperação.
- Próxima ação: coordenador revisar o código e as evidências e decidir o gate. Qualquer
  Etapa 2 depende de nova autorização explícita. Nenhuma aprovação independente é
  reivindicada por esta implementação.
