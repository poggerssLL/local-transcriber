# Manutenção 8H — instalação a partir do GitHub

Data: 2026-10-13. Baseline main `5cfc7b8`, upstream origin/main.
Consulta ao remoto confirmou o mesmo commit. API pública do GitHub confirmou
repositório público, branch padrão main, sem licença reconhecida na entrada.
Alterações locais 8D/8E/8F/8G preexistentes preservadas. Nenhum commit/push.

## Pedido, diagnóstico e entrega

Erick pediu verificar replicação em outros computadores e corrigir o necessário.
Também escolheu expressamente licença somente para uso pessoal e não comercial.
O código publicado já continha backend, frontend e configuração de package-data;
não precisava de Orca/Codex nem de cópia do ambiente do autor. O README, porém,
começava com instalação de desenvolvimento, sem fluxo ZIP/clone completo,
separação clara de modelos, CPU/CUDA e Ollama opcional. Não existia LICENSE.

- Instalador PowerShell cria `.venv` com Python 3.13 x64, instala pacote normal
  sem extra dev, verifica prefixo, pip check e versão. Recusa ambiente existente
  salvo `-Update` explícito; nenhuma remoção, instalação global, modelo ou daemon.
- Guia INSTALLATION cobre ZIP/Git, primeiro modelo explícito, início/fim,
  CPU primeiro, dados locais, Ollama opcional, atualizações e falhas frequentes.
- LICENSE pessoal/não comercial; pyproject referencia o arquivo e o README
  descreve a restrição. Componentes/modelos de terceiros mantêm suas licenças.
- Smoke instalado verifica importação non-editable, seis assets do wheel,
  modelos ausentes, servidor HTTP real e criação de matéria em SQLite novo.
- Workflow Windows instala em Python 3.13 x64 e executa esse smoke, sem modelos.
  Automação preparada, ainda não executada no GitHub porque não houve publicação.

## Validação observada agora

Snapshot dos arquivos publicados com `git archive HEAD`, mais somente os cinco
arquivos iniciais desta entrega (README, pyproject, LICENSE, guia e instalador).
Extração em pasta com espaços, venv novo sem system-site-packages, pip instalando
dependências reais e construindo wheel. Nenhum modelo, banco, fixture antiga,
transcrição, mídia pessoal ou summarizer local 8G foi copiado.

- Instalador real exit 0; Python 3.13 Windows x64, pacote 0.7.1/schema 4.
- Dependências resolvidas e pip check sem incompatibilidades. Nesta instalação,
  av 16.1.0, CTranslate2 4.8.2, Faster Whisper 1.2.1, FastAPI 0.116.2,
  Uvicorn 0.54.0 e Hugging Face Hub 2.2.0. Ranges não são lock exato.
- Pacote importado de site-packages; LICENSE e seis assets presentes; pytest
  ausente, comprovando que extra dev não é necessário para usar.
- Servidor real ligado somente em loopback com porta efêmera: `/api/health`
  status ok, versão 0.7.1/schema 4; página inicial disponível e matéria fictícia
  persistida. Processo de teste encerrado em finally, sem daemon residual.
- Guarda de `.venv` existente recusou reinstalação implícita conforme esperado.
- Smoke final também aprovado após endurecer a checagem de modelos ausentes.
- Suíte existente no ambiente de desenvolvimento: 150 testes aprovados em
  27,49 s; Ruff e formatação, AST de 30 arquivos e pip check aprovados.
- Parser nativo PowerShell e parser YAML do workflow aprovados. Esses parsers
  não comprovam execução de GitHub Actions.

## Limites e gate

Este é um ambiente Python novo **no mesmo computador**, não validação em um
segundo computador/VM nem instalação de Windows sem seus componentes nativos.
NVIDIA não é requisito de CPU, mas runtime Visual C++ pode ser necessário para
carregar wheels nativos. Não foram instalados componentes de sistema, Ollama ou
modelos. Não houve inferência nova, portanto nenhuma alegação de precisão, CUDA,
resumos ou E2E de fala decorre deste smoke. 8G continua exigindo complemento.
Linux/macOS/ARM não homologados. Primeira instalação exige rede; offline exige
preparação prévia de dependências/modelos. Atualizações de dependências em ranges
podem mudar o resultado; CI foi adicionado para detectar regressões.

Coordenador Codex único escritor; revisão real Orca Antigravity Gemini 3.8 Flash
high/high somente leitura, fallback none.
Parecer final recebido: replicabilidade APROVADA para o caminho Windows
documentado, com limites do teste no mesmo host e publicação ainda pendente.
Nenhuma edição no repositório pelo reviewer; artefato interno de auditoria
separado. Worker_done real aceito, release e ACK concluídos, zero reclaimable.
Após revisar esta entrega, Erick autorizou explicitamente commit e push somente
da instalação/licença. A confirmação da publicação é obtida pelo Git após o push,
sem inferir sucesso a partir da autorização. Mudanças 8D–8G ficam fora deste commit.
Não misturar os arquivos anteriores de runtime ou mudanças 8G nesta entrega.
