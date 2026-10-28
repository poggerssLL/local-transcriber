# Manutenção 8E — reparo reversível do ambiente

Data: 2026-10-06. Baseline publicada: 5cfc7b8, pacote 0.7.1, schema SQLite v4.

## Resultado e escopo

Erick autorizou corrigir os problemas diagnosticados. Dois diretórios de metadados
inválidos foram movidos de `.venv/Lib/site-packages` para
`.venv/maintenance-quarantine/20261006-metadata`, ignorado pelo Git:
`~ocal_transcriber-0.6.2.dist-info` e `~ocal_transcriber-0.7.0.dist-info`.
Os caminhos absolutos de origem e destino foram conferidos dentro do projeto,
links foram rejeitados e a inspeção Python não encontrou reparse tag nessas entradas.
O pacote ativo, arquivos de produção, dependências e fixtures preexistentes foram preservados.
Não houve reinstalação, exclusão, download, alteração de versão ou migração.

## Evidências atuais

- `python -m pip check`: exit 0, `No broken requirements found.`, sem aviso de distribuição inválida.
- `importlib.metadata.version('local-transcriber')`: 0.7.1; import do pacote aprovado.
- `git check-ignore` confirma que o manifesto de rollback está fora do versionamento.
- Pytest dos módulos `test_summarizer.py` e `test_api_summary.py`: 26 testes aprovados,
  com mocks/fixtures sintéticas e cache pytest desabilitado. Não é inferência real.
- A tentativa inicial com unittest não descobriu testes; somente o resultado pytest
  acima constitui validação dos módulos.

## Reversão e limites

O arquivo `ROLLBACK.txt` na quarentena registra os dois nomes. Para reverter,
confira novamente o confinamento e a ausência dos destinos e mova somente esses
metadados para o diretório original. Não restaure por cópia ampla da venv.
A evidência anterior de saúde do Ollama e sondagem CPU/CUDA permanece no relatório 8D;
esses checks não foram repetidos e não provam execução de transcrição ou sumarização.
A próxima validação funcional usa exclusivamente mídia e texto sintéticos,
modelos já existentes, temporários próprios e comparação explícita CPU/CUDA/Ollama.
A Etapa 9 não foi iniciada. Sem commit ou push nesta manutenção.
