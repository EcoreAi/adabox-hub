# adabox-hub — piano AI-6: specialisti

**Spec:** `docs/superpowers/specs/2026-10-29-adabox-hub-modulo-ai-design.md` (fasi: proposta, sezione 6).
**Regole:** test prima, suite verde (SQLite e Postgres) che decide il commit, un commit per task con push,
collaudo del modulo `ai`.

**Esito atteso:** "prevedi il fatturato dei prossimi 3 mesi" — la storia la costruisce il codice dai dati del
gestionale, i numeri della previsione li calcola il servizio locale, il grafico mostra mediana e fascia 10-90 %.

**Decisioni (dalla proposta, sezione 7):**
- Previsioni e decisore opzionali, spenti di default: gli strumenti compaiono solo con l'URL del servizio nelle
  impostazioni (`ai.url_forecast`, `ai.url_decider`).
- Timestral: il pacchetto è Apache 2.0, i pesi hanno una licenza propria (MIT modificata con limite di ricavi,
  secondo lo studio di adabox): va verificata prima dell'uso commerciale; alternativa Apache 2.0 da valutare
  (es. Chronos) cambiando solo il servizio.
- Decisore: senza esempi addestrati (backend `embed_sim`) le probabilità sono solo indicative (prova sul server:
  un ticket chiaramente urgente al 36 %). Sul server resta spento finché non ci sono teste addestrate.
- La serie storica esclude il periodo in corso (incompleto) e riempie di zeri i periodi senza dati; almeno 6
  periodi. Serie non negative: previsioni mai sotto zero.

### Task 1: previsioni e decisore come strumenti — fatto
- `ai/specialisti.py`: client dei servizi, serie storica dai dati con i permessi dell'utente (aggregazione nel
  database), previsione a quantili, grafico SVG (storia, mediana tratteggiata, fascia 10-90 %), decisore.
- Strumenti `previsione` (artifact grafico, CSV con i quantili, pagina con i dati di oggi) e `classifica`;
  strumenti visibili solo con il servizio configurato (`Strumento.disponibile`).
- Filtri con una data su campi data e ora: confronto sul giorno nel fuso locale.

### Task 2: installazione, collaudo, README, verifica dal vivo — fatto
- Versione `ai` 1.5.0; sul server solo le previsioni attive; prova dal vivo.
