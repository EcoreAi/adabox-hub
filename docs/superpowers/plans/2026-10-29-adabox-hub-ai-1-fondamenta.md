# adabox-hub — piano AI-1: fondamenta del modulo AI

**Spec:** `docs/superpowers/specs/2026-10-29-adabox-hub-modulo-ai-design.md`.
**Regole:** test prima, suite verde (SQLite e Postgres) che decide il commit, un commit per task con push,
collaudo del modulo `ai`.

### Task 1: infrastruttura — dipendenze, cifratura nel kernel, servizio ASGI per lo streaming — fatto
- `anthropic==1.17.0`, `uvicorn`, `uvicorn-worker` nei requirements; `core/cifratura.py` (Fernet da
  `AI_CHIAVE_CIFRATURA` o derivata da `SECRET_KEY`); `config/asgi.py`; servizio `stream` nel compose e
  instradamento nginx di `/ai/flusso/`.

### Task 2: catalogo — provider, modelli, profili, risoluzione del profilo, viste di gestione, dati iniziali
### Task 3: gateway — adattatori anthropic / openai_compat / finto, chunk ed errori normalizzati, retry e fallback, costi
### Task 4: motore — turni, log degli eventi, loop con strumenti di base, budget, battito, contesto con cache
### Task 5: streaming SSE e interfaccia della chat (invio, testo in diretta, stop, titoli automatici)
### Task 6: licenza firmata, tetto di spesa, consumi e dashboard
### Task 7: installazione, collaudo, README, verifica (anche dal vivo con una chiave API, se disponibile)
