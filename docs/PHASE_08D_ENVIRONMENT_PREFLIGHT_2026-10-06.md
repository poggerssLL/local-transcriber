# Manutenção 8D — diagnóstico do ambiente e preflight local

Data: 2026-10-06. Baseline: main `5cfc7b8`, versão 0.7.1, schema v4.
Escopo autorizado: investigar aviso do ambiente e preparar validação real.
Coordenador único escritor documental; worker Gemini 3.8 Flash high somente leitura.
Sem alteração funcional, instalação, remoção, renomeação, inferência ou publicação.

## Evidências confirmadas pelo coordenador

| Verificação | Resultado | Limite |
| --- | --- | --- |
| pip check no ambiente existente | exit 0, No broken requirements found; aviso invalid distribution ~ocal-transcriber | Não comprova inferência |
| Metadados ativos | local_transcriber-0.7.1.dist-info, Name local-transcriber, Version 0.7.1 | importlib.metadata seleciona 0.7.1 |
| Origem do import | Dentro de src do checkout principal | Sem presumir destino do editable install |
| Metadados com prefixo til | ~ocal_transcriber-0.6.2.dist-info e ~ocal_transcriber-0.7.0.dist-info têm versões antigas | Não são o dist-info selecionado; preservados |
| Código pip existente | Validação de nome em metadata/base.py rejeita nomes fora do padrão e emite o aviso | Não prova quem criou os resíduos |
| Atributos dos resíduos | ReadOnly e ReparsePoint observados | Não presumir que remoção/movimentação de placeholders seja trivial |
| Ollama GET /api/version | Serviço loopback respondeu versão 0.35.1 | Sem geração de texto |
| Ollama GET /api/tags | qwen2.5:3b e nomic-embed-text:latest presentes | Sem expor hashes/model metadata adicional |
| CTranslate2RuntimeProbe.inspect | Uma GPU; int8_float16 suportado; cuda_error None; CPU int8 suportado | Sondagem real de capacidade/DLLs, não inferência ou benchmark |

O aviso está associado aos diretórios antigos com nomes prefixados por til. O pacote
ativo e suas dependências passam nas verificações acima. Resíduos de uninstall/update
são hipótese compatível com o código de stash do pip, não causalidade histórica comprovada.
Não usar pip uninstall de versões antigas: o RECORD pode referir arquivos compartilhados
com o pacote ativo. Nenhuma limpeza foi feita, inclusive em tests/fixtures preexistentes.

## Plano reversível de reparo, ainda não executado

1. Delimitar somente os dois dist-info antigos; conferir tipo, reparse target e resolução
   absoluta dentro da .venv antes de qualquer movimentação. Inventário/backup ficam locais,
   fora do Git, sem incluir dados de runtime ou segredos.
2. Com autorização específica para mudar o ambiente, preferir quarentena fora de
   site-packages em diretório novo próprio, preservando conteúdo e nomes de origem.
   Se houver placeholder/lock ou destino inesperado, parar; não elevar privilégios.
3. Repetir pip check e verificar distribuição ativa e import 0.7.1. Se houver regressão,
   restaurar os dois diretórios por caminhos literais confirmados. Não apagar backups.
4. Instalação/recriação de venv não faz parte deste diagnóstico. Version/schema intactos.

## Plano de validação real sintética, ainda não executado

- Criar runtime exclusivo fora de diretório sincronizado; nunca reaproveitar fixtures
  antigas ou banco pessoal. Fixar importação de src, loopback e engine/modelo explícitos.
- Ollama: gerar transcript Markdown integralmente sintético curto com gabarito de tópicos,
  no formato aceito pelo parser da Etapa 8. Usar qwen2.5:3b já presente, sem pull/download.
  Medir parse, chunks, map/reduce, progresso, sidecars JSON/Markdown e timeout/falhas.
  Conferir que o original não muda e resultados contêm apenas dados da fixture.
- API/frontend: confirmar SSE progress/complete/error, fallback de consulta final e troca
  de leitura com respostas obsoletas. Teste navegador/controlado é separado de node syntax.
- CPU/CUDA: áudio sintético controlado novo e modelo explicitamente já instalado; presença
  atual do small ainda não conferida. Comparar mesmo áudio/parâmetros, persistência, lease,
  cancelamento e exportações. Não inferir GPU inference a partir de runtime probe.
- Critérios: zero downloads/fallback de nuvem, sem runtime pessoal, integridade do original,
  saídas/schema válidos, tratamento sanitizado e resultados/tempo documentados com limites.
  Qualidade exige gabarito independente; amostra curta não valida carga longa.

As 142 aprovações e Ruff/formatação da 8C são evidências históricas, não reexecução nesta
manutenção documental. Etapa 9 não iniciada. Commit/push não realizados neste marco.

## Revisão do retorno Gemini

Diagnóstico dos metadados antigos aceito como apoio, conferido independentemente.
A afirmação de que Ollama está desligado foi rejeitada: a observação do worker
restrito não demonstra o estado fora do sandbox; GET loopback do coordenador
respondeu e listou o modelo. A proposta de WAV senoidal sem voz pode testar pipeline,
mas não avaliar sumarização de texto: usar transcript sintético não vazio independente
para Ollama e separar validação CPU/CUDA. Não executar limpeza/descarte proposto,
não iniciar serviço nem usar símbolos de API não conferidos no código.
Turno final observado; attempt fenced pelo coordenador por IPC EPERM, Task failed
operacionalmente e recursos preservados. Não houve worker_done durável nem release
de terminal ativo. Artefatos automáticos do provider não foram copiados para Git.
