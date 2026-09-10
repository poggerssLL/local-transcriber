# Etapa 6 — Interface web local

## Resultado

A Etapa 6 adicionou uma interface web local completa para o uso cotidiano do Local
Transcriber. Ela é servida pelo mesmo processo FastAPI em `http://127.0.0.1:8765`, usa a
API `/api` da mesma origem e funciona sem build, CDN, telemetria, serviço externo ou
runtime Node em produção.

A versão passou de `0.5.1` para `0.6.0`. O schema SQLite permanece v4: a interface apenas
consome contratos existentes e não exigiu mudança estrutural no banco. O baseline limpo e
publicado foi `1659f5532ebfa9cb5ab2b713498da23a44276bd7`, correspondente à correção
complementar 5B.

## Escopo implementado

### Entrega e arquitetura

- `GET /` entrega o shell HTML da aplicação sem entrar no OpenAPI;
- `/assets` serve CSS e módulos JavaScript incluídos no pacote Python;
- os contratos de dados permanecem versionados sob `/api`;
- `/api/openapi.json` continua local, e Swagger UI e ReDoc permanecem desabilitados;
- a política CSP permite somente os recursos da mesma origem necessários à interface;
- não há framework de frontend, etapa obrigatória de build ou dependência de internet.

O JavaScript foi dividido em cliente HTTP/SSE, utilitários seguros de DOM e coordenação das
vistas. Dados de matérias, títulos, pesquisa, transcrições e erros são tratados como texto.
A implementação não usa `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`
ou `eval`.

### Fluxos de uso

- Painel: saúde do serviço, estado do worker, perfil recomendado, modelos e jobs recentes.
- Matérias: criação, listagem e seleção como filtro da biblioteca.
- Biblioteca: upload progressivo de áudio ou vídeo, título, matéria, data, pesquisa FTS5,
  listagem, metadados e exclusão com confirmação.
- Transcrição: modelo, idioma automático ou português, perfil automático, CPU ou CUDA,
  beam size, VAD e timestamps por palavra, com revisão antes do enfileiramento.
- Fila: fase, progresso, tempo processado e total, cancelamento, retry e restauração após
  recarregar a página.
- Leitura: player de áudio ou vídeo, segmentos temporais clicáveis, texto integral,
  idioma, métricas e probabilidades opcionais.
- Exportação: criação e download de TXT, Markdown, SRT, WebVTT e JSON.
- Modelos: instalados e ausentes, com orientação explícita da CLI e sem download silencioso.

Jobs não terminais usam `EventSource`. A reconexão nativa envia o último ID recebido, e o
backend faz replay dos eventos posteriores persistidos no SQLite. O frontend anuncia
desconexão e reconexão, não cancela o job quando a página perde o stream e volta a consultar
a fila ao carregar novamente.

### Estados e acessibilidade

A interface representa carregamento, vazio, offline, erro, enfileirado, worker parado,
modelo ausente, cancelamento solicitado, concluído, falha recuperável e SSE em reconexão.
Falhas têm resumo em linguagem natural; detalhes técnicos sanitizados ficam recolhidos.

Foram implementados HTML semântico, landmarks, link para pular ao conteúdo, labels
associados, foco visível, navegação por teclado, diálogos nativos, regiões `aria-live` e
textos que não dependem somente de cor. `prefers-reduced-motion` desativa rolagem suave. O
layout foi ajustado para notebook em 1366×768 e para telas menores sem overflow horizontal
da página.

## Segurança e privacidade

- a aplicação continua restrita a `127.0.0.1` e a um worker por runtime;
- assets e chamadas usam a mesma origem, sem CORS wildcard ou URL externa;
- nenhuma entrada da interface é interpretada como caminho de arquivo do servidor;
- uploads permanecem sujeitos aos limites e à validação de conteúdo da API;
- mídia e exportações são acessadas exclusivamente por IDs gerenciados;
- dados retornados são inseridos no DOM como texto;
- erros não revelam stack trace nem caminhos físicos;
- modelos ausentes mostram o comando da CLI, mas não acionam rede;
- nenhum dado simulado foi incorporado ao produto.

## Testes automatizados

A suíte passou de 95 para 101 testes. Os novos testes usam banco e runtime temporários,
mídia WAV sintética, sonda controlada e worker desabilitado ou estado de fila preparado.
Eles cobrem:

- shell e assets locais com rede bloqueada;
- CSP estrita, ausência de CDN, `/api/docs` e `/redoc`;
- HTML semântico, labels, landmarks e regiões de anúncio;
- ausência de sinks de HTML inseguros;
- preservação de conteúdo hostil como texto;
- upload, pesquisa, fila, cancelamento, transcrição e exportação pelos contratos usados
  pela interface;
- Range para reprodução;
- `EventSource`, último ID, reconexão, seek do player e estado offline;
- estado real do worker e perfil recomendado no runtime;
- OpenAPI 0.6.0 restrito aos contratos `/api`.

Resultado final: `101 passed`.

## Inspeção real no navegador

A inspeção visual foi executada em navegador Chromium local contra um servidor real em
loopback e um runtime temporário fora do checkout. Somente conteúdo sintético foi usado.
Foram percorridos:

- painel vazio e com jobs;
- biblioteca vazia e preenchida por upload através da própria interface;
- criação e filtro de matéria;
- orientação de modelo ausente e diálogo de confirmação;
- job enfileirado, em andamento, cancelado, concluído e com falha recuperável;
- interrupção e restauração reais do servidor para observar o estado de reconexão SSE;
- busca, player, timestamps clicáveis, texto, métricas e exportação TXT;
- viewport de 1366×768 e viewport estreita;
- foco visível, link de salto e navegação por teclado;
- console do navegador sem erros após navegação limpa.

A inspeção encontrou e levou à correção de overflow horizontal em tela estreita, causado
pela combinação de conteúdo tabular e texto apenas para leitores de tela. Também levou à
redução da duplicação de títulos visuais e ao recolhimento de detalhes técnicos de falhas.
Nenhuma captura foi preservada, nenhum modelo foi baixado e nenhuma inferência sobre áudio
pessoal foi executada.

## Validação técnica

Foram executados com sucesso:

- testes direcionados da interface e API;
- suíte completa com diretório temporário fora do checkout sincronizado;
- Ruff e verificação de formatação Python;
- compilação de sintaxe Python;
- verificação de sintaxe dos três módulos JavaScript;
- `pip check`;
- geração e inspeção do OpenAPI;
- inicialização real em localhost e consulta de raiz, assets e API;
- navegação visual e por teclado em navegador real;
- busca por referências externas e sinks inseguros nos arquivos servidos;
- `git diff --check`.

O `PermissionError` transitório anteriormente associado a temporários sob o checkout não
reapareceu. A execução usou um `basetemp` exclusivo no diretório temporário do sistema,
preservando reprodutibilidade no Windows sem alterar OneDrive ou mover o repositório.

## Limitações preservadas

- a reprodução depende dos codecs disponíveis no navegador;
- a seleção da tela de leitura não é restaurada após recarga, embora jobs e eventos sejam;
- não existe visualizador HTML da especificação OpenAPI;
- CUDA e cargas longas continuam pendentes de validação real abrangente;
- não foram implementados frontend remoto, worker remoto, diarização, Ollama, microfone
  ao vivo ou Home Assistant.

A próxima fase prevista no roadmap é a Etapa 7. Ela não foi iniciada neste trabalho.
