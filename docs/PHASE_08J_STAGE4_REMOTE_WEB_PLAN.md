# Fase 8J — Etapa 4: plano técnico da interface web remota Safari/iPad

Data: 2026-10-27. Natureza: planejamento; implementação e homologação física pendentes.
Executor previsto: Codex Sol 6.0, esforço Medium, uma única etapa e um único escritor.

## 1. Base, limites e resultado esperado

Este plano usa o dossiê autocontido fornecido pelo coordenador. Código, documentos e testes do projeto não foram relidos, nem testes executados nesta tarefa. Os nomes de schemas, rotas, limites e os 194 testes das Etapas 0–3 são contratos informados pelo dossiê, ainda sujeitos à confirmação cirúrgica pelo implementador. Não se trata de evidência de execução no Safari.

Baseline observado: raiz `C:/Users/erick/OneDrive/Documentos/Local Transcriber`, branch `main`, HEAD `122d7026dd3a0ef3a9b61ac0b0b74631c0e037c4`, upstream `origin/main`. O checkout já continha numerosas alterações e arquivos não rastreados, inclusive `remote_gateway.py`, documentação e `tests/test_remote_resumable.py`; preservar integralmente esse trabalho. O único arquivo criado por este planejamento é este plano. Nenhum commit/push está autorizado.

Entregar uma interface HTML/CSS/JS pura para selecionar matéria e áudio, enviar com retomada, acompanhar o job e ler/copiar sua transcrição. Servir tudo pela mesma origem HTTPS privada do Tailscale Serve, com gateway em `127.0.0.1:8766`. Manter Core SQLite schema v4, uploads legados, protocolo resumable, isolamento de identidades e bloqueio de Funnel. Não alterar o motor Faster Whisper, baixar modelos, configurar Serve, adicionar nuvem, frameworks, CDN, service worker ou File System Access API.

A Etapa 4 produz implementação e evidência sintética. A Etapa 5 permanece responsável por iPad físico, Safari, tailnet externa, fechamento da aba, retomada e leitura de transcrição real.

## 2. Arquivos, responsabilidades e rotas

| Arquivo | Responsabilidade |
|---|---|
| `src/local_transcriber/remote_web/index.html` | Shell semântico, formulário, progresso, recuperação e resultado; referências externas absolutas |
| `src/local_transcriber/remote_web/styles.css` | Tokens próprios mínimos, responsividade, acessibilidade, estados e safe areas |
| `src/local_transcriber/remote_web/app.js` | Máquina de estados, hashing incremental, seleção/reseleção, persistência e coordenação assíncrona |
| `src/local_transcriber/remote_web/api.js` | Cliente HTTP da API remota, sessão/CSRF em memória, Retry-After, fila de leitura e métodos tipados por contrato |
| `src/local_transcriber/remote_web/dom.js` | Construção segura do DOM, formatação e renderização; nenhuma dependência da UI desktop |
| `src/local_transcriber/remote_gateway.py` | Servimento autenticado dos estáticos e exceção estrita do GET descrita na seção 3 |
| `tests/test_remote_web.py` | Contratos HTTP, segurança, ativos e cenários sintéticos da UI |

Não importar `web/app.js` nem expor assets da UI local. `app.js` importa somente `./api.js` e `./dom.js`. Manter o SHA-256 incremental como unidade exportável/testável em `app.js`, com bootstrap protegido por existência de `document`; não criar sexto módulo sem necessidade justificada.

No factory do gateway, definir `REMOTE_WEB_ROOT = Path(__file__).with_name('remote_web')` e registrar:

- `GET /`: `FileResponse(REMOTE_WEB_ROOT / 'index.html', media_type='text/html')`.
- `GET /remote`: o mesmo shell, sem redirecionamento e sem novo domínio.
- `GET /remote/`: o mesmo shell, para links com barra final.
- `app.mount('/remote/assets', StaticFiles(directory=REMOTE_WEB_ROOT, html=False), name='remote-web-assets')`.

HTML: stylesheet `/remote/assets/styles.css`; script externo `type='module'` em `/remote/assets/app.js`. Não montar `/remote` como diretório, pois capturaria `/remote/v1`. Não criar fallback SPA que responda HTML para APIs ou assets inexistentes. Diretório montado contém somente os cinco arquivos públicos; nenhum caminho de runtime, banco, mídia ou documentação. Garantir que os assets entrem na distribuição instalada, verificando configuração de package data e instalando um wheel temporário isolado na validação. Alterar configuração de empacotamento somente se faltar essa inclusão.

O middleware de fronteira deve envolver também `FileResponse`, `StaticFiles`, 404 e redirecionamentos: loopback, Host único permitido, login Tailscale único permitido e rejeição de qualquer `tailscale-funnel-request`. HTML e assets não precisam de cookie de sessão, mas sempre precisam da identidade do proxy. Navegação inicial sem Origin e com `Sec-Fetch-Site: none` permanece válida. Aplicar os mesmos headers de segurança/no-store aos arquivos; confirmar MIME de CSS e módulos JS sob `nosniff`.

## 3. Correção necessária: Origin no GET resumable

Não implementar a afirmação do dossiê de que `fetch(..., {mode: 'cors'})` força Origin em GET da mesma origem. Ela não é garantida pelo navegador. `Origin`, `Host`, `Cookie`, `Content-Length` e `Sec-Fetch-*` são administrados pelo navegador e não devem ser escritos pelo JS. Referência normativa consultada: [Fetch Standard — Origin](https://fetch.spec.whatwg.org/#append-a-request-origin-header). Esta consulta externa verificou apenas a semântica do navegador; não revisou o repositório.

Decisão proposta para implementação: preservar a via atual com Origin válido e acrescentar uma única via autenticada de leitura, sem mudar mutações nem a regra geral `is_resumable`:

1. Somente método `GET` e caminho exato `/remote/v1/uploads/resumable/{upload_id}`, com ID de 32 hexadecimais e sem subcaminhos, podem usar a exceção.
2. A exceção só vale quando Origin está **ausente**. Origin inválido, `null`, duplicado ou divergente continua rejeitado, mesmo com as demais provas.
3. Exigir cookie `lt_remote_session` válido e `x-csrf-token` único, válido, não expirado e verificado pelo signer existente contra a mesma identidade/sessão. Não apenas testar presença do token.
4. Exigir `Sec-Fetch-Site: same-origin` e `Sec-Fetch-Mode: cors`, ambos únicos. Não aceitar `none`, `same-site`, `cross-site`, ausentes ou duplicados nessa exceção. O JS usa `mode: 'cors'`, `credentials: 'same-origin'` e envia `x-csrf-token` nesse GET.
5. Executar antes as validações globais de binding, Funnel, Host e identidade. Manter ownership/IDOR, expiração e rate limit de leitura do handler. Não converter o GET em mutação nem cobrar bucket de mutação.
6. Todas as outras rotas resumable e métodos conservam Origin obrigatório. GETs antigos sem Origin e sem essa combinação continuam em 403; requisições existentes com Origin permitido conservam o comportamento anterior.

Esta é uma alteração explícita e limitada do contrato de fronteira, não um relaxamento geral de Origin. Acrescentar testes negativos combinando cada prova ausente/inválida. Não editar os 194 testes existentes para acomodar a mudança: executar todos intactos. Se algum teste existente exigir 403 para a combinação exata agora autorizada, há conflito real de contrato: interromper e levar ao coordenador antes de ampliar a exceção ou alterar regressões. O dossiê não permite prometer antecipadamente que não existe tal teste.

Safari sem Fetch Metadata compatível não recebe bypass silencioso: exibir incompatibilidade de consulta/retomada e registrar como limite para a Etapa 5. Confirmar no WebKit automatizado e depois no Safari físico os headers gerados; não simulá-los apenas em mocks e declarar suporte real.

## 4. Bootstrap, cliente HTTP e seleção de matéria

`RemoteApi` usa somente URLs relativas sob `/remote/v1`, `credentials: 'same-origin'`, `mode: 'cors'`, `cache: 'no-store'` e cancelamento por AbortController. Rejeitar URLs absolutas externas, redirects de API e respostas com schema incompatível. Não tentar enviar `Tailscale-User-Login`; o proxy é sua única fonte. Não habilitar CORS externo.

Sequência de abertura:

1. Renderizar shell e estado `bootstrapping`, desabilitando mutações.
2. `GET /remote/v1/session`: guardar `csrf_token`, `expires_at` e `max_upload_bytes` apenas em memória. O navegador recebe cookie Secure, HttpOnly, SameSite=Strict, Path=/remote/v1. Não usar `document.cookie` nem persistir CSRF.
3. `GET /remote/v1/subjects`: zero matérias bloqueia envio com explicação; uma matéria é selecionada automaticamente e exibida; múltiplas exigem escolha explícita com opção inicial vazia. Nunca selecionar arbitrariamente a primeira.
4. Ler/validar recuperação do localStorage e consultar estado remoto conforme seção 7. A presença de job permite acompanhamento mesmo sem arquivo selecionado.

Enviar `x-csrf-token` nas mutações e no GET resumable da exceção. Renovar sessão antes da expiração; em 403 só renovar uma vez se o erro reconhecido for de cookie/CSRF expirado. Rejeição de identidade, Origin, Funnel ou Host é terminal e não deve gerar loop de login. Após renovação, reconciliar operação incerta antes de retransmitir. A rotação não deve alterar chave de idempotência nem criar outro upload/job.

Formulário: arquivo único `.m4a,.aac,.mp3,.wav`, matéria, título opcional até 500 caracteres e data local `YYYY-MM-DD` opcional. `accept` é orientação, não validação. Exigir tamanho > 0 e <= `max_upload_bytes`, nome <= 255 caracteres, normalizado NFC e sem separadores; preservar o nome original para comparação de reseleção e enviar o nome NFC validado. Não inferir MIME confiável pela extensão. Não enviar campos desconhecidos (`extra='forbid'`); opcionais ausentes devem ser omitidos ou null conforme schema, data vazia nunca enviada como string vazia.

## 5. Hashing limitado a 8 MiB por fatia

O hash total é obrigatório **antes** do init. Não usar `file.arrayBuffer()` no arquivo inteiro, não concatenar buffers e não calcular SHA-256 da concatenação dos hashes dos chunks: isso não é SHA-256 do arquivo.

Algoritmo em duas passagens:

1. Fixar fatia de 8.388.608 bytes. Para cada `start`, ler `await file.slice(start, min(start + 8388608, size)).arrayBuffer()`.
2. Alimentar o SHA-256 incremental puro com os bytes originais. Implementação própria pequena, sem pacote externo: oito palavras de estado Uint32, 64 constantes, mensagem expandida de 64 palavras, compressão por blocos de 64 bytes, rotações e somas modulo 2^32. Conservar apenas resto < 64 bytes e contador total; finalizar com bit 1, zeros e comprimento de 64 bits big-endian. O padding só é aplicado uma vez, no fim do arquivo.
3. Para a mesma fatia calcular `crypto.subtle.digest('SHA-256', buffer)` e reter somente o hexadecimal de 64 caracteres e seus limites em uma tabela em memória. Hash total incremental deve corresponder aos bytes do arquivo completo, incluindo último chunk parcial.
4. Liberar referências de buffer antes da próxima leitura e ceder à fila de eventos entre fatias; atualizar progresso “Verificando arquivo” e verificar cancelamento/geração. Não acumular Promises de digest paralelas. Pico de memória deve depender da fatia, não de 200 MiB; cópias internas temporárias da Web Crypto podem existir.
5. Finalizar total em hexadecimal minúsculo e validar 64 hexadecimais. Na segunda passagem de envio ler somente a fatia do offset confirmado e usar o hash daquele chunk. Recalcular digest se o offset não corresponder à tabela; nunca usar hash de outra fatia.

Validar implementação com vetores SHA-256 conhecidos (vazio, `abc`, mensagem longa), comprimentos 55/56/63/64/65 bytes, entradas binárias e fatias diferentes. Comparar total incremental com digest nativo em fixtures pequenas e com hashlib em fixture sintética de 200 MiB. Não usar o teste grande para justificar alocar 200 MiB no navegador. Sem Web Crypto/HTTPS, bloquear envio com mensagem clara; não inventar fallback criptográfico inseguro.

## 6. Upload sequencial, idempotência e erros recuperáveis

Criar e persistir uma chave de idempotência aleatória por intenção de upload **antes** do init. `POST /remote/v1/uploads/resumable` leva `Idempotency-Key`, `X-Expected-Sha256`, CSRF e JSON `{filename,total_bytes,enqueue:true,subject_id,title?,lesson_date?}`. A resposta 200/201 fornece ID, offset, chunk_bytes, expiração e estado. Validar hash/tamanho contra a intenção; exigir `chunk_bytes == 8388608` nesta versão. Persistir upload_id imediatamente. Timeout do init repete a mesma intenção/chave, nunca cria uma chave nova automaticamente.

Loop único, sem uploads paralelos:

1. Consultar estado se houve interrupção; considerar `current_offset` remoto a autoridade. Validar inteiro 0 <= offset <= total, hash e tamanho. Offset intermediário não alinhado ao chunk deve bloquear/reconciliar segundo contrato, nunca arredondar para baixo nem pular bytes.
2. Se `uploading` e offset < total, enviar `PATCH /remote/v1/uploads/resumable/{id}` com `Upload-Offset`, `X-Chunk-Sha256`, CSRF, `Content-Type: application/octet-stream` e corpo ArrayBuffer/Blob de exatamente uma fatia. O navegador gera Content-Length. Confirmar no Safari real o transporte desse corpo com tamanho conhecido; não usar ReadableStream de tamanho desconhecido.
3. Em 204 ler `Current-Offset` e verificar avanço exato pelo tamanho transmitido; persistir e renderizar apenas bytes confirmados. A porcentagem não deve anunciar dados apenas lidos ou ainda em trânsito.
4. Em falha de rede, timeout, retorno de background ou 409 de offset, suspender PATCH e fazer GET de reconciliação antes de qualquer retransmissão. Se PATCH foi confirmado no servidor mas resposta se perdeu, o GET evitará duplicar bytes.
5. `online`, `pageshow` e `visibilitychange` disparam uma única reconciliação quando visível e apropriado, nunca novos loops concorrentes. `navigator.onLine` é dica, não prova. Safari pode suspender timers; não prometer upload em background.

429 é estado normal de espera: ler Retry-After (segundos ou data HTTP), esperar pelo menos o prazo, mostrar contagem “Aguardando limite do servidor; envio será retomado” e tentar novamente a mesma operação/offset. Sem header válido, usar fallback de 12 segundos para mutações. O burst é de cinco **mutações**, incluindo init/finalize, não cinco chunks. Não alterar limites do gateway para esconder o problema.

503 `finalization_busy` ou indisponibilidade transitória: respeitar Retry-After, fallback 2 segundos, informar espera. Quando a resposta/estado for ambíguo, reconciliar antes de repetir mutação; Retry-After é limite mínimo. Todos os timers precisam ser abortáveis. Backoff de rede: 2, 4, 8, 16, até 30 segundos, com jitter apenas adicional; após tentativas consecutivas limitadas, manter sessão recuperável e oferecer retentar, sem descartar manifesto. 429/503 explícitos podem continuar aguardando enquanto a intenção estiver ativa, sem loop apertado.

Tratar 400/413/415/422 como erro do arquivo/parâmetros; 404 como sessão ausente ou não acessível, sem revelar ownership; expired/aborted como impossibilidade de continuar esse ID. `409 import_outcome_unknown` é bloqueio de reconciliação humana: não recriar upload nem reenfileirar automaticamente. Não transformar todo 409 em retentativa. Não repetir indiscriminadamente mutações após 500.

## 7. Persistência e retomada após fechamento

Uma chave versionada, por exemplo `lt.remote.pending.v1`, contém JSON validado:

```json
{"version":1,"upload_id":null,"expected_sha256":"64 hex","filename":"aula.m4a","total_bytes":123,"subject_id":"uuid","title":null,"lesson_date":null,"job_id":null,"recording_id":null,"init_key":"random","job_key":null,"confirmed_offset":0,"expires_at":null}
```

Guardar também `raw_filename` se NFC alterou o nome. `init_key` deve sobreviver à janela de resposta perdida antes de existir upload_id. Persistir metadados após cada transição confirmada. Nunca persistir File, bytes, cookie, CSRF, login, áudio ou texto transcrito. Explicar que nomes/títulos ficam neste navegador e disponibilizar “Esquecer acompanhamento”, que remove apenas a chave local e não apaga dados do servidor. Tratar JSON inválido, versão desconhecida, quota/security error e armazenamento privado indisponível sem crash; avisar quando a recuperação durável não estiver disponível.

No reload: bootstrap sempre precede consultas. Se existir job_id válido, acompanhar job imediatamente e sem arquivo. Se só upload_id, consultar GET remoto: `assembling`/`importing` dispensam arquivo e entram no polling de montagem; `completed` recupera IDs e acompanha job; `uploading` exige arquivo se bytes faltarem; offset == total permite finalizar sem reseleção. IDs recuperados localmente não autorizam acesso; servidor sempre revalida ownership. Falha de matéria removida da allowlist não autoriza substituir matéria silenciosamente.

Sem File em memória e offset < total, mostrar nome, tamanho, offset confirmado e controle nativo “Selecionar novamente o mesmo arquivo”. Validar **todos**: nome original (e representação NFC enviada), tamanho e SHA-256 total recalculado em streaming. Só depois de igualdade estrita consultar novamente estado e offset e liberar PATCH. Mesmo nome/tamanho com conteúdo diferente deve falhar; verificar só primeiro chunk é proibido. Matéria/título/data da sessão ficam bloqueados para evitar divergência com manifesto já criado.

Com File ainda referenciado e oscilação de rede, a retomada é automática por GET/offset. Após fechamento, não prometer recuperação automática dos bytes: Safari perde a referência File. Evitar duas abas transmitindo: usar um lease local com owner/expiração, renovado enquanto ativo, e evento `storage` para colocar a segunda aba em observação; tratar como coordenação de UX, não segurança. Corridas residuais são resolvidas pelo offset do servidor. Não iniciar novo upload ao detectar mera expiração do lease.

## 8. Finalização e job durável

Com offset == total, `POST /remote/v1/uploads/resumable/{id}/finalize`, `X-Expected-Sha256`, CSRF, `Content-Type: application/json`. O enfileiramento já foi solicitado por `enqueue:true` no init. **Não acrescentar campos não previstos ao finalize**: o dossiê não inclui seu request schema. O implementador deve confirmar apenas esse handler/modelo e enviar seu corpo exato (objeto vazio somente se aceito), sem inventar `{enqueue:true}` no finalize.

202 com Retry-After:2 significa montagem/importação pendente. Esperar `max(3s, Retry-After)` antes de GET de status. `assembling`/`importing` continuam no mesmo ciclo até completed; não chamar finalize repetidamente para fazer polling. Se finalize recebe 503 busy e ainda não foi aceito, respeitar espera e reconciliar estado, então repetir apenas se continuar uploading com todos os bytes. GET de status pode continuar retornando 200 com estado intermediário; é o `state` que decide, não somente HTTP.

Em completed, persistir recording_id/job_id antes de renderizar próximo estado. Se job_id vier, nunca criar outro job. Se recording_id existir sem job_id, verificar queue_state/error_code: não duplicar enfileiramento que esteja pendente ou ambíguo. A alternativa explícita `POST /remote/v1/jobs` só pode ser usada se o contrato demonstrar que não houve enfileiramento (fluxo deliberadamente iniciado com enqueue:false, por exemplo); enviar `{recording_id}` e Idempotency-Key estável persistida antes do POST. Se enqueue:true concluir sem job e sem explicação inequívoca, exibir recuperação pendente, consultar novamente com limite e depois solicitar reconciliação, sem adivinhar.

`GET /remote/v1/jobs/{job_id}`: ciclo serial de pelo menos 3 segundos, iniciado após terminar a resposta anterior. Exibir status/phase, progress_percent quando disponível e segundos processados. Sem percent válido, usar indicador indeterminado; não inventar progresso. pending/running continuam; failed/cancelled encerram polling e mostram erro via texto; succeeded com transcript_available permite buscar `GET /remote/v1/jobs/{job_id}/transcript`. Se succeeded ainda sem transcript, aguardar de forma limitada e informar pendência; não buscar transcrição em loop rápido.

Centralizar todo GET de API em uma fila que mantém intervalo mínimo global de 3 segundos (bootstrap, reconciliação, job e transcript incluídos), além de cooldown de 429 compartilhado. Uma única aba acompanha uma atividade principal; ao transitar de upload/montagem para job cancelar o polling antigo. Não executar dois pollings a 3 segundos que somem 0,66 req/s. Retry-After maior sempre prevalece, inclusive sobre gatilhos de visibilidade.

Exibir texto completo e segmentos com início/fim formatados por nós seguros. O botão copiar chama `navigator.clipboard.writeText(transcript.text)` em gesto do usuário; se rejeitado, permitir selecionar/copiar manualmente em campo somente leitura. Não persistir transcrição no localStorage. Não usar rota `/recordings/{recording_id}/transcript`: ela não existe no gateway.

## 9. Máquina de estados, cancelamento e ergonomia

Estados explícitos: bootstrapping → ready/recovery → hashing → initializing → uploading ↔ waiting-rate/network → finalizing → assembling/importing → tracking-job → succeeded; erros recuperáveis conservam manifesto; aborted/expired/import-outcome-unknown têm mensagens próprias. `needs-file` só bloqueia envio de bytes, jamais acompanhamento de job ou montagem.

Usar contador de geração e AbortController conforme ADR-032 dentro dos módulos isolados: nova intenção invalida a anterior; após cada await, digest, timer ou fetch validar geração antes de alterar DOM/localStorage. Separar cancelamento de observação de cancelamento remoto. “Pausar envio” interrompe trabalho local e conserva upload; `DELETE` remoto só em ação explícita de descartar sessão e com CSRF, Origin e espera por rate limit. Fechar a aba não envia DELETE. Abort de fetch não prova que o servidor abortou operação; sempre reconciliar ao voltar.

Antes de implementar UI, consultar a skill local `.agents/skills/impeccable/SKILL.md`; este planejamento usa apenas as diretrizes consolidadas no dossiê, sem alegar ter relido a skill. Superfície utilitária: título, formulário, cartão de atividade e leitura; sem navegação desktop, fontes externas ou decoração que esconda estado.

- Meta viewport `width=device-width, initial-scale=1, viewport-fit=cover`; permitir zoom.
- Padding com base de espaçamento + `env(safe-area-inset-top/right/bottom/left, 0px)`; evitar controles presos atrás de teclado/Home indicator.
- Botões/seletores >= 44×44px; inputs/selects/textarea >= 16px; fonte de sistema e layout de coluna única em telas pequenas, largura de leitura contida no iPad.
- Labels associados, instruções de recuperação próximas ao seletor, foco visível, contraste >= 4,5:1, estados disabled/active perceptíveis, sem depender de hover ou só de cor.
- `role='status'`, `aria-live='polite'`, `aria-atomic='true'` para mensagens; limitar anúncios por chunk/fase para não saturar VoiceOver. `progress` nativo com value/max, sem style inline para largura.
- Respeitar prefers-reduced-motion. Nenhum controle depende de arrastar/soltar ou hover.

## 10. DOM, CSP e privacidade

Preservar integralmente a CSP do gateway: `default-src 'none'; base-uri 'none'; connect-src 'self'; font-src 'self'; form-action 'self'; frame-ancestors 'none'; img-src 'self'; media-src 'self'; object-src 'none'; script-src 'self'; style-src 'self'`. Manter X-Content-Type-Options:nosniff, X-Frame-Options:DENY, Referrer-Policy:no-referrer e Cache-Control:no-store em sucesso e erros.

Proibir scripts/styles inline, handlers `onclick=`, atributos style, `.style`, innerHTML, outerHTML, insertAdjacentHTML, document.write, eval e Function construtor. Criar nós via createElement, textContent, append e replaceChildren; classes CSS controlam aparência. Nomes, títulos, mensagens do servidor e transcrições são texto não confiável. Não montar links de URLs retornadas sem validação; IDs são codificados e validados antes de compor caminhos.

Não incluir logs com CSRF, cookies, áudio, nomes/títulos ou texto transcrito. `no-store` não torna localStorage efêmero nem apaga clipboard; a UI deve informar persistência local de metadados e oferecer limpeza. “Esquecer” cancela observadores antes de remover a chave para evitar recriação por resposta tardia.

## 11. Matriz automatizada — tests/test_remote_web.py

Separar contratos HTTP FastAPI (cliente sintético + stubs do Core) dos cenários JS em navegador automatizado. O arquivo pytest pode orquestrar runner já disponível; se não houver navegador/runner, negociar dependência apenas de desenvolvimento e documentar execução explícita. Não declarar comportamento JS coberto por simples busca textual. Não introduzir dependências de produção ou download silencioso de navegador/modelo. WebKit automatizado é aproximação, não prova de Safari iPad físico.

| Grupo | Casos e asserções mínimas |
|---|---|
| Servimento | `/`, `/remote`, `/remote/`, cinco assets com Host/login válidos, navegação sem Origin; MIME correto; módulos importam paths existentes; nenhum acesso ao Core para shell |
| Fronteira web | Parametrizar shell/CSS/JS: Funnel inclusive header vazio, login ausente/inválido/duplicado, Host proibido/duplicado, binding inválido e fetch-site cross-site; nenhum corpo estático em resposta negada |
| Isolamento | 404 de asset inexistente, traversal e nomes codificados; `/remote/v1` continua API; nenhum fallback HTML para API/asset; UI local e dados runtime não expostos |
| Headers/CSP | CSP exata, no-store/nosniff/DENY/no-referrer em HTML/assets/erros; sem relaxar unsafe-inline/unsafe-eval; nenhum CDN/inline script/style/handler; proibições DOM em todos os cinco arquivos |
| GET sem Origin | Via antiga com Origin válido preservada; sem Origin ordinário continua 403; nova via exige cookie+CSRF válido+same-origin+cors; testar cada prova inválida/ausente/duplicada, token expirado, identidade trocada, Origin null/inválido, IDs de outra identidade e path/método fora do alvo |
| Bootstrap | Cookie HttpOnly Secure Path=/remote/v1, CSRF somente em memória; 0/1/N matérias; matéria removida; sessão expirada e renovação única; max_upload_bytes controla limite |
| Hash | Vetores conhecidos, limites de padding/blocos/fatias, último chunk parcial, resultado equivalente a hashlib; instrumentar slices <=8 MiB e ausência de leitura integral; cancelar hashing impede init |
| Protocolo | Init/headers/schema exatos; PATCH sequenciais com bytes e hashes corretos; avanço pelo Current-Offset; digest total não é digest de hashes; 200/201/204 tratados corretamente |
| Rate limit | Fixture > 32 MiB esgota burst init+quatro PATCH; 429 não perde File/offset/chave; timer respeita Retry-After; 503 com 2s; relógio falso, sem espera real de minutos; leitura agregada nunca > uma/3s |
| Rede | PATCH aceito com resposta perdida → GET confirma offset → próximo chunk correto; queda antes de commit; 409 de offset; reconexões/visibilidade não duplicam loops; cooldown não é ignorado por evento online |
| Reload/reseleção | Só metadados persistem; job/montagem sem File continuam; upload pede arquivo; mesmo nome/tamanho mas hash diferente bloqueia; hash correto retoma offset remoto; total completo dispensa arquivo |
| Durabilidade | Timeout no init repete chave original; reload antes de resposta de job não duplica criação; localStorage indisponível/corrompido; duas abas/lease e corrida de offset; esquecer não reaparece via resposta obsoleta |
| Finalização | 202/Retry-After → GET → completed com IDs; sem polling por POST; busy503; estados importing/expired/aborted; import_outcome_unknown bloqueia duplicação; enqueue:true não gera POST jobs extra |
| Job/transcrição | pending/running/succeeded/failed/cancelled; polling >=3s; transcript_available, segmentos em texto, clipboard sucesso/falha; nunca rota por recording_id; retomada sem reseleção |
| Segurança DOM | Payloads com tags/event handlers em matéria/nome/erro/transcrição ficam literais; nenhuma execução; capturar violações CSP reais no navegador |
| Async/acessibilidade | Resposta atrasada não sobrescreve intenção nova; abort não vira erro falso; labels/live region/foco/44px/16px/safe areas/reduced motion; viewport retrato/paisagem e teclado via verificação manual posterior |
| Distribuição | Wheel instalado isoladamente entrega todos os assets sem depender da raiz do checkout |

Manter os 194 testes das Etapas 0–3 intactos e executar o conjunto original incluindo `tests/test_remote_resumable.py`, usando nomes atuais confirmados pelo implementador. Quantidade é referência do dossiê: registrar número efetivamente coletado e discrepâncias, sem manipular contagem. Novos testes não substituem regressões. Nada disso foi executado na tarefa de planejamento.

## 12. Ordem de implementação, documentação e gates

1. Confirmar baseline/instruções e consultar somente símbolos indispensáveis: boundary, signer, finalize request/handler, factory de app, empacotamento e fixtures de regressão. Conferir divergências do dossiê antes de escrever. Consultar Graphify para relações quando aplicável, Serena para símbolos; sem ler módulos grandes integralmente.
2. Implementar servimento isolado, inclusão no pacote e exceção estrita de GET; validar primeiro fronteira e regressões existentes. Não deixar uma UI cujo upload funciona mas cuja retomada é impossível no navegador.
3. Implementar cliente, fila de leitura, persistência, hash e máquina de estados; depois formulário, recuperação e transcrição. Exercitar fluxos sintéticos com relógio controlado e rede simulada.
4. Verificar novo conjunto, regressões das Etapas 0–3, Ruff check, Ruff format --check, pip check e git diff --check; registrar comandos, resultados, ambiente e limitações reais. Usar git diff --stat e revisão seletiva de código; não despejar diff completo de Markdown. Revisar escopo para não atribuir mudanças anteriores a esta etapa.
5. Atualizar `docs/PROJECT_STATE.md` e `docs/ROADMAP.md` ao concluir implementação funcional; `FOUNDATION.md` para pacote/rotas e `DECISIONS.md` para exceção de Origin se confirmada como mudança arquitetural. Atualizar KNOWN_ISSUES apenas se houver nova limitação. Não alterar migrations/schema/Core para atender UI.
6. Entregar relatório durável com arquivos efetivamente alterados, testes reais, limitações e roteiro físico pendente. Não iniciar homologação externa, commit ou push implicitamente.

Aceite da Etapa 4: shell/assets privados sob fronteira completa e CSP; SHA-256 correto com memória por fatia; 429/503 tratados; upload/retomada/finalização/job/transcrição cobertos sinteticamente; regressões originais preservadas; wheel inclui UI; documentação atualizada. Se qualquer gate falhar, relatar bloqueio concreto em vez de concluir etapa.

Roteiro reservado à Etapa 5: Core/notebook ativo, remote-session iniciado por operador, Safari em iPad físico na tailnet via rede externa; upload M4A, oscilação de sinal com aba aberta, fechamento e reseleção estrita, montagem/job recuperados sem arquivo, leitura/cópia de transcrição e tentativa de acesso por Funnel/identidade não permitida. Confirmar headers GET, corpo PATCH com Content-Length, suspensão de background, safe areas/teclado/VoiceOver e conteúdo final. Nenhum teste sintético autoriza afirmar essas condições como homologadas.
