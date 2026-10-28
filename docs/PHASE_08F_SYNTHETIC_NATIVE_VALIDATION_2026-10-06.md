# Manutenção 8F: validação nativa sintética (2026-10-06)

Main `5cfc7b8`, pacote 0.7.1/schema 4 preservados. Harness opt-in
`scripts/validate-phase8-synthetic.py`: pasta nova exclusiva, dados sintéticos e
modelos existentes; modelo incompleto recusado, Hugging Face offline. Ollama em
loopback literal, proxy desativado e redirects recusados. Sem download/instalação,
dados pessoais, alteração de serviços ou defaults de produção.

| Exercício nativo | Resultado | Limite |
| --- | --- | --- |
| FasterWhisper small CPU int8 | Concluído em 6,292 s | Tom sintético 2 s, zero segmentos; não mede fala |
| FasterWhisper small CUDA int8_float16 | Concluído em 2,410 s | Mesmo tom; não mede precisão/throughput longo |
| Ollama qwen2.5:3b | Map/reduce e persistência em 34,751 s | Texto sintético separado; não é E2E de fala |

Fonte/áudio preservados; hashes somente no runtime local. Markdown/sidecar JSON,
reconstrução TranscriptSummary e tese não vazia conferidos. Gabarito lexical 5/5;
não é aprovação semântica. Fases parsing/chunking/map/reduce/persisting/completed.

Primeira tentativa expirou em 60,023 s, causa não estabelecida. Segunda gerou
artefatos mas o harness falhou por atributo incorreto. Corrigido para
`summary.executive`; repetição somente do resumo com timeout 180 s concluiu.
Timeout pertence ao harness, sem mudança nos defaults de produção.

Inspeção manual encontrou repetição de parágrafos e timeline vazia apesar de
timestamps na fonte. Cobertura 5/5 não prova fatos completos, incluindo referência
numérica. Gate técnico passou; qualidade exige complemento. Fala com gabarito,
fila SQLite/leases, interface/SSE E2E, carga prolongada e dados reais não exercitados.

142 testes Python aprovados; Ruff src/tests/harness, formatação e pip check
aprovados. Mocks da suíte não são a evidência das execuções nativas acima.
Reviewer Gemini 3.8 Flash high recebeu despacho Orca real, somente leitura dos
contratos. Done durável aguarda consentimento de IPC. Coordenador executou a
validação nativa; manutenções 8D/8E e fixtures antigas preservadas.

Próximo: qualidade com gabarito de fatos/timestamps e áudio sintético com fala,
antes de ampliar uso. Etapa 9 não iniciada. Sem commit/push. Artefatos, caminhos
pessoais e IDs de runtime permanecem fora do Git.
