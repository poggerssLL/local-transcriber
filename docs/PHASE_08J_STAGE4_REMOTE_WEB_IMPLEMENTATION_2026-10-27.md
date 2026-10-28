# Fase 8J — Etapa 4: implementação da interface remota

Data: 2026-10-27. Baseline de execução: `main` em `122d7026dd3a0ef3a9b61ac0b0b74631c0e037c4`, upstream `origin/main`. O checkout já continha alterações de outras fases; esta tarefa não fez commit nem push.

## Entrega

- `remote_web/`: HTML/CSS/JS isolados da UI local, com formulário, estados de envio, recuperação, progresso, job e transcrição. Os cinco assets usam CSP sem script/style inline, DOM com `textContent`/`createElement`, safe areas e controles móveis.
- SHA-256 total incremental em fatias de 8 MiB e digest Web Crypto individual por chunk; arquivo completo nunca é lido em uma única operação. Metadados versionados permitem reabrir a aba, conferir o hash total após reseleção e retomar pelo offset remoto. Áudio, transcrição, CSRF e cookie não são persistidos no armazenamento local.
- `remote_gateway.py`: shell em `/`, `/remote` e `/remote/`, assets em `/remote/assets/*`, e exceção restrita para GET de status resumable sem Origin com cookie, CSRF e Fetch Metadata válidos. `pyproject.toml` inclui os assets no wheel.
- Documentação viva atualizada em `PROJECT_STATE.md`, `ROADMAP.md`, `FOUNDATION.md` e `DECISIONS.md`.

## Validação executada

- `python -m pytest tests/test_remote_web.py tests/test_remote_resumable.py tests/test_remote_gateway.py tests/test_remote_gateway_stage2.py -q --basetemp=.test-tmp-remote-stage4-final`: **221 aprovados**, sendo 27 novos e 194 regressões existentes. Os dois arquivos originalmente citados somam 158 testes; os outros 36 estão em `test_remote_gateway_stage2.py`.
- SHA-256 incremental: vetores pequenos, fronteiras 55/56/63/64/65 bytes e fixture sintética de 200 MiB comparada com `hashlib`, lendo 25 fatias de 8 MiB.
- `ruff check` e `ruff format --check` em `remote_gateway.py` e `test_remote_web.py`: aprovados. `pip check`: aprovado. `git diff --check`: aprovado, com avisos existentes de normalização LF/CRLF.
- Wheel sintético mínimo construído com `uv build`, instalado em diretório temporário com `pip --target`; os cinco assets estavam presentes no pacote instalado. A construção usou uma cópia mínima de metadados e assets, não uma instalação integral do checkout.
- Detector Impeccable executado uma vez; não resolveu o caminho absoluto de CSS e apontou hierarquia tipográfica plana com base em tamanhos padrão, enquanto `styles.css` define `h1` de 2–3rem. Esse resultado não substitui inspeção visual em navegador.

## Limites e próximo gate

Os testes JS são sintéticos em Node e não executaram WebKit. Permanecem para a Etapa 5 a homologação no Safari/iPad físico, os headers reais do GET sem Origin, Content-Length do PATCH, suspensão/retomada com oscilação de rede, teclado/safe areas/VoiceOver e leitura/cópia de transcrição real em tailnet externa. O gate técnico desta implementação cabe ao coordenador; este relatório não afirma validação física.
