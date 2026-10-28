# adabox-hub — modulo AI ("il cervello"): spec

Data: 2026-10-29
Stato: approvato (proposta e decisioni in `2026-10-28-adabox-hub-modulo-ai-proposta.md`; l'utente ha autorizzato
la realizzazione in autonomia)

## Obiettivo

Un assistente agentico dentro adabox-hub che conosce e usa tutte le app installate con i permessi di chi lo usa:
- legge, analizza e risponde con tabelle e grafici;
- crea e modifica record con conferma;
- pianifica attività ricorrenti;
- cerca nei documenti;
- usa modelli diversi per compiti diversi (cloud o locali);
- costa poco e si vende con licenza.

## Principi

1. **Il modello sceglie e formula; numeri, permessi, scritture, grafici e verifiche li fa il codice.**
2. **Log degli eventi in sola aggiunta** come unica fonte del contesto del modello: audit, ripresa, replay,
   compatibilità con il "preserved thinking" dei modelli Claude 5.x (i blocchi di ragionamento si rimandano
   invariati, la storia non si riscrive mai).
3. **Cache del prefisso**:
   - prompt di sistema byte-stabile e strumenti in ordine deterministico, con un punto di cache dopo di essi;
   - fatti dinamici (data, azienda, pagina) in un messaggio dopo il prefisso.
4. **Fallire in sicurezza**:
   - budget per turno (passi, token, secondi, costo);
   - ogni chiamata a uno strumento riceve un risultato, sintetico se interrotta;
   - nessuna scrittura senza conferma esplicita dell'utente nell'interfaccia.
5. **Nessuna memoria di processo**: lo stato vive nel database (turni, eventi, battito del turno in corso).

## Architettura

- App `addons/ai` (esistente: chat, cronologia, limitazione a un'app) diventa il modulo completo, versione 1.0.
- **Gateway** (`ai/gateway/`):
  - adattatori `anthropic` (SDK ufficiale `anthropic` 1.17), `openai_compat` (HTTP con `httpx2`: OpenAI,
    OpenRouter, Ollama, vLLM, Gemini nella modalità compatibile) e `finto` (test e sviluppo);
  - chunk normalizzati (`Testo`, `Ragionamento`, `ChiamataStrumento`, `Uso`, `Fine`) ed errori normalizzati
    (`ErroreModello(codice, riprovabile, attesa)`);
  - retry con backoff; fallback lungo la catena del profilo solo prima del primo token.
- **Catalogo** (database):
  - `Provider`: tipo, URL, chiave API cifrata con Fernet, per azienda o globale;
  - `Modello`: id API, capacità, contesto, output massimo, prezzi per milione di token (input, output, scrittura
    e lettura cache), locale, residenza UE;
  - `Profilo`: compito, app e azienda facoltativi, catena ordinata di modelli, effort, temperatura dove
    ammessa. Compiti: `chat`, `titoli`, `riassunti`, `pianificate`, `classificazione`.
  - Si sceglie il profilo più specifico tra azienda+app, app, azienda e generale.
- **Motore** (`ai/motore/`):
  - `Turno` (conversazione, stato, budget, costo, battito, errore) ed `Evento` (turno, numero progressivo,
    tipo, dati JSON);
  - loop: contesto dagli eventi → gateway → eventi di testo e strumenti → esecuzione degli strumenti
    (le letture in parallelo, le scritture come barriera) → ripetizione fino a fine, budget o errore;
  - il turno gira in un thread del processo che riceve il messaggio (`AI_TURNI_SINCRONI` per i test) o nel
    worker del kernel per le esecuzioni pianificate. Un turno senza battito da 90 secondi è "interrotto".
- **Streaming**: `GET /ai/flusso/<turno>/` (Server-Sent Events) segue il log degli eventi del turno. Il generatore
  è asincrono sotto ASGI e sincrono sotto WSGI (Django 5.2 bufferizza i tipi sbagliati). In produzione un
  servizio `uvicorn` (stessa immagine, `config.asgi`) serve solo `/ai/flusso/`, accanto a gunicorn che resta
  WSGI per il resto.
- **Strumenti** (`ai/strumenti/`): registro con schema in ingresso, livello di rischio (`lettura`, `scrittura`,
  `irreversibile`), `concorrente`, timeout. In AI-1: strumenti di base (data e ora, app disponibili). In AI-2:
  generatore dalle `ModelView` e strumenti dichiarati nei manifest.
- **Licenza**: file JSON firmato Ed25519 con le chiavi fidate del kernel; contiene cliente, scadenza, funzioni,
  numero di utenti. Tetto di spesa mensile per azienda (parametro), con avviso all'80% e blocco morbido al 100%.
  Senza licenza valida l'assistente risponde che il modulo non è attivo; `AI_LICENZA_SVILUPPO=True` la simula
  in sviluppo e nei test.
- **Specialisti locali**: URL dei servizi adabox (`embeddings`, `pii`, `decider`, `forecast`) nei parametri;
  usati dalle fasi AI-4/5/6.
- **Database**: Postgres + pgvector richiesto da AI-4 (RAG). AI-1/2/3 girano anche su SQLite; i test della CI
  girano su entrambi.

## Fasi

AI-1 fondamenta · AI-2 strumenti dalle app · AI-3 proattività · AI-4 conoscenza (RAG) · AI-5 fiducia (PII,
provenienza) · AI-6 specialisti · AI-7 assistenti, sotto-agenti, eval. Contenuti: proposta, sezione 6.

## Prezzi e modelli iniziali (dal riferimento ufficiale Anthropic, ottobre 2026)

| Modello | ID | Contesto / output | $ per milione di token (input / output / lettura cache) |
|---|---|---|---|
| Claude Haiku 5.5 | `claude-haiku-5-5` | 1M / 128K | 0,10 / 0,50 / — (oltre 100K di prompt: 0,50 / 2,50) |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 1M / 128K | 2 / 10 / 0,20 |
| Claude Opus 5.5 | `claude-opus-5-5` | 1M / 128K | 4 / 20 / 0,20 |

Il ragionamento è sempre attivo sui modelli 5.5 e si regola con `output_config.effort` (Haiku: default `medium`;
per la chat si parte da `low`). La scrittura in cache costa circa 1,25 volte l'input. I prezzi sono modificabili
nel catalogo.

## Fuori scope di AI-1

Strumenti sulle app, conferme di scrittura, RAG, PII, specialisti, sotto-agenti (fasi successive).
