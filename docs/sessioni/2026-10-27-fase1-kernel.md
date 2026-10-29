# Sessione 2026-10-27 — fase 1 del kernel

Partecipanti: sviluppo2@ichnobyte.it con Claude (Claude Code, VS Code).
Piano eseguito: `docs/superpowers/plans/2026-10-27-adabox-hub-fase1-kernel.md`, task 1-14, un commit per task.
Remote: `git@github-adabox:EcoreAi/adabox-hub.git` (alias SSH del server con la chiave dell'account EcoreAi;
l'host `github.com` usa la deploy key di adaerp e non può scrivere qui).

## Stato a fine sessione

- Suite: tutti i test verdi, compreso l'end-to-end `addons/todo/tests/test_installazione.py` (`pytest -m "not slow"` lo salta).
- DB di sviluppo: migrato, `todo` installato con i dati demo, **nessun utente** (serve `createsuperuser`).
- Docker verificato: build, login 200 su :8096, SIGHUP via pidfile con riavvio dei worker.

## Scostamenti dal piano e dalla spec

1. Comando interno `modulo_applica` invece di `_modulo_applica`: Django non scopre i comandi che iniziano con `_`.
2. Le `ModelView` del kernel sono montate sotto `/core/` (come i moduli sotto `/<slug>/`): `/core/aziende/`, `/core/profili/`.
3. Migrazione `0003_azienda_iniziale` senza pk esplicito: su Postgres non farebbe avanzare la sequenza.
4. Il backup sqlite (API nativa) resta in attesa se la stessa connessione ha scritture non committate: succede solo nei
   test non transazionali, per questo `test_aggiorna` è `transaction=True`.
5. Messaggi di conferma neutri rispetto al genere ("Creazione completata: azienda «X»"); azioni di massa come bottoni
   con `formaction` (funzionano senza JS); eliminazione via HTMX con `HX-Redirect`.
6. La tabella resa da HTMX nasce con `is-revealed` (ui.js rivela solo le tabelle presenti al caricamento).
7. API: corpo JSON validato dalla `ModelForm` della vista, risposte `dict` (niente `create_schema`); Ninja 1.7 non ha il
   parametro `csrf`, il controllo lo fa `django_auth`.
8. Pagina Moduli: un modulo in `errore` non installato offre Installa (riprova); il comando scrive `== FINE ok|errore ==`
   prima di propagare l'errore e la pagina lo cerca nella coda del log.
9. Aggiunti dopo il piano, dalla spec: azienda predefinita in `/profilo/`; indicazione "dati presenti" per i moduli
   disinstallati senza `--elimina-dati` (dalle righe di `django_migrations`).

## Da fare

- Prova manuale nel browser (filtri dal vivo, modale, installa/disinstalla da `/moduli/` con `runserver`).
- Ogni `docker compose up` crea `staticfiles/` come root nella cartella del repo (comportamento ereditato dallo starter).
- Fase 2: spec approvata e piano 2a completato (sezione sotto); restano i piani 2b (viste) e 2c (report PDF,
  campi personalizzati).

## Fase 2a — servizi (stessa sessione)

Spec di fase 2 approvata (`docs/superpowers/specs/2026-10-27-adabox-hub-fase2-kernel-completo-design.md`; decisione
cambiata: email anche in entrata, via IMAP). Piano 2a eseguito: `docs/superpowers/plans/2026-10-27-adabox-hub-fase2a-servizi.md`.

- Lavori nel DB e `manage.py worker`; pianificazioni dai manifest; parametri e `/impostazioni/`; sequenze; allegati
  privati; chatter con tracciamento, follower, email in uscita e in entrata; attività pianificate e `/attivita/`.
- `todo` 1.1.0 li usa tutti; il DB di sviluppo è aggiornato a 1.1.0.
- Suite verde su SQLite e su Postgres (`deploy/test-postgres.sh -q`), compresi aggiornamento 1.0.0 → 1.1.0 e
  concorrenza (worker, pianificazioni, sequenze).
- Docker verificato: web, worker e nginx; lavoro accodato dal web ed eseguito dal worker; il worker esce e riparte
  da solo quando cambiano i moduli.

Scostamenti dal piano 2a: pannello del chatter incluso da `dettaglio.html` (non via `hooks`); sequenze conservate
alla disinstallazione senza `--elimina-dati`; token di risposta `ct-pk-hmac` esadecimale (sta nella parte locale
dell'indirizzo); il riferimento al filo del record in `References` non basta ad abbinare una risposta; contatore
delle attività come voce della nav; il worker si ferma da solo quando cambiano `installed.json` o i manifest.

## Fase 2b — viste (stessa sessione)

Piano `docs/superpowers/plans/2026-10-27-adabox-hub-fase2b-viste.md` eseguito: raggruppamenti con totali e
selettore delle viste, kanban con trascinamento, calendario mese/settimana, grafico SVG, export CSV/XLSX, import con
prova a secco. `todo` 1.2.0 le usa tutte; DB di sviluppo aggiornato. Suite verde su SQLite e Postgres.
Scostamenti: le viste dichiarate ma non montate non compaiono nel selettore; il form "nuovo" accetta valori iniziali
dalla query string (serve al calendario); i totali dei campi interi si riportano a intero (su Postgres SUM dà Decimal).

## Fase 2c — report PDF e campi personalizzati (stessa sessione)

Piano `docs/superpowers/plans/2026-10-27-adabox-hub-fase2c-documenti.md` eseguito: stampe PDF dalla `ModelView`
(WeasyPrint, layout del kernel, singole e di massa, worker oltre 20 record) e campi personalizzati
(`ProprietaMixin`, `/core/campi/`) in form, dettaglio, lista, filtri e API. `todo` 1.3.0 li usa; DB di sviluppo
aggiornato. **La fase 2 è completa.**

- Suite verde su SQLite e Postgres; test PDF verdi nell'immagine Docker (`deploy/test-pdf.sh`): Pango non è
  installato sull'host (server condiviso), dove i test PDF si saltano e la stampa risponde 503.
- Stack Docker provato: pagine 200, scheda PDF e export XLSX dal container web.
- Corretto il pin di pytest (9.1.1): con 9.0.2 un'installazione pulita di requirements-dev falliva.
- Scostamenti: `get_form_class(request)` (i campi personalizzati dipendono dall'azienda); `Azienda` accetta campi
  personalizzati; il filtro per azienda confronta il pk (request.azienda lazy può avvolgere None); log di
  WeasyPrint e fontTools a WARNING; HarfBuzz-Subset nell'immagine.

## Prossimi passi

- Prova manuale nel browser di tutta la fase 2 (con `runserver` serve `createsuperuser`: il DB di sviluppo non ha
  utenti); per i PDF in sviluppo serve Pango sull'host oppure Docker.
- Configurare per un'istanza vera `EMAIL_URL`, `EMAIL_RISPOSTE`, `IMAP_URL`, `SITO_URL` e Postgres nel compose.
- Fase 3 (prime app: contatti, calendario, crm, helpdesk, progetti e timesheet): spec propria; `todo` può passare
  alle attività pianificate del kernel.

## Fase 3 — prime app (sessione proseguita il 2026-10-28)

Spec `docs/superpowers/specs/2026-10-27-adabox-hub-fase3-prime-app-design.md` (decisioni prese in autonomia su
richiesta dell'utente, motivate nella spec) e piano `docs/superpowers/plans/2026-10-27-adabox-hub-fase3-prime-app.md`
eseguiti: **contatti, calendario, crm, helpdesk, progetti, timesheet**, tutte installate nel DB di sviluppo con i demo.

- Kernel: clienti esterni nel chatter (`destinatari_esterni`, `autore_email`) e gestori delle email non abbinate;
  scelte di FK/M2M filtrate per azienda nei form; campi URL con https.
- Visibilità sui record con permessi personalizzati: progetti (membri/responsabile), timesheet (proprie ore),
  calendario (eventi privati).
- `todo` resta l'app minima di riferimento (decisione 6 della spec).
- Suite verde su SQLite (con l'installazione vergine di tutte le app) e su Postgres; PDF in Docker; stack Docker
  provato su tutte le app.
- Corretti strada facendo: due test dipendenti dal tempo (pianificazioni del kernel scadute dopo minuti di suite),
  registri globali (sezioni, gestori email) svuotati dai test e ora sostituiti con monkeypatch, un escape non valido
  in `calendario/ics.py` (ora c'è un test che compila tutti i sorgenti con i warning come errori).

Prossimi passi: prova nel browser; configurazione della posta per un'istanza vera; fase 4 (distribuzione: upload
zip dei moduli, pacchettizzazione, firma) o fase 5 (gestionale: prodotti, vendite, magazzino, fatturazione).

## Dashboard, chat e fase 4 — distribuzione (2026-10-28)

- **Dashboard** (`/dashboard/`) con i KPI e i grafici dichiarati da ogni app (`dashboard` nel manifest); **home**
  configurabile (`home` nel manifest): con il modulo `ai` installato è la chat, altrimenti la dashboard; launcher su
  `/app/`. Modulo **`ai` 0.2.0** (scheletro): chat a tutto schermo con header e menu delle app, colonne laterali a
  icone, suggerimenti e limitazione a un'app; risposta segnaposto in `addons/ai/assistente.py`.
- **Fase 4** (spec `docs/superpowers/specs/2026-10-28-adabox-hub-fase4-distribuzione-design.md`, piano
  `docs/superpowers/plans/2026-10-28-adabox-hub-fase4-distribuzione.md`): pacchetti zip con hash e firma Ed25519
  (`cryptography`), caricamento con tutti i controlli da `/moduli/` e da CLI (estrae, non installa), catalogo firmato
  con download, collaudo `modulo collauda` in istanze usa e getta. Tutte le 8 app passano il collaudo.
- Il collaudo ha trovato un test di `ai` che presupponeva `todo` installato: corretto.

Prossimi passi: generare la coppia di chiavi di produzione e pubblicare il catalogo; prontezza per un cliente vero
(Postgres nel compose, HTTPS, posta, CI, backup pianificati); fase 5 (gestionale) e il modulo AI vero.

## Fase 5 — gestionale (2026-10-28)

Spec `docs/superpowers/specs/2026-10-28-adabox-hub-fase5-gestionale-design.md` e piano
`docs/superpowers/plans/2026-10-28-adabox-hub-fase5-gestionale.md` eseguiti in autonomia: **fiscale, prodotti,
vendite, magazzino, acquisti, fatturazione**, installate nel DB di sviluppo con i demo; tutte passano il collaudo.

- Kernel: righe dei documenti (`Inline`, formset con "Aggiungi riga", totali nel dettaglio) e hook `demo(modulo)`.
- Collegamenti con segnali (conferma ordine → consegna/ricevimento) solo se `magazzino` è installato; giacenza
  calcolata dai movimenti; importi `Decimal` con `ROUND_HALF_UP`.
- Fatture numerate `n/anno` solo all'emissione (controllo dell'ordine delle date), scadenze dal termine di
  pagamento, incassi, note di credito sulla stessa sequenza; XML FatturaPA FPR12 con progressivo di invio per azienda
  e validazione strutturale nei test; registro IVA mensile/annuale con CSV.
- Fuori scope, come da spec: SDI (modulo a parte, con lo schema XSD ufficiale), HR e note spese, partita doppia.

Prossimi passi: modulo `sdi` (invio/ricezione, notifiche, XSD); i demo di vendite non generano consegne (gli ordini
demo sono confermati senza segnale); prova nel browser del ciclo completo; modulo AI vero.

## Fase 6 — Studio, Documenti, Discuss (2026-10-28)

Spec `docs/superpowers/specs/2026-10-28-adabox-hub-fase6-studio-documenti-discuss-design.md` e piano
`docs/superpowers/plans/2026-10-28-adabox-hub-fase6-studio-documenti-discuss.md` eseguiti in autonomia; le tre app
sono installate nel DB di sviluppo (documenti e discuss con i demo) e passano il collaudo.

- Kernel: viste personalizzabili per richiesta (`core.viste.personalizza`, copia superficiale della `ModelView`),
  `etichette`, campi personalizzati singoli nei layout, `hooks.voce_testata`, sezioni di dettaglio per tutti i
  modelli (`"*"`).
- **Studio**: editor in JavaScript nativo (trascinamento + bottoni), solo le differenze salvate, storico,
  esporta/importa; verificato con jsdom e con un salvataggio vero sul server di sviluppo.
- **Documenti**: permessi per gruppi ereditati, anteprima di immagini e PDF, cestino, zip, link pubblici con
  limite per IP e registro accessi, richieste che creano un'attività, cartelle collegate ai modelli.
- **Discuss**: canali e messaggi diretti con polling HTMX, non letti, menzioni, posta in arrivo anche dal chatter,
  campanella in testata, email dei non letti.

Prossimi passi: prova nel browser di editor di Studio, trascinamento dei file e chat; cache condivisa (Redis) per
il limite dei link pubblici con più processi; campanella anche nella pagina della chat AI (ha una testata propria).

## Barra in alto, fase 7 — SDI, personale, note spese, proposta AI (2026-10-28)

- Barra in alto con poche app e menu «Altre»; pagina `/impostazioni/barra/` per scegliere app fisse e ordine.
- Fase 7 (spec `docs/superpowers/specs/2026-10-28-adabox-hub-fase7-sdi-personale-spese-design.md`, piano
  omonimo): ponte vendite/acquisti → magazzino nei dati demo; **sdi** (validazione XSD ufficiale con `lxml`,
  canali manuale/PEC/prova, notifiche, fatture passive con p7m, pagamenti, registro acquisti); **personale**
  (assenze con approvazione, saldi, festività); **spese** (note con ricevute, km, approvazione, rimborso).
  Kernel: form multipart anche per le righe, nome dei file nei dettagli, test che ogni `hooks.py` sia dichiarato
  (il manifest di sdi lo aveva dimenticato: demo e gruppo non partivano).
- Un test (`config/tests/test_deploy.py`) è fallito una volta sola sotto carico e poi è passato: da tenere d'occhio.
- **Modulo AI**: proposta in `docs/superpowers/specs/2026-10-28-adabox-hub-modulo-ai-proposta.md`, dallo studio di
  adabox (`/opt/adabox`, spec `docs/MODULO_AI_SPEC.md`, adabox-pii, villasalto-rag) e di deepseek-harness (MIT).
  In attesa delle decisioni della sezione 7 prima della spec.

## Modulo AI — fase AI-1, fondamenta (2026-10-29)

Spec `docs/superpowers/specs/2026-10-29-adabox-hub-modulo-ai-design.md`, piano
`docs/superpowers/plans/2026-10-29-adabox-hub-ai-1-fondamenta.md`, eseguiti in autonomia (autorizzazione esplicita).

- Kernel: `core/cifratura.py` (Fernet), `config/asgi.py` con riavvio al cambio dei moduli, servizio `stream`
  (uvicorn) accanto a gunicorn e instradamento nginx di `/ai/flusso/`.
- `ai` 1.0.0:
  - catalogo di provider, modelli e profili con catena di fallback;
  - gateway con l'SDK `anthropic` 1.17 (cache del prefisso, effort), adattatore compatibile OpenAI su
    `httpx2` e modello finto;
  - motore con log degli eventi in sola aggiunta, strumenti di base, budget, stop e turni interrotti;
  - SSE con ripresa, Markdown sicuro, titoli automatici;
  - licenza Ed25519, tetto di spesa, consumi e dashboard.
- Corretto: una `SECRET_KEY` che iniziava con `$` veniva sostituita in silenzio dal default di sviluppo
  (interpolazione di django-environ). Era la causa del test intermittente `test_deploy`.
- Verificato sul server di sviluppo con un provider finto temporaneo, poi rimosso: turno in un thread, streaming
  in diretta sotto WSGI (`runserver`) e ASGI (uvicorn).
- Manca la prova con Claude Haiku 5.5 vera: sul server non c'è una chiave API. Va inserita in `/ai/provider/`.

Prossimo: AI-2 (strumenti generati dalle `ModelView`, scritture con conferma, ChartSpec e artifact).

## Modulo AI — fase AI-2, strumenti dalle app (2026-10-29)

Piano `docs/superpowers/plans/2026-10-29-adabox-hub-ai-2-strumenti.md`.

- Strumenti generici con la vista come argomento, non sette per vista: con 20 app sarebbero centinaia di
  definizioni in ogni richiesta e un prefisso diverso per utente. Il modello scopre le viste con `elenco_viste`.
- Letture (`ai/strumenti/viste.py`) con una richiesta finta (`richiesta.py`) che passa dalle `ModelView` come il
  browser; filtri con al massimo un salto su una relazione e operatori ammessi; campi sensibili esclusi.
- Scritture come `Proposta` (`ai/proposte.py`, `ai/strumenti/scritture.py`): anteprima validata, conferma con
  bottone, esecuzione dell'operazione salvata, impronta del record contro le modifiche nel frattempo, scadenza
  di 24 ore, nota nel chatter, esito al modello nel `<contesto>` del messaggio successivo.
- `Artifact` (grafico, tabella) con istantanea in chat, pagina con i dati di oggi e CSV; pannelli dei salvati.
- Chiave `"ai"` del manifest (solo moduli dell'app stessa); `calendario.ai` con l'agenda.
- Test: `AI_STRUMENTI_SINCRONI` (default come `AI_TURNI_SINCRONI`) fa girare gli strumenti nel thread del turno,
  perché sotto SQLite un altro thread non vede la transazione del test.

Prossimo: AI-3 (attività pianificate, riepilogo del mattino, consegna in Discuss). Resta da provare la chat con
una chiave API vera.

Dopo AI-2, su richiesta dell'utente: chat sotto l'header del tema (una sola barra), «Chat» prima voce della barra
(`NAV_APP_IN_TESTA`, `nav_label` del manifest), applicazione rinominata «Adabox v3» con il logo a cubo, CSS e JS
con la versione nell'URL (`{% statico %}` del tema), bottone «App» nel campo della chat. Corretti: nginx agganciato
al vecchio IP di `stream` dopo la ricreazione dei container (502), token CSRF assente nelle schede arrivate dallo
streaming (403 alla conferma).

## Modulo AI — fase AI-3, proattività (2026-10-29)

Piano `docs/superpowers/plans/2026-10-29-adabox-hub-ai-3-proattivita.md`.

- `Pianificata` con ricorrenze proprie (giorni della settimana, mese, ogni N ore, prima degli eventi): le
  pianificazioni del kernel conoscono solo intervalli fissi e restano l'orologio (`cron` ogni minuto).
- Esecuzione nel worker con `motore.avvia(..., compito="pianificate", sincrono=True, nota=...)`: la nota va al
  modello nel `<contesto>`, in chat resta solo l'istruzione.
- Consegna: conversazione dedicata sempre; Discuss (messaggio diretto di `assistente-ai`) ed email facoltativi.
- Creazione dalla chat con `crea_pianificata` (proposta da confermare), pagina «Pianificate» con i bottoni.
- Il profilo «Attività pianificate» passa da 1024 a 16000 token (`post_upgrade`).

Prossimo: AI-4 (conoscenza: RAG su documenti, chatter e record con citazioni).
