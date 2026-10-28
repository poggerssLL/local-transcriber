# Manutenção 8G — qualidade e fala sintética

Data: 2026-10-07. Baseline main `5cfc7b8`, upstream origin/main local;
pacote 0.7.1, schema 4 preservados. Entrega local, sem commit/push.
8D/8E/8F e fixtures antigas permanecem. Coordenador Codex único escritor;
revisores reais Orca Antigravity Gemini 3.8 Flash high/high, somente leitura,
`fallback: none`. Nenhum modelo/plugin foi instalado ou baixado.

## Mudança e gabarito

Novo harness opt-in `scripts/validate-phase8-quality.py` e oito regressões.
O map prompt especifica chaves canônicas de timeline/glossário/flashcards e
timestamps da fonte mesmo curta. O reduce pede extensão proporcional, preservação
de números, relações causais, atores e ressalvas, sem mínimo artificial de palavras
ou lista final redundante de glossário. Apenas parágrafos textualmente idênticos
são removidos; não se tenta deduplicar significado automaticamente.

Gabarito criado antes da avaliação: seis fatos fictícios sobre sensor, referência
de 25 graus, comparação pelo controlador, erro regulando aquecimento,
realimentação e ausência de dados reais/equipamentos conectados. Fonte do resumo
tem timestamps conhecidos 0/30/60/90/120/150 s. Fala SAPI Maria pt-BR instalada,
seis enunciados e pausas de 0,6 s, com janelas obtidas de cada WAV gerado.
WER normaliza grafia numérica/acentos; critérios iniciais WER <= 0,20,
seis âncoras dentro da janela ±1 s e timestamps de palavras finitos na duração.
Cobertura lexical, número, timeline e Jaccard são indicadores, não aceite semântico.
O resultado exige explicitamente revisão manual.

## Evidência nativa preservada

Execução c em output ignorado, fora do basetemp do pytest:

| Perfil | Áudio | Segmentos | WER | Âncoras | Processamento |
| --- | --- | --- | --- | --- | --- |
| small CPU int8 | 36,466 s sintéticos | 6 | 0,0 | 6/6 | 25,545 s |
| small CUDA int8_float16 | mesma fixture | 6 | 0,0 | 6/6 | 6,445 s |

Timestamps válidos; áudio preservado. Inferência real com modelo existente,
offline forçado para Hugging Face. Isso mede somente esta fala sintética curta,
não fala humana, ruído, sessão longa ou benchmark de carga.

Ollama qwen2.5:3b local processou TEXTO sintético separado, não a saída Whisper.
Resumo c: 31,648 s, seis indicadores factuais/seis marcos, zero duplicatas exatas;
revisor aprovou inicialmente, mas o coordenador encontrou tese central atribuindo
a comparação ao sensor em vez do controlador. Aceite semântico irrestrito recusado.
Complemento d (30,450 s) corrigiu a tese, mas acrescentou definições repetidas
nos parágrafos/roteiro. Complemento e (26,508 s): seis indicadores/seis marcos,
sem duplicatas exatas, Jaccard máximo 0,3571. Gate independente final Gemini:
COMPLEMENTO NECESSÁRIO, aceito pelo coordenador; oito testes do reviewer passaram.
Leitura manual do coordenador em e encontrou redundância de definições no terceiro
parágrafo e roteiro; a tese voltou a permitir leitura de que o sensor compara.
Os indicadores passaram, mas o coordenador não aceita aprovação semântica integral.
Reviewer confirmou omissão do controlador na tese, repetição conceitual de P1
em P3 e duplicação da ressalva no roteiro. Worker_done real recebido, release
e ACK concluídos; sucesso da tarefa de revisão não é aprovação do produto.
Artefatos c/d/e, fontes Markdown/JSON e áudio c permanecem em output ignorado.

## Testes e limites de evidência

Suíte completa: 150 aprovados (142 anteriores + 8 novos). Após ajustes de prompt,
19 testes de resumo/qualidade aprovados; Ruff, formatação e pip check aprovados.
Nenhuma mudança de versão/schema, fila, engine, API ou interface.

A primeira execução a produziu fala WER 0 e resumo com timeline vazia,
apenas 3/6 indicadores factuais, repetição e extrapolação de eficácia. Esse
resultado motivou o complemento. Artefatos a e b foram colocados pelo coordenador
em `.test-tmp`; a suíte usa `--basetemp=.test-tmp` e apagou essas evidências.
Seus resultados são registros observados no terminal, sem originais preservados.
O coordenador reconheceu o erro e regenerou c em output; novas execuções de testes
usam basetemp próprio distinto. Não afirmar preservação do scratch anterior.
Não houve limpeza intencional das fixtures antigas em tests/fixtures.

Próximo: decidir gate final de fidelidade/concisão e definir pacote sintético E2E
fala→fila→transcrição→resumo→API/interface com critérios de fatos e timestamps.
Até esse gate, Etapa 9 não iniciada. Não aprovar qualidade geral por seis palavras,
indicadores ou um worker_done. Dados reais, carga longa e publicação dependem de
pedido próprio; controle visual/instalação/download continuam fora do escopo.
