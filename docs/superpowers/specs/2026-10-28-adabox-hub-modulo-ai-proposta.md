# adabox-hub — modulo AI, "il cervello": brainstorming e proposta

Data: 2026-10-28
Stato: proposta da discutere (non ancora spec approvata)
Fonti studiate:
- adabox, repo `Ichnobyte/ICH_INV_070_25_adabox_prd`: branch `apps` e `stage` e branch `decisio-*` già uniti
  in stage. Contiene la spec di riscrittura `docs/MODULO_AI_SPEC.md`, scritta dal team per questo stesso
  obiettivo;
- `/opt/adabox-pii` (mascheramento dei dati personali) e `/opt/villasalto-rag` (RAG);
- deepseek-harness (MIT, TypeScript).

## 1. In una frase

Un'app `ai` installabile, disattivabile e vendibile come le altre. Contiene:
- un **motore agentico scritto in casa**: loop, strumenti, eventi;
- un **gateway dei modelli** con catalogo e regole di instradamento per compito e per app;
- **strumenti generati dalle `ModelView` del kernel**, con i permessi dell'utente e le conferme per le
  scritture;
- **servizi locali specialistici**: embedding, PII, decisore, previsioni.

Il principio guida, preso da adabox: **il modello sceglie e formula; numeri, permessi, scritture, grafici e
verifiche li fa il codice.**

## 2. Cosa prendere da dove

### Da adabox (codice Ichnobyte: si può riusare anche il codice)

| Funzione | Dove in adabox | Come in adabox-hub |
|---|---|---|
| Scritture con conferma in due fasi + audit | `tools/odoo/writes.py` | anteprima della modifica → bottone "Conferma" nella chat (non un codice da digitare) → si esegue l'operazione salvata, non argomenti nuovi |
| Contesti (assistenti configurabili): istruzioni, strumenti ammessi, profilo LLM, permessi per ruolo | `prompts`, `ContextLlmProfile`, `PromptPermission` | modello `Assistente` con ambito per app; la chat "limitata all'app" già esistente diventa l'assistente di quell'app |
| PII intorno a ogni chiamata cloud | `/opt/adabox-pii` (mmBERT ONNX, 24 categorie IT), `plugins/pii` (vault, segnaposto stabili, smascheramento degli argomenti dei tool e dello stream) | stesso servizio (riusato così com'è) + middleware nel gateway; politica per **anello della catena di fallback**, non per hostname |
| Decisore tipizzato (protocollo Jev: domande sì/no, scelta, punteggio → probabilità) | `docker/decider`, `plugins/decider` | servizio locale riusato (EmbeddingGemma + teste logistiche); Jev cloud solo con consenso esplicito (è negli USA) |
| Previsioni Timestral (quantili) + grafico | `docker/forecast`, `tools/forecast` | servizio locale riusato; attenzione: i pesi di Timestral hanno una licenza MIT modificata (uso solo sotto 20 M$ di ricavi mensili): va valutata per la vendita |
| Guardia sui numeri di previsione | `plugins/agent/utils/forecast_guard.py` | generalizzata: "i numeri di tipo X devono venire dallo strumento Y" |
| Badge di provenienza (verificato / parziale / senza fonti, PII, costo) | `provenance.py`, `response_badges.js` | evento di fine turno + badge sotto la risposta |
| Excel/CSV caricati → tabelle SQL interrogabili in sola lettura | `plugins/upload_tables` | "Tabelle dati" del modulo: schema separato, ruolo in sola lettura, timeout |
| Attività pianificate in linguaggio naturale + riepilogo del mattino | `tools/tasks`, `plugins/digest` | sulle pianificazioni e sul worker del kernel, che ci sono già; risultati in Discuss / posta in arrivo / email |
| UX dello streaming: risposta immediata, avanzamento per strumento, fonti prima del testo con citazioni | `chat_ack.py`, villasalto `citations.py` | eventi SSE tipizzati |
| Costi per turno, prezzi per milione di token, cache di Anthropic | `llm_providers/api.py`, `CachedChatAnthropic` | catalogo modelli con prezzi; costo nel log degli eventi |

**Da non ripetere** (elencati dalla spec di adabox stessa):
- SQL "protetto" solo da regex;
- `eval` di codice di grafici scritto dal modello;
- stato in memoria del processo con più worker gunicorn;
- vettori a 3584 dimensioni senza indice;
- chiavi API in chiaro;
- conoscenza condivisa tra utenti senza revisione;
- nessuna eval.

### Da deepseek-harness (MIT: idee e prompt; il codice è TypeScript)

1. **Log degli eventi della sessione come unica fonte del contesto** ("ciò che il modello vede è nel log"): audit,
   ripresa dopo un riavvio, debug e replay di ogni richiesta. Per un gestionale è oro.
2. **Strumenti tipizzati** (schema in ingresso e in uscita) con metadati che non vanno al modello: timeout,
   rischio, `concorrente_sicuro(args)`, presentazione.
3. **Pipeline degli strumenti**: pre-esecuzione (permessi, conferma) → guardie che possono solo negare →
   esecuzione con timeout → post-esecuzione. Approvazioni a esito chiuso, che falliscono in sicurezza.
4. **Esiti sintetici per le chiamate interrotte** ("esito sconosciuto: riprova solo se è idempotente"): niente
   fatture doppie dopo un crash.
5. **Interfaccia neutra per i provider**: chunk di stream normalizzati, errori con codice (`RATE_LIMIT`,
   `TIMEOUT`, ...), retry per rotta con backoff, watchdog sullo stream fermo.
6. **Disciplina della cache del prefisso**: prompt di sistema byte-stabile, fatti dinamici (data, azienda,
   pagina) come messaggi, storia solo in aggiunta. Con il caching di Anthropic dà grossi risparmi di costo e
   latenza.
7. **Compattazione a soglia** con riassunto strutturato (Intento / Dati / Errori / In sospeso / Prossimo
   passo); i risultati grandi dei tool vanno in un artifact e al modello arrivano testa, coda e riferimento.
8. **Strumenti in parallelo**: le letture insieme, le scritture una alla volta come barriera.
9. **Sotto-agenti** con profondità limitata, persona + elenco di strumenti + modello propri, per esempio
   "analista vendite" con un modello economico.
10. **Guardie anti-loop**: stessa chiamata ripetuta (avvisi a 3/5/8), timeout per strumento, budget del turno
    (passi, token, secondi, costo) con una chiusura controllata ("ho fatto X, manca Y").
11. **Test con sessioni registrate e un LLM finto**: regressioni deterministiche in CI. In più, eval con
    domande d'oro per assistente.
12. Più avanti: "code mode" (il modello scrive codice contro un SDK degli strumenti in una sandbox). Potente,
    ma in Python la sandbox è difficile.

## 3. Architettura proposta

```
addons/ai/
  motore/        loop agentico, eventi, budget, compattazione (Python puro, senza Django nel cuore)
  gateway/       provider (Anthropic, OpenAI-compatibili = OpenAI/OpenRouter/Ollama/vLLM, Google),
                 catalogo modelli, regole di instradamento, fallback, costi, PII middleware
  strumenti/     registro; generatore dalle ModelView; strumenti delle app (chiave "ai" nel manifest)
  conoscenza/    RAG: indicizzazione di Documenti, chatter, record; pgvector + full-text; citazioni
  specialisti/   client dei servizi locali: embedding, PII, decisore, previsioni
  assistenti, attività pianificate, tabelle dati, artifact (tabelle, ChartSpec, file)
servizi locali (docker, riusati da adabox): embeddings (EmbeddingGemma), pii (mmBERT ONNX),
  decider (protocollo Jev), forecast (Timestral)
```

- **Niente LangChain/LangGraph**: un loop nostro di poche centinaia di righe, provider con gli SDK ufficiali.
  Così è più veloce, ha meno dipendenze, il controllo è totale e i bug strani dei parser (vissuti in adabox)
  non ci sono.
- **Dove gira**: nel processo Django per la chat, con streaming SSE servito da worker ASGI (uvicorn) per non
  bloccare gunicorn; le esecuzioni lunghe e le pianificate girano nel worker del kernel. Stato su Postgres:
  nessuna memoria di processo.
- **Gli strumenti vengono gratis dalle app**: il kernel conosce già ogni `ModelView` (campi, filtri, permessi,
  azienda, azioni, bottoni). Il generatore crea per ogni vista `cerca`, `leggi`, `raggruppa/aggrega`, `crea`,
  `modifica`, `elimina`, `esegui_azione`, sempre con i **permessi dell'utente** e il filtro dell'azienda.
  Le app aggiungono strumenti propri con la chiave `"ai"` nel manifest (per esempio
  `fatturazione.emetti_fattura`, `calendario.crea_evento`).
- **Scritture**: ogni strumento ha un livello di rischio:
  - lettura → si esegue subito;
  - scrittura → anteprima e bottone di conferma;
  - irreversibile (eliminare, emettere, inviare allo SDI) → conferma più un riepilogo esplicito.
  Tutto finisce nel chatter del record e nel log degli eventi.
- **Grafici**: il modello produce una **ChartSpec** JSON e il kernel la disegna con il motore di grafici che ha
  già (SVG lato server, senza `eval`). Tipi: barre, linee, torta, area, dispersione, heatmap, imbuto, gauge,
  combinati, più previsione con fasce di quantili. Si salvano sulla dashboard e si aggiornano con dati veri,
  non con il modello.
- **"Creare tabelle"**:
  - tabelle dati del modulo (da Excel/CSV o definite in chat) in uno schema separato;
  - nuovi campi tramite Studio (che c'è già).
  Niente DDL libero sul database delle app.
- **Attività pianificate e eventi**: "ogni lunedì alle 8 mandami gli ordini aperti sopra 5.000 €" diventa una
  pianificazione del kernel che esegue l'agente con il profilo "pianificate" (modello economico) e consegna in
  Discuss, nella posta in arrivo o via email.

## 4. Modelli: instradamento per compito e per app

**Catalogo modelli** (tabella), con per ogni modello:
- provider e modello;
- capacità (strumenti, visione, ragionamento, JSON);
- finestra di contesto e prezzi;
- se è locale e se ha residenza UE.

**Profili per compito**, sovrascrivibili per app e per assistente:

| Compito | Proposta iniziale |
|---|---|
| chat e agente | **Claude Haiku 5.5** (`claude-haiku-5-5`) via API, prompt caching attivo |
| ragionamento difficile / sotto-agente "esperto" | Claude Sonnet 5.5 o Opus 5.5 su richiesta (escalation) |
| titoli, riassunti, compattazione, classificazione | modello economico (Haiku) o locale (Ollama) |
| embedding e RAG | **EmbeddingGemma** locale (768 dimensioni, indice HNSW pgvector) |
| PII | **mmBERT ONNX** locale (adabox-pii) |
| decisioni tipizzate | decisore locale (protocollo Jev); Jev cloud opzionale |
| previsioni | **Timestral** locale (quantili) |
| dati sensibili / installazioni senza cloud | catena interamente locale con Ollama |

**Catena di fallback** per profilo, con politica PII per ogni anello: un modello cloud riceve sempre i dati
mascherati, uno locale no. Il fallback scatta solo prima del primo token.

## 5. Vendibile e disattivabile

- È un modulo come gli altri: pacchetto firmato (fase 4), installabile e disinstallabile; disattivarlo lascia
  le app intatte.
- **Licenza**: un file di licenza firmato Ed25519 (le chiavi del kernel ci sono già), con cliente, scadenza,
  funzioni abilitate (RAG, specialisti, numero di utenti) ed eventuale tetto di spesa. Senza licenza valida il
  modulo resta installato ma spento.
- Chiavi API cifrate nel database (Fernet), mai mostrate per intero.
- Budget per utente, assistente e mese, con avvisi; costi visibili per turno e in dashboard.

## 6. Fasi proposte

| Fase | Contenuto | Esito visibile |
|---|---|---|
| AI-1 Fondamenta | gateway (Anthropic + OpenAI-compatibili + Ollama), catalogo e profili, loop con log degli eventi, budget, retry, streaming SSE, costi, licenza | la chat risponde davvero con Haiku 5.5 |
| AI-2 Strumenti | generatore dalle ModelView, permessi, conferme, parallelo/barriere, ChartSpec + artifact tabelle, strumenti del manifest | "quanti ordini aperti ha Rossi? crea un'attività per domani" |
| AI-3 Proattività | attività pianificate, riepilogo del mattino, eventi di calendario, consegna in Discuss | "ogni lunedì mandami…" |
| AI-4 Conoscenza | RAG su Documenti/chatter/record con EmbeddingGemma + full-text, citazioni, tabelle dati da Excel | "cosa dice il contratto di Bianchi sul rinnovo?" |
| AI-5 Fiducia | PII (adabox-pii), provenienza e badge, guardie sui numeri, audit | dati personali mai in chiaro verso il cloud |
| AI-6 Specialisti | decisore e previsioni Timestral come strumenti con grafici a quantili | "prevedi il fatturato dei prossimi 3 mesi" |
| AI-7 Agenti e qualità | assistenti configurabili, sotto-agenti per dominio, compattazione, eval in CI con LLM finto e domande d'oro | assistenti per app, regressioni bloccate in CI |

## 7. Decisioni prese (brainstorming del 2026-10-28)

1. **Dove gira**: app Django `ai` dentro adabox-hub. Lo streaming passa da worker ASGI (uvicorn), le esecuzioni
   lunghe e pianificate dal worker del kernel. Niente servizio separato: gli strumenti usano direttamente le
   `ModelView` con i permessi dell'utente.
2. **Specialisti locali**: si riusano i container di adabox già attivi su questo server (embeddings, pii,
   decider, forecast), raggiunti via rete Docker con URL configurabili. Senza di loro le funzioni relative si
   spengono e il resto funziona.
3. **Azioni dell'agente nella prima versione**:
   - legge tutto ciò che l'utente vede;
   - crea e modifica con anteprima e conferma;
   - le azioni irreversibili (eliminare, emettere, inviare allo SDI) richiedono conferma con riepilogo
     esplicito.
4. **Database**: Postgres + pgvector obbligatorio per il modulo AI; sviluppo e test dell'AI su Postgres.
5. **Jev e Timestral**: decisore e previsioni opzionali, spenti di default. Jev cloud (USA) solo con consenso
   esplicito per azienda. Per Timestral si documenta il limite della licenza dei pesi e si valuta un'alternativa
   Apache 2.0 (es. Chronos).
6. **Vendita**: file di licenza firmato (cliente, scadenza, funzioni, numero di utenti) e tetto di spesa mensile
   per azienda, con avvisi e blocco morbido. Senza licenza valida il modulo resta installato ma spento.
7. **Chiavi API**: per azienda, cifrate nel database, con una chiave globale di riserva; mai mostrate per intero.
   I costi si attribuiscono all'azienda.
8. **Accesso**: gruppo «AI / Utente» per la chat. Ogni assistente (generale o per app) ha i gruppi ammessi e i
   propri strumenti; gli strumenti operano sempre con i permessi di chi chiede.

Fatti verificati sul server:
- niente GPU (8 core, 22 GB di RAM);
- sono attivi i container adabox `embeddings`, `pii` (porta 5005), `decider`, `forecast`, `searxng` e
  `speaches`;
- Ollama non è in esecuzione: gli LLM locali girerebbero su CPU, quindi solo modelli piccoli.

Prossimo passo: la spec del modulo (dalle sezioni 2-6 e da queste decisioni) e il piano della fase AI-1.
