# Relatório de Manutenção e Validação de Baseline — Etapa 8B

> Documento factual de consolidação de baseline e validação estática em 2026-10-05 (atualizado no complemento de precisão documental).

## 1. Contexto e Mandato

A Etapa 8B teve como objetivo exclusivo a manutenção de baseline, validação estática e saneamento de contradições documentais após a conclusão da Etapa 8 (sumarização estruturada com Ollama local).
Em cumprimento estrito às regras do repositório e ao mandato desta intervenção:
- Nenhuma funcionalidade nova foi introduzida.
- Oito arquivos de código pré-existentes modificados foram rigorosamente congelados em seu conteúdo original, sem edições, reformatações, inclusões de staging ou commits.
- A validação foi conduzida no escopo de testes automatizados com mocks e fixtures locais no `.venv` pré-instalado, sem monitoramento ativo de tráfego de rede nem garantia formal de isolamento de rede no nível do sistema operacional.
- Nenhum download, modelo de inferência real, GPU externa, API em nuvem ou modificação no banco pessoal foi realizado.

## 2. Hashes de Integridade dos Arquivos Pré-existentes Protegidos

Para garantir a imutabilidade absoluta dos oito arquivos pré-existentes, seus hashes SHA-256 foram calculados no início da execução e verificados no fechamento do gate:

| Arquivo | SHA-256 Inicial | SHA-256 Final | Estado |
|---|---|---|---|
| `src/local_transcriber/api.py` | `39739E47C398ED7E0AB7283CEFF1D933D6564262B33EC16C9ADF52625E53A185` | `39739E47C398ED7E0AB7283CEFF1D933D6564262B33EC16C9ADF52625E53A185` | Preservado |
| `src/local_transcriber/summarizer.py` | `328B4B156D2ACC333CDCFF7654063C5C478278E64DF4DE2A70F88DB9547CBE2C` | `328B4B156D2ACC333CDCFF7654063C5C478278E64DF4DE2A70F88DB9547CBE2C` | Preservado |
| `src/local_transcriber/web/api.js` | `4501ECA74726CC3FF3A89192DC71C177503130A4BE799B021A59448F0772C541` | `4501ECA74726CC3FF3A89192DC71C177503130A4BE799B021A59448F0772C541` | Preservado |
| `src/local_transcriber/web/app.js` | `2AC425C27A095A9A82A470D6D08AEF56341C26482C780196FA160A9C5D487C95` | `2AC425C27A095A9A82A470D6D08AEF56341C26482C780196FA160A9C5D487C95` | Preservado |
| `src/local_transcriber/web/index.html` | `FE2C1E864D8F3620E8BFB39518C98F35A61B42730438966CFFF26A72F36E4039` | `FE2C1E864D8F3620E8BFB39518C98F35A61B42730438966CFFF26A72F36E4039` | Preservado |
| `src/local_transcriber/web/styles.css` | `54D9DF01822D4A8181A45F6F51675660D332826D59EBB22FC1DFDFE8416C4C0D` | `54D9DF01822D4A8181A45F6F51675660D332826D59EBB22FC1DFDFE8416C4C0D` | Preservado |
| `tests/test_api_summary.py` | `C7AC5509F57C42FEBC8CEFE2596EB2A235C8189EBA6385439716CC457BB2DF0E` | `C7AC5509F57C42FEBC8CEFE2596EB2A235C8189EBA6385439716CC457BB2DF0E` | Preservado |
| `tests/test_summarizer.py` | `37EAA52BB06631739C1CC3D528FFCC20D0A3AAFC8E07AB961B8A0327D5D0A54C` | `37EAA52BB06631739C1CC3D528FFCC20D0A3AAFC8E07AB961B8A0327D5D0A54C` | Preservado |

Nenhum byte dos arquivos acima foi alterado.

## 3. Matriz de Validação Automatizada e Baseline

### 3.1 Suíte de Testes Python (pytest)
- **Coleta**: 141 testes unitários e de integração coletados em 12 módulos de teste.
- **Isolamento de Temporários**:
  - Diretório de base temporária apontado explicitamente para subárvore confinada `tests/fixtures/maintenance_20261005_retry/pytest-tmp`, sem remover ou sobrescrever a pasta `.test-tmp` do repositório.
  - Caches desativados (`-p no:cacheprovider`) e geração de bytecode suprimida (`-B`).
- **Histórico de Execução na Validação**:
  - Primeira execução integral da suíte: registrou 1 falha e 140 aprovações (`1 failed, 140 passed in 20.76s`). A falha ocorreu no teste `test_heartbeat_bounds_retries_when_sqlite_does_not_recover` em `tests/test_queue.py` por asserção `assert attempts == heartbeat.max_transient_retries + 1` (`assert 3 == (3 + 1)`).
  - Retries efetivos:
    - Execução direcionada do teste isolado: aprovado.
    - Execução direcionada do módulo `tests/test_queue.py`: 23 testes aprovados em 4.56s.
    - Reexecução integral da suíte de 141 testes: aprovada em 19.18s (`141 passed in 19.18s`).
- **Caracterização Factual da Intermitência**:
  - Trata-se de uma sensibilidade transitória de temporização/sincronização no teste de heartbeat.
  - A causa exata permanece não demonstrada; hipóteses como sobrecarga do escalonador ou barreira prematura de thread pool são especulativas e não comprovadas.
  - O teste não apresenta garantia de comportamento determinístico; a falha inicial e a aprovação nos retries foram documentadas honestamente em `docs/KNOWN_ISSUES.md`.
  - Em conformidade com a orientação do coordenador, a suíte pytest completa não foi reexecutada no complemento de manutenção.

### 3.2 Sintaxe JavaScript Individual (Node.js)
A invocação anterior de `node --check` com quatro argumentos simultâneos validava apenas o primeiro arquivo passado como script e ignorava os demais (tratados como argumentos de linha de comando).
Para comprovação rigorosa e individual, cada arquivo JavaScript da interface web foi executado separadamente com `node --check`:

| Arquivo | Comando Executado | Código de Saída | Erros de Sintaxe |
|---|---|---|---|
| `src/local_transcriber/web/api.js` | `node --check src/local_transcriber/web/api.js` | 0 | 0 |
| `src/local_transcriber/web/app.js` | `node --check src/local_transcriber/web/app.js` | 0 | 0 |
| `src/local_transcriber/web/async_state.js` | `node --check src/local_transcriber/web/async_state.js` | 0 | 0 |
| `src/local_transcriber/web/dom.js` | `node --check src/local_transcriber/web/dom.js` | 0 | 0 |

Os 11 testes JavaScript comportamentais históricos da baseline continuam descritos em `docs/FOUNDATION.md` e não foram reexecutados nesta manutenção.

### 3.3 Compilação de Sintaxe Python (`compileall`)
- Comando executado: `python -m compileall -q src tests`.
- Resultado: Código de saída 0; todos os módulos compilados sem erros de sintaxe.

### 3.4 Verificação de Integridade de Dependências (`pip check`)
- Comando executado: `python -m pip check`.
- Resultado: Código de saída 0; `No broken requirements found` (com aviso de dist-info antigas marcadas com til em `site-packages` decorrentes de atualizações anteriores).

### 3.5 Verificação de Conflitos e Diferenças Git (`git diff --check`)
- Comando executado: `git diff --check`.
- Resultado: Código de saída 0; nenhum conflito ou espaço em branco irregular.

## 4. Auditoria de Qualidade e Linter (Ruff)

A auditoria estática não possui sucesso global no repositório; há dívida técnica pendente nos arquivos de código protegidos:

### 4.1 Linter (`ruff check .`)
O comando retornou código de saída 1 com 10 advertências `E501` (comprimento de linha > 100 caracteres):
- `src/local_transcriber/api.py`: 4 ocorrências (linhas 1246, 1258, 1284, 1293);
- `src/local_transcriber/summarizer.py`: 1 ocorrência (linha 696);
- `tests/test_api_summary.py`: 4 ocorrências (linhas 460, 491, 498, 564);
- `tests/test_summarizer.py`: 1 ocorrência (linha 384).

Todas as 10 advertências residem nos arquivos de código protegidos e foram intencionalmente preservadas sem alteração para manter o congelamento estrito de código.

### 4.2 Formatador (`ruff format --check .`)
O comando retornou código de saída 1 indicando que 4 arquivos teriam alterações de formatação (os mesmos quatro arquivos mencionados acima), enquanto os demais 48 arquivos do repositório já se encontram formatados. Nenhuma modificação foi aplicada.

## 5. Auditoria da Remoção de `tests/fixtures` e Limites de Evidência

Durante a execução da manutenção pelo worker anterior, foi identificada a execução do comando `Remove-Item -Path "tests/fixtures" -Recurse -Force`:
- **Escopo Autorizado**: A autorização do coordenador permitia exclusivamente o saneamento das subárvores temporárias de scratch desta tarefa (`maintenance_20261005` e `maintenance_20261005_retry`).
- **Ação Realizada**: O comando de remoção recursiva foi direcionado ao diretório-pai `tests/fixtures`, excedendo a autorização restrita. O registro disponível não comprova a remoção integral nem o impacto sobre todos os conteúdos anteriores.
- **Evidências do Histórico e Limitações**:
  - O arquivo de log e histórico acessível exibe as chamadas de remoção sem expansão exaustiva de conteúdo estrutural prévio.
  - `git ls-files tests/fixtures` retorna vazio no index atual; isso sozinho não comprova ausência em todo o histórico nem preservação de arquivos não versionados.
  - Antes da remoção, foram observadas as subpastas sintéticas temporárias de scratch, mas devido ao truncamento dos registros de arquivos não é possível atestar com certeza absoluta a ausência total de links ou conteúdos adicionais no diretório pai. Esse limite é categorizado como **desconhecido**.
- **Estado Atual conferido pelo coordenador**: `tests/fixtures/maintenance_20261005` existe e contém resíduos sintéticos não versionados da primeira tentativa, incluindo locks, exportação de teste e DLLs de fixture. Foram preservados; não houve nova remoção. A presença atual não demonstra a causa da divergência entre as observações nem recupera um inventário anterior completo. Esses artefatos ficam fora de qualquer commit.

## 6. Saneamento Documental e Governança de ADRs

### 6.1 Alinhamento de Contradições do Escopo Ollama
- `AGENTS.md` e `docs/PROJECT_CONTRACT.md`: Invariantes mantidos afirmando que diarização, microfone ao vivo e Home Assistant estão fora do MVP, esclarecendo que a sumarização estruturada com Ollama local opera estritamente em loopback (`127.0.0.1`), sem dependência de nuvem nem vazamento de dados.
- `docs/PROJECT_STATE.md`: Fotografia atualizada para 2026-10-05, registrando os 141 testes Python com mocks e fixtures locais (sem monitoramento formal de rede), a execução individual de sintaxe Node nos 4 arquivos JS, a dívida técnica pendente do Ruff (10 E501 e 4 arquivos desformatados) e a sensibilidade intermitente do teste de heartbeat.
- `docs/FOUNDATION.md`: Preservado o histórico integral dos 11 testes JavaScript comportamentais e cobertura de concorrência, distinguindo que não foram reexecutados nesta manutenção, além de documentar os endpoints e sidecars do summarizer.
- `docs/ROADMAP.md`: Registrada a conclusão da Etapa 8 e a manutenção 8B, preservando as próximas etapas como não iniciadas.

### 6.2 Governança de Decisões Arquiteturais (`docs/DECISIONS.md`)
- A proposta anterior de introduzir ADR-036 (retroativa) e ADR-037 (gate de baseline) em `docs/DECISIONS.md` foi descartada:
  - ADR-037 é um procedimento de gate operacional de manutenção e pertence a este relatório factual de validação, não a `docs/DECISIONS.md`.
  - ADR-036 introduzia data pretérita e asserções não comprovadas de isolamento de rede; para evitar formalizações retroativas desnecessárias, `docs/DECISIONS.md` permanece inalterado e preservado exatamente em seu estado original de HEAD (terminando em ADR-035).
  - O alinhamento factual da implementação existente do summarizer permanece documentado na arquitetura viva (`docs/FOUNDATION.md`) e no relatório da Etapa 8.

## 7. Conclusão e Estado do Gate

O gate de manutenção e consolidação de baseline foi concluído com limites factuais transparentes:
- **Código Congelado**: 8 arquivos protegidos com hashes SHA-256 100% idênticos e preservados.
- **Sintaxe JavaScript**: 4 arquivos validados individualmente com `node --check` (código de saída 0 em cada um).
- **Testes Python**: 141 testes aprovados com mocks e fixtures locais, registrando falha inicial e retries efetivos em teste intermitente de heartbeat, sem suposições causais.
- **Estilo e Linter**: 10 advertências Ruff E501 e 4 arquivos pendentes de formatação registrados honestamente como dívida técnica não sanada.
- **Operação de Arquivos**: Ocorrência da remoção de `tests/fixtures` investigada e documentada com declaração factual de limites de evidência.
