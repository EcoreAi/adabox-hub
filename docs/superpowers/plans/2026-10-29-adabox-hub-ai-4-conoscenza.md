# adabox-hub — piano AI-4: conoscenza

**Spec:** `docs/superpowers/specs/2026-10-29-adabox-hub-modulo-ai-design.md` (fasi: proposta, sezione 6).
**Regole:** test prima, suite verde (SQLite e Postgres) che decide il commit, un commit per task con push,
collaudo del modulo `ai`.

**Esito atteso:** "cosa dice il contratto di Bianchi sul rinnovo?" — l'assistente trova il passaggio nei documenti,
nelle note del chatter o nei record che l'utente può vedere e risponde citando le fonti con i link.

**Decisioni:**
- Niente pgvector per ora: il server di sviluppo è su SQLite. Vettori a 256 dimensioni (EmbeddingGemma 2 accorciato,
  Matryoshka) salvati come float32 nel database e confrontati in Python: basta fino a decine di migliaia di
  frammenti. Il passaggio a pgvector cambierà solo `ai/conoscenza.py`, non gli strumenti.
- Ricerca ibrida: similarità semantica più parole chiave. Senza il servizio di embedding (URL vuoto o servizio
  giù) resta la ricerca per parole chiave: l'assistente funziona lo stesso.
- I permessi si applicano alla ricerca, non all'indice: l'indice è per azienda; ogni risultato si mostra solo se
  la `ModelView` della fonte lo fa vedere all'utente (cartelle dei Documenti comprese).
- L'URL del servizio è un'impostazione del modulo (`ai.url_embeddings`). Sul server di sviluppo i container
  dell'hub raggiungono `adabox-embeddings-1` sulla rete `adabox_ada_net` con un `docker-compose.override.yml` locale
  (esempio in `deploy/`), così il compose del repository non dipende da adabox.
- "Tabelle dati da Excel" come strumento di lettura dei fogli (righe filtrate), non come tabelle SQL: le tabelle
  interrogabili restano per dopo.

### Task 1: indice — estrazione del testo, frammenti, embedding — fatto (commit unico con il task 2)
- `pypdf` e `python-docx` nei requirements; testo da txt/md/csv, PDF, Word, Excel.
- Modello `Frammento` (fonte, record d'origine, azienda, titolo, testo, impronta, vettore).
- `ai/conoscenza.py`: frammenti da record delle `ModelView` (campi di testo, mai quelli sensibili), note e messaggi
  del chatter, documenti; solo i frammenti cambiati si ricalcolano, quelli spariti si tolgono. Voce `cron` ogni
  10 minuti e comando `manage.py ai_indicizza`.

### Task 2: ricerca con citazioni — fatto
- Strumento `cerca_conoscenza` (domanda, fonti, app): risultati numerati con titolo, link ed estratto, filtrati per
  permessi; prompt con l'obbligo di citare le fonti.
- `leggi_documento` (il testo di un documento, a pagine) e `leggi_foglio` (righe di un Excel/CSV, con filtro).

### Task 3: installazione, collaudo, README, verifica dal vivo — fatto
- Versione `ai` 1.3.0, override del compose sul server, URL del servizio, prima indicizzazione, prova dal vivo.
