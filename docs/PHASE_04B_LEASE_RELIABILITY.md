# Etapa 4B — confiabilidade de lease

## Escopo

Esta correção complementar permanece dentro da Etapa 4. Ela não adiciona API HTTP,
SSE, frontend nem funcionalidades da Etapa 5. O relatório histórico
`PHASE_04_PERSISTENT_QUEUE.md` permanece inalterado.

A versão passa a `0.4.1`. O schema continua v4: a correção altera coordenação e
validação de posse, sem exigir novas estruturas persistidas ou migração.

## Causa

`_LeaseHeartbeat` encerrava sua thread ao receber qualquer `Exception` de
`renew_lease`, sem expor a falha ao fluxo principal. Assim, a inferência podia continuar
sem saber que a renovação havia parado. Depois de uma recuperação por outro worker, o
tratamento genérico de erro ainda podia tentar `fail_claimed_job` com a posse antiga; a
segunda perda de posse podia escapar e encerrar o loop do worker.

## Correção

- `LeaseOwnershipLost` representa especificamente a ausência de uma lease válida e não
  é tratada como falha comum do engine.
- O heartbeat registra sua primeira exceção, mantém um sinal compartilhado de perda e
  termina de forma observável.
- `sqlite3.OperationalError` durante renovação recebe tentativas limitadas, com espera
  curta, somente enquanto resta margem segura antes da expiração confirmada.
- Perda explícita, erro não transitório ou esgotamento seguro das tentativas ativa o
  sinal de perda.
- Callbacks de progresso e pontos cooperativos consultam o sinal. Ao perder a posse, o
  worker abandona a tentativa sem cancelar, falhar ou publicar o job de outro worker.
- Renovação, progresso, finalização por cancelamento ou falha e publicação validam
  também se a lease ainda não expirou.
- A perda de um job não encerra o loop; o worker pode procurar o próximo.
- `KeyboardInterrupt` e `SystemExit` continuam encerramentos operacionais, fora do
  tratamento de falhas de domínio.

## Semântica e garantias

- Somente um worker possui a lease válida.
- Somente o proprietário atual pode persistir progresso ou publicar.
- Depois da expiração pode existir uma pequena sobreposição de computação até o worker
  obsoleto alcançar um ponto cooperativo.
- A publicação permanece transacional e a unicidade por job impede duas publicações
  finais para o mesmo trabalho.

Portanto, a correção não promete que duas inferências nunca se sobreponham. O controle
forte está nas mutações persistentes e na publicação final.

## Regressões automatizadas

Os testes sem modelo real, áudio, GPU ou rede verificam:

- erro SQLite transitório no heartbeat, retry limitado e recuperação;
- esgotamento das tentativas dentro da margem de segurança;
- perda definitiva comunicada ao callback de progresso;
- rejeição de progresso e publicação por worker obsoleto;
- ausência de transcrição duplicada;
- preservação do job pertencente ao novo worker, sem marcação como `failed`;
- continuidade do loop após perder um job;
- encerramento do heartbeat ao finalizar o trabalho;
- preservação de `KeyboardInterrupt` e `SystemExit` como encerramentos operacionais;
- regressão integral dos 63 testes anteriores.

A suíte resultante possui 72 testes. Também foram verificados Ruff, formatação,
compilação, integridade das dependências, CLI e `git diff --check`.

## Resultado

Nenhuma migração foi criada e o schema permanece v4. A proteção transacional contra
publicação duplicada foi preservada. A Etapa 5 não foi iniciada.
