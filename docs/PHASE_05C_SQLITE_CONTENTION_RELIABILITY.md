# Correção complementar 5C — Confiabilidade da contenção SQLite

## Resultado

A correção 5C eliminou a aquisição repetida de locks de escrita pelo worker HTTP quando a
fila está vazia e tornou o controlador resistente a falhas SQLite transitórias na consulta
ou reivindicação. A versão passou de `0.6.0` para `0.6.1`; o schema SQLite permanece v4 e
nenhuma migração foi alterada ou adicionada.

O baseline limpo e publicado foi
`9b3f7bf764b73a43cf8f8e3f1e6c1f0781ee3478`. A correção frontend 6B e a Etapa 7 não
fazem parte deste trabalho.

## Falha observada

A suíte do baseline executou 101 casos, mas terminou com 100 aprovados e uma falha em um
teste de evento terminal SSE. O upload sintético falhou ao inserir a gravação com
`sqlite3.OperationalError: database is locked`. A execução isolada reproduziu a mesma
falha, descartando a hipótese de resultado ocasional de uma ordem específica da suíte.

O banco afetado estava em runtime temporário exclusivo fora do checkout. Não ocorreu
`PermissionError`, interferência do OneDrive, reutilização de banco ou processo externo.
A operação concorrente era a própria thread do worker criada pelo lifespan da aplicação.

## Causa confirmada

`Repository.claim_next_job()` iniciava `BEGIN IMMEDIATE`, recuperava leases e só então
consultava se existia job pendente. Assim, cada polling ocioso adquiria uma transação de
escrita mesmo sem qualquer estado a alterar. Com intervalo de teste de 0,01 segundo, o
worker conseguia disputar repetidamente o lock necessário ao INSERT do upload.

`PRAGMA busy_timeout = 5000` controla quanto uma operação SQLite pode aguardar depois que
a contenção existe. Ele não evita a aquisição desnecessária do lock pelo worker nem garante
justiça entre upgrades de transações concorrentes; aumentá-lo apenas mascararia a causa e
alongaria a falha.

Além disso, `_WorkerController._run()` não diferenciava um lock SQLite transitório: uma
exceção que escapasse de `run_once()` encerrava a thread sem política de retry controlada.

## Solução aplicada

### Pré-consulta somente leitura

Antes de abrir a transação imediata, o repositório executa uma consulta parametrizada por:

- job `pending`, sem cancelamento e abaixo do limite de tentativas; ou
- job `running` com lease ausente ou vencida no instante verificado.

Se não existir candidato, o polling retorna sem abrir transação de escrita. Um job criado
logo depois desse resultado pode aguardar até o polling seguinte, comportamento deliberado
e limitado pelo intervalo normal do worker.

Se existir candidato, `BEGIN IMMEDIATE` continua obrigatório. Dentro dele, leases vencidas
são recuperadas novamente, o candidato pendente é selecionado novamente e o UPDATE exige
estado, cancelamento e limite de tentativas ainda válidos. Portanto, a pré-consulta é apenas
uma otimização conservadora: ela nunca concede posse e não substitui o compare-and-set.
Dois processos continuam incapazes de reivindicar o mesmo job.

### Falhas transitórias do controlador

O controlador classifica como transitórios somente códigos base `SQLITE_BUSY` e
`SQLITE_LOCKED`. Para doubles sem código SQLite, são aceitas apenas as mensagens conhecidas
de banco, tabela ou schema ocupado.

Uma falha transitória recebe espera curta por `Event.wait`, portanto responsiva ao shutdown,
e até três retries consecutivos. Qualquer execução sem erro zera a contagem. O primeiro erro
transitório permanece observável no controlador.

Erros SQLite permanentes não são repetidos. Falhas transitórias acima do limite também
param. Nos dois casos, a exceção fatal é registrada no controlador e no log antes da thread
encerrar; não existe loop infinito nem ocultação silenciosa.

## Testes determinísticos

Foram adicionados seis testes específicos:

- fila vazia não abre transação `immediate`;
- upload HTTP conclui enquanto o worker ocioso faz polling sem locks de escritor;
- job criado após uma pré-consulta vazia é reivindicado no polling seguinte;
- um lock transitório é repetido e a thread continua viva;
- erro SQLite permanente não recebe retry;
- locks transitórios persistentes param exatamente após o limite configurado.

Os testes já existentes continuaram verificando:

- somente um vencedor entre dois workers concorrentes;
- recuperação e nova reivindicação de lease vencida;
- conclusão integral de um job com engine falsa;
- falha do engine com evento SSE terminal e mensagem sanitizada;
- `Last-Event-ID`, desconexão sem cancelamento, Range, retry e lock de um consumidor por
  runtime.

Todos os cenários usam bancos, runtime, mídia e engines sintéticos ou doubles. Nenhum
modelo foi baixado, nenhum áudio pessoal foi usado e nenhuma inferência real foi executada.

## Validação

- teste originalmente falho mais regressões 5C: 7 aprovados;
- fila, API e regressões de contenção: 50 aprovados;
- suíte completa: 107 aprovados;
- Ruff: aprovado;
- formatação Python: 43 arquivos em conformidade;
- compilação Python: aprovada;
- sintaxe dos três módulos JavaScript existentes: aprovada;
- `pip check`: nenhuma dependência quebrada;
- `git diff --check`: aprovado antes da publicação.

Os temporários exclusivos ficaram fora do checkout. A interface permaneceu inalterada e
não ganhou dependência de Node em instalação ou execução; Node foi usado somente para
verificação de sintaxe durante o desenvolvimento.

## Limitações preservadas

- execução após crash continua `at least once`;
- recuperação pode reiniciar a inferência completa;
- cancelamento e perda de lease continuam cooperativos;
- um lock transitório persistente além do limite interrompe o controlador e exige ação
  operacional, em vez de permanecer oculto;
- fila com Faster Whisper real, cargas longas e CUDA continuam pendentes da Etapa 7.

A correção 6B e a Etapa 7 não foram iniciadas.
