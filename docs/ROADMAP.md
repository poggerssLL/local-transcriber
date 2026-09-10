# Roadmap

1. Fundação e persistência — concluída.
2. Biblioteca de mídia e exportadores — concluída.
3. Engine Faster Whisper e CLIs — concluída.
4. Fila persistente — próxima etapa.
5. API FastAPI e SSE.
6. Interface web.
7. Integração e validação real.
8. Futuras fases de diarização, Ollama, tempo real e Home Assistant.

Após a Etapa 3, duas validações reais antecipadas confirmaram o fluxo CPU `int8` com
modelo local, exportações e persistência. Os RTFs observados foram 1,612 e 0,4778, mas
duas amostras curtas não permitem garantir desempenho em uma gravação de 1h40. A projeção
de aproximadamente 47,8 minutos derivada do segundo RTF não é uma medição real de carga
longa. Isso não conclui a Etapa 7, que continua responsável pela integração e validação
abrangente do MVP.

Cada fase deve respeitar os invariantes de `PROJECT_CONTRACT.md` e incluir testes
proporcionais ao risco antes de avançar.
