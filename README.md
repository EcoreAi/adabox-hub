# adabox-hub

Piattaforma gestionale modulare di ICHNOBYTE, costruita con Django 5.2 sopra lo
starter `django-template`. Riproduce il modello di Odoo: un **kernel** (`core`) e
delle **app** in `addons/` che si installano, aggiornano e disinstallano da riga di
comando o dalla pagina `/moduli/`. A ogni cliente la sua istanza, con le sue app.

Spec e piano della fase 1: `docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md`,
`docs/superpowers/plans/2026-10-27-adabox-hub-fase1-kernel.md`.

## Avvio in sviluppo

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                       # imposta SECRET_KEY
python manage.py migrate
python manage.py createsuperuser
python manage.py modulo installa todo --demo --si
python manage.py runserver
```

Apri `http://127.0.0.1:8000/`: il launcher mostra le app installate. Poi `/moduli/`
(superuser), `/core/aziende/`, `/api/v1/docs`, `/profilo/` (token API), `/stile/`.

## Struttura

```
addons/            le app: una cartella per app, con __manifest__.py
  installed.json   stato di installazione dell'istanza (non versionato)
  todo/            app di riferimento
backup/            dump del DB prima di ogni installazione/aggiornamento (non versionato)
config/            settings unico via .env; INSTALLED_APPS = kernel + addons installati
core/              il kernel
  registry/        bootstrap (python puro, letto dai settings), manifest, scoperta e stati,
                   installazione, gruppi, ricarica, hook, URL dei moduli
  viste/           ModelView e viste generiche (lista, form, dettaglio, elimina, azioni)
  api/             API JSON (Django Ninja): /api/v1/
  backup.py        sqlite (API di backup) o pg_dump
  models.py        Azienda, ProfiloUtente, Modulo, TokenApi
theme/             grafica (admin e frontend) + htmx vendorizzato; non importa nulla da core
deploy/            entrypoint.sh (gunicorn con pidfile), nginx.conf
```

## Scrivere un'app

Un'app minima non scrive né viste né template: bastano modello, `ModelView` e manifest.
`addons/todo/` è l'esempio completo.

1. **Cartella e manifest** — `addons/<slug>/__manifest__.py`, un solo dizionario letterale
   (si legge con `ast.literal_eval`, mai importato):
   ```python
   {
       "name": "To-Do", "summary": "Attività con scadenze", "version": "1.0.0", "min_core": "1.0",
       "depends": [], "application": True, "icon": "todo/icon.svg",
       "menu": [{"label": "Attività", "url_name": "todo:attivita_lista", "permission": "todo.view_attivita"}],
       "groups": {"To-Do / Utente": ["todo.view_attivita", "todo.add_attivita"], "To-Do / Responsabile": ["todo.*"]},
       "data": ["data/tag.json"], "demo": ["data/demo.json"], "hooks": "todo.hooks",
   }
   ```
   Lo slug (`^[a-z][a-z0-9_]{1,30}$`) è il nome della cartella e del pacchetto. Chiavi
   sconosciute sono un errore. `python manage.py modulo verifica addons/<slug>` lo valida.
2. **Pacchetto Django** — `__init__.py`, `apps.py`, `models.py`, `migrations/`. I modelli
   per azienda ereditano `core.mixins.AziendaMixin`; quelli condivisi (tag, tipi) no.
   Le migrazioni si generano con `ADDONS_FORCE=<slug> python manage.py makemigrations <slug>`
   (la variabile carica il modulo anche se non è ancora installato).
3. **Viste** — in `views.py`:
   ```python
   from core.viste import ModelView, register

   @register
   class AttivitaView(ModelView):
       model = Attivita
       list_display = ["titolo", "scadenza", "stato"]
       list_filter = ["stato"]
       search_fields = ["titolo"]
       form_layout = [("Generale", ["titolo", ("scadenza", "stato")])]   # tupla = campi affiancati
       company_field = "azienda"          # filtro e assegnazione automatica dell'azienda corrente
       actions = ["archivia"]             # metodi (self, request, queryset) -> messaggio
       buttons = ["segna_fatta"]          # metodi (self, request, obj) -> messaggio o HttpResponse
       api = True                         # /api/v1/<slug>/<vista>/

       def col_stato(self, obj): ...      # resa personalizzata di una colonna
   ```
   Il kernel genera sotto `/<slug>/` lista (ricerca, filtri, ordinamento, paginazione con
   HTMX), nuovo, dettaglio, modifica, elimina (modale), azioni e bottoni, con nomi URL
   `<slug>:<vista>_lista|_nuovo|_dettaglio|_modifica|_elimina|_azione|_bottone` e i permessi
   Django del modello. Pagine proprie: `urls.py` del modulo (montato sotto lo stesso prefisso)
   e template che estendono `core/base_app.html`.
4. **Gruppi, fixture, hook** — i gruppi del manifest si creano all'installazione (`app.*` =
   tutti i permessi dell'app); le fixture `data` si caricano a ogni installazione e
   aggiornamento (pk fissi), quelle `demo` solo con `--demo`; `hooks.py` può definire
   `post_install(modulo)`, `post_upgrade(modulo, da_versione)`, `pre_uninstall(modulo)` e
   `demo(modulo)` (solo con `--demo`, dopo le fixture: per i dati demo che citano record di altre app).
5. **Righe dei documenti** (one2many) — `inlines = [Inline(Riga, "documento", ["prodotto", "quantita"])]`
   nella `ModelView`: il form del documento ha la tabella delle righe con "Aggiungi riga" ed eliminazione
   (scelte filtrate per azienda), il dettaglio le mostra in sola lettura; `dopo_righe(request, obj)` è chiamato
   dopo il salvataggio (es. per ricalcolare i totali) e `totali(obj)` dà le voci sotto le righe.
6. **Sezioni su modelli altrui** — nel `ready()` dell'app:
   `core.registry.hooks.sezione_dettaglio("todo.Attivita", "mia_app/_sezione.html", order=50)` (`"*"` = il
   dettaglio di tutti i modelli). Per la barra in alto: `hooks.voce_testata("mia_app/_voce.html", order, permission)`.
   Per cambiare le viste di altri moduli a ogni richiesta: `core.viste.personalizza.registra(funzione)`, dove
   `funzione(vista, request)` restituisce gli attributi da sovrascrivere (`list_display`, `form_layout`,
   `etichette`... vedi `ATTRIBUTI`); è il meccanismo usato da Studio.
7. **Test** — in `addons/<slug>/tests/`; per farli girare con la suite aggiungi lo slug a
   `ADDONS_FORCE` in `pytest.ini`.

## Servizi del kernel

Un'app li usa dichiarando attributi o chiamando una funzione: niente viste né template da scrivere.

| Servizio | Come si usa |
|---|---|
| **Chatter** | `ModelView.chatter = True`: pannello con messaggi, note interne, follower, allegati e attività nel dettaglio. `tracked_fields = ["stato", ...]` scrive le modifiche (da form e da API). Da codice: `core.chatter.scrivi(obj, utente, testo)`, `core.chatter.traccia(obj, vecchi, utente)` con `vecchi = core.chatter.valori(obj, campi)` letto prima. |
| **Email** | I *messaggi* (non le note) partono per email ai follower, nel worker. Le risposte tornano nel chatter del record (vedi sotto). |
| **Attività** | Nel pannello: "Pianifica un'attività" (tipo, scadenza, assegnatario). Fatta → voce del chatter. `/attivita/` elenca le proprie; promemoria ogni mattina alle 07:00. Da codice: `core.attivita.pianifica(obj, tipo, utente, scadenza)`. |
| **Allegati** | Nel pannello, o `core.allegati.salva(obj, file, utente)`. File in `private/`, mai pubblici: si scaricano da `/allegati/<pk>/` solo con il permesso di vedere il record. |
| **Sequenze** | Manifest `"sequences": [{"codice": "todo.attivita", "formato": "ATT/{anno}/{numero:04d}", "azzera": "anno"}]` e `ModelView.sequence_field = ("numero", "todo.attivita")`; da codice `core.sequenze.prossimo(codice, azienda)`. |
| **Impostazioni** | Manifest `"settings": [{"chiave": "giorni_preavviso", "label": ..., "tipo": "intero", "default": 2, "per_azienda": True}]`: pagina `/impostazioni/` generata; si leggono con `core.parametri.leggi("todo.giorni_preavviso", azienda)`. |
| **Lavori** | `core.lavori.accoda("app.modulo.funzione", ritardo=0, **argomenti_json)`: eseguito dal worker, con tre tentativi (1, 5, 30 minuti). `/core/lavoro/` per il superuser. |
| **Pianificazioni** | Manifest `"cron": [{"nome": ..., "funzione": "todo.lavori.promemoria_scadenze", "ogni": "1d", "alle": "07:30"}]` (`ogni`: `15m`, `2h`, `1d`). Si attivano e disattivano dall'admin. |

### Worker

`python manage.py worker` esegue lavori e pianificazioni (in Docker è il servizio `worker`). Più worker in
parallelo funzionano su Postgres. In sviluppo `LAVORI_SINCRONI=True` (default con `DEBUG`) esegue i lavori subito,
nella richiesta: il worker serve solo per le pianificazioni. Quando cambiano i moduli installati il worker esce
da solo e Docker lo riavvia con il codice nuovo.

### Posta del chatter

- **Uscita**: `EMAIL_URL` (vedi Produzione) e `SITO_URL` (base dei link, es. `https://hub.cliente.it`).
- **Entrata**: una casella dedicata che accetti gli indirizzi con il `+` (`risposte+qualcosa@cliente.it` arriva in
  `risposte@cliente.it`): `EMAIL_RISPOSTE=risposte@cliente.it` e
  `IMAP_URL=imaps://risposte%40cliente.it:password@mail.cliente.it:993/INBOX`. Ogni 2 minuti il worker legge le
  email non lette e le abbina al record (per `In-Reply-To` o per il token firmato nell'indirizzo); il mittente
  deve essere un utente che vede il record. Esiti in `/core/email/`.

## Viste oltre la lista

Si dichiarano sulla `ModelView`; un selettore nella testata passa dall'una all'altra conservando ricerca e filtri.

```python
list_group_by = ["stato", "assegnatario", "scadenza:mese"]   # "Raggruppa per" nella lista, con conteggi
list_sum = ["ore"]                                          # totali per gruppo e in fondo (campi numerici)
kanban_group = "stato"                                      # colonne: scelte o FK; card trascinabili
kanban_fields = ["numero", "scadenza", "assegnatario"]
calendar_date = "scadenza"                                  # mese e settimana; clic su un giorno = nuovo
calendar_color = "stato"
graph = {"tipi": ["barre", "linee", "torta"], "misure": ["count", "sum:ore"], "per": ["stato", "scadenza:mese"]}
export_fields = None                                        # default: id + campi di list_display
import_key = "numero"                                       # l'import aggiorna i record con lo stesso numero
```

- **Kanban**: spostare una card cambia il campo (permesso `change`) e lo traccia nel chatter; senza JavaScript
  ogni card ha un "Sposta".
- **Grafico**: aggregato nel DB e disegnato in SVG dal server, con la tabella dei dati sotto.
- **Export** (menu "Dati" della lista): Excel o CSV (`;`, virgola decimale, come lo apre Excel in italiano) delle
  righe filtrate, o di quelle selezionate. Oltre `EXPORT_SINCRONO_MAX` righe (5000) lo prepara il worker e il link
  arriva per email.
- **Import** (menu "Dati"): carica CSV o Excel, associa le colonne ai campi (proposta automatica), **prova a secco**
  con l'elenco degli errori per riga, poi importa tutto o niente. FK e tag si scrivono per nome, le scelte con la
  loro etichetta, le date come `gg/mm/aaaa`. Oltre `IMPORT_SINCRONO_MAX` righe (1000) nel worker.

## Stampe PDF e campi personalizzati

**Report PDF.** Sulla vista: `reports = [{"nome": "Scheda attività", "template": "todo/report/attivita.html"}]`.
Il template estende `core/report/base.html` (A4, intestazione con logo e dati dell'azienda corrente, "Pagina N di M")
e riempie `{% block record %}` con `obj`: un record per pagina. Bottone nel dettaglio e "Stampa" sulle righe
selezionate della lista; `?html=1` mostra l'HTML per provare il layout. Oltre `REPORT_SINCRONO_MAX` record (20) il
PDF lo prepara il worker. I PDF li genera WeasyPrint, che richiede Pango: è nell'immagine Docker; dove manca la
stampa risponde 503 e i test che generano PDF si eseguono con `deploy/test-pdf.sh`.

**Campi personalizzati.** Il cliente aggiunge campi da `/core/campi/` (testo, numeri, data, Sì/No, scelta da elenco,
utente; obbligatori, in lista, filtrabili; per tutte le aziende o per una), senza migrazioni. Li accettano i modelli
con `core.mixins.ProprietaMixin` (valori nel JSON `proprieta`): compaiono nel form (dove il `form_layout` dice
`"@proprieta"`, altrimenti in "Altre informazioni"), nel dettaglio, nella lista, nei filtri e nell'API
(`"proprieta": {...}` in lettura e scrittura). Oggi li accettano `Azienda` e `todo.Attivita`.

## Le app

| App | Dipende da | Cosa fa |
|---|---|---|
| `todo` | — | app minima di riferimento del kernel (attività con scadenze) |
| `contatti` | — | anagrafica di aziende e persone, partita IVA e codice fiscale validati, codice SDI e PEC |
| `calendario` | contatti | eventi con inviti e file `.ics`, promemoria, eventi privati |
| `crm` | contatti | opportunità in pipeline (kanban per fase), valore atteso, lead convertibili in contatti |
| `helpdesk` | contatti | ticket con SLA per priorità; il cliente riceve i messaggi e risponde per email; ticket aperti dalle email all'indirizzo dell'helpdesk |
| `progetti` | contatti | progetti e compiti (kanban, calendario, avanzamento); ognuno vede i progetti di cui è membro |
| `timesheet` | progetti | ore su progetti e compiti, griglia settimanale, totali e analisi; ognuno vede le proprie ore |
| `ai` | — | assistente agentico: chat in diretta (home se installata), catalogo di provider e modelli con profili per compito, strumenti con i permessi dell'utente, licenza e tetto di spesa |
| `fiscale` | — | aliquote IVA con natura ed esigibilità, termini di pagamento a rate; calcolo di importi, riepilogo IVA e scadenze |
| `prodotti` | fiscale | beni e servizi con codice, unità, IVA, costo e prezzo; listini a scaglioni di quantità |
| `vendite` | prodotti, contatti | preventivi e ordini con righe, listini, sconti e IVA; stampa, invio per email, conferma |
| `magazzino` | prodotti | movimenti e giacenze, consegne con DDT (scarico), ricevimenti (carico), rettifiche, scorte minime |
| `acquisti` | prodotti, contatti | ordini ai fornitori con costi e IVA; stampa, invio, conferma |
| `fatturazione` | vendite, fiscale | fatture e note di credito numerate all'emissione, scadenze e incassi, XML FatturaPA, registro IVA |
| `sdi` | fatturazione | fatture elettroniche allo SDI (validate con lo schema ufficiale; canale manuale, PEC o di prova) con notifiche; fatture dei fornitori dalla PEC o caricate (XML, p7m, zip), registrazione, pagamenti, registro IVA acquisti |
| `personale` | — | dipendenti e reparti, ferie e permessi richiesti dal dipendente e approvati dal responsabile, saldi annui, calendario delle assenze |
| `spese` | personale | note spese con ricevute e rimborsi chilometrici, approvazione del responsabile, rimborso, stampa |
| `studio` | — | adatta le viste senza programmare: colonne, filtri, ricerca, raggruppamenti, form, etichette, kanban; storico, esporta/importa |
| `documenti` | — | archivio per cartelle con permessi ereditati, anteprima, tag, cestino, zip; link pubblici a scadenza, richieste di documenti, cartelle che raccolgono gli allegati dei record |
| `discuss` | — | canali e messaggi diretti tra colleghi, menzioni, posta in arrivo (anche dal chatter), campanella in testata, email per i non letti |

`python manage.py modulo installa timesheet crm helpdesk calendario --demo --si` installa tutto, con le dipendenze
(contatti, progetti) e i dati dimostrativi. Chi installa un'app riceve il suo gruppo base; i gruppi "Responsabile"
danno anche i permessi speciali (`progetti.vedi_tutti_progetti`, `timesheet.vedi_tutte_ore`).

Per l'helpdesk via email: casella delle risposte configurata (vedi "Posta del chatter"), un indirizzo dedicato
(es. `assistenza@cliente.it`) che arrivi nella stessa casella, e quell'indirizzo nel parametro "Indirizzo email
dell'helpdesk" in `/impostazioni/`.

### Il gestionale

`python manage.py modulo installa fatturazione magazzino acquisti --demo --si` installa il ciclo commerciale
completo. Il flusso: **prodotto → preventivo → ordine → consegna (DDT) → fattura → incasso**, e dal lato fornitori
**ordine d'acquisto → ricevimento**.

- Le app si parlano con segnali: con `magazzino` installato, la conferma di un ordine di vendita crea la consegna
  in bozza e quella di un ordine d'acquisto il ricevimento; senza, vendite e acquisti funzionano lo stesso.
- La giacenza è la somma dei movimenti; il parametro "Consenti giacenze negative" in `/impostazioni/` decide se una
  consegna può spedire più di quanto c'è.
- Numeri: preventivi `PV/anno/n` alla creazione, ordini `OV/anno/n` alla conferma, DDT alla spedizione, fatture
  `n/anno` solo all'**emissione** (le bozze non consumano numeri; le note di credito usano la stessa sequenza e
  la data deve seguire quella dell'ultima fattura emessa). Una fattura emessa non si modifica: si storna con una
  nota di credito.
- Fattura elettronica: in `/fatturazione/dati/` regime fiscale, IBAN e REA dell'azienda (con partita IVA e
  indirizzo nella sua anagrafica); il bottone "Fattura elettronica (XML)" di una fattura emessa scarica
  `IT<partita IVA>_<progressivo>.xml` in formato FPR12. L'invio allo SDI non è incluso (modulo `sdi` a parte).
- Il registro IVA delle vendite (`/fatturazione/registro-iva/`) riepiloga per mese o anno, anche in CSV.

### SDI, personale, note spese

- **SDI** (`/sdi/`): il canale si sceglie per azienda in `/impostazioni/`.
  - **manuale** (default): dalla fattura emessa "Invia allo SDI" prepara l'XML, lo si carica sul portale
    "Fatture e Corrispettivi", si segna come caricato e si caricano qui le notifiche ricevute (anche in zip);
  - **PEC**: indirizzo, server SMTP e casella IMAP della PEC aziendale; un lavoro pianificato legge la casella
    ogni 15 minuti (serve il worker). L'indirizzo dello SDI comunicato nella prima ricevuta si memorizza da solo;
  - **prova**: simula la consegna, solo per demo e test.
  Ogni XML si valida con lo schema FatturaPA 1.2.2 (copia locale in `addons/sdi/schemi/`, serve `lxml`) prima
  di partire. Dopo uno scarto si corregge e si reinvia con un nuovo progressivo. Le fatture dei fornitori
  arrivano dalla stessa PEC o si caricano (XML, `.p7m` estratto con `openssl`, zip): il fornitore si riconosce
  o si crea dalla partita IVA; si registrano, si pagano per scadenza e finiscono nel registro IVA acquisti.
  Le credenziali PEC stanno nei parametri del database: proteggere l'accesso a `/impostazioni/`.
- **Personale**: ogni dipendente collegato a un utente chiede ferie e permessi da "Le mie assenze"; approva il
  suo responsabile (o quello del reparto) o chi ha "vede tutte le assenze". I giorni si contano lavorativi, senza
  festività nazionali (Pasqua compresa); le spettanze dell'anno sono in proporzione al periodo lavorato.
- **Note spese**: ricevuta obbligatoria e limite per categoria; il rimborso chilometrico calcola km × tariffa.
  Il responsabile approva, l'amministrazione ("vede tutte le note") segna il rimborso.

### Studio, Documenti, Discuss

- **Studio** (`/studio/`, superuser o gruppo "Studio / Amministratore"): per ogni vista si scelgono e ordinano
  (trascinando) colonne, filtri, campi di ricerca, raggruppamenti, totali, ordinamento, righe per pagina, il layout
  del form (sezioni, righe, campi affiancati, singoli campi personalizzati) e le etichette. Si salvano solo le
  differenze dall'originale, così il resto segue gli aggiornamenti del modulo; i campi che un aggiornamento toglie
  si ignorano. Ogni salvataggio tiene la versione precedente (ultime 20); "Esporta" e "Importa" portano tutte le
  personalizzazioni e i campi personalizzati globali da un'istanza all'altra.
- **Documenti** (`/documenti/`): i gruppi vuoti di una cartella ereditano quelli della madre (in cima: tutti gli
  utenti dell'app); il gruppo "Responsabile" vede tutto. Una cartella collegata a un tipo di record (es. le
  fatture) raccoglie gli allegati caricati sui suoi record, senza copiarli. I link pubblici
  (`/documenti/condivisi/<token>/`) scadono, si revocano, registrano ogni accesso e hanno un limite di 60
  richieste al minuto per IP (serve una cache condivisa, es. Redis, con più processi gunicorn).
- **Discuss** (`/discuss/`): la conversazione aperta si aggiorna ogni 3 secondi e la campanella ogni 30 (niente
  websocket). All'installazione tutti entrano nel canale «generale». Le menzioni (`@username`) e i messaggi
  diretti non letti da 15 minuti arrivano per email (lavoro pianificato ogni 10 minuti: serve il worker).

### Assistente AI

Spec `docs/superpowers/specs/2026-10-29-adabox-hub-modulo-ai-design.md`; fasi AI-1 (fondamenta), AI-2 (strumenti
dalle app) e AI-3 (proattività) completate.

- **Configurazione** (gruppo «AI / Amministratore»):
  - in `/ai/provider/` la chiave API di Anthropic, salvata cifrata con `CHIAVE_CIFRATURA` o, se manca, con una
    chiave derivata da `SECRET_KEY`; in `/ai/chiavi/` una chiave diversa per azienda;
  - in `/ai/modelli/` modelli e prezzi (all'installazione: Claude Haiku, Sonnet e Opus 5.5);
  - in `/ai/profili/` quale catena di modelli usa ogni compito (chat, titoli, riassunti, pianificate,
    classificazione), anche per singola app o azienda. Il modello successivo della catena entra solo se il
    precedente fallisce prima di rispondere;
  - Ollama, OpenRouter, OpenAI, vLLM e Gemini si aggiungono come provider "compatibile OpenAI" con il loro URL.
- **Licenza**:
  - si carica in `/ai/licenza/` il file JSON firmato da ICHNOBYTE con
    `python manage.py ai_licenza --chiave privata.pem --cliente ... --scadenza AAAA-MM-GG --utenti N`;
  - la firma si verifica con `MODULI_CHIAVI_FIDATE`, le stesse chiavi dei pacchetti;
  - in sviluppo `AI_LICENZA_SVILUPPO=True` simula una licenza;
  - il tetto di spesa mensile per azienda (default 50 $) e la soglia dell'avviso agli amministratori stanno in
    `/impostazioni/`. I consumi di ogni chiamata sono in `/ai/consumi/`.
- **Come funziona**:
  - ogni domanda è un turno eseguito in un thread (o nel processo con `AI_TURNI_SINCRONI=True`);
  - il contesto del modello si ricostruisce dal log degli eventi, in sola aggiunta: i blocchi di ragionamento
    di Claude tornano invariati;
  - il prompt di sistema è stabile e la cache del prefisso è attiva. Data, utente e azienda viaggiano nel
    messaggio dell'utente;
  - budget per turno: 12 passi, 300 secondi, 0,50 $;
  - lo streaming è Server-Sent Events su `/ai/flusso/<turno>/` e riprende da dove era rimasto se la connessione
    cade.
- **Strumenti dalle app** (AI-2):
  - letture generiche con la vista come argomento (`vendite.ordini`): `elenco_viste`, `descrivi_vista`,
    `cerca_record`, `leggi_record`, `aggrega_record`. Usano le `ModelView` con l'utente e l'azienda di chi chiede,
    comprese le personalizzazioni di Studio; i campi sensibili (password, chiavi, token, segreti) sono esclusi;
  - scritture: `crea_record` (anche con le righe del documento), `modifica_record`, `elimina_record`,
    `esegui_bottone`, `esegui_azione`, `pianifica_attivita`. Non eseguono nulla: preparano una **proposta**
    validata con lo stesso form del browser, mostrata sotto la risposta con «Conferma» / «Annulla». Alla conferma
    si esegue l'operazione salvata, con i permessi ricontrollati; si rifiuta se è passato più di un giorno o se
    il record è cambiato nel frattempo. Le irreversibili chiedono anche una spunta. L'esito finisce nel chatter
    del record e arriva al modello nel messaggio successivo;
  - nei bottoni e nelle azioni delle `ModelView`, l'attributo `rischio = "irreversibile"` (invio, emissione,
    conferma con numero, movimenti di magazzino) e `ai = False` (download, stampe) come `short_description`;
  - `grafico` (barre, linee, torta) e `tabella`: il modello scrive solo la specifica, i dati li calcola il
    database e il disegno lo fa il kernel in SVG. Si salvano con la stella, si riaprono con i dati di oggi in
    `/ai/artifact/<id>/` e si esportano in CSV;
  - le app aggiungono strumenti propri con la chiave `"ai": "<app>.ai"` del manifest (un modulo che chiama
    `registra`); esempio `calendario.ai` con `calendario_agenda`.
- **Attività pianificate** (AI-3):
  - «ogni lunedì alle 8 mandami gli ordini aperti» in chat diventa, dopo la conferma, un'attività che l'assistente
    esegue da solo con i permessi di chi l'ha chiesta (strumento `crea_pianificata`; `preset=riepilogo_mattino`
    per il riepilogo della giornata). Ricorrenze: giorni della settimana, un giorno del mese, ogni N ore, N minuti
    prima di ogni evento del calendario (una volta per evento);
  - le gestisce la pagina **Pianificate** (`/ai/pianificate/`): ognuno le proprie, gli amministratori tutte;
    bottoni «Esegui ora», «Sospendi», «Riattiva»;
  - il worker le controlla ogni minuto (voce `cron` del manifest) e le esegue con il profilo «Attività
    pianificate» e il tetto di spesa dell'azienda. Dopo 3 esecuzioni non riuscite di fila la pianificazione si
    sospende e il proprietario riceve un'email;
  - il risultato va sempre nella conversazione della pianificazione (grafici e tabelle compresi) e, se scelto, in
    Discuss come messaggio diretto dell'utente di sistema `assistente-ai` (non attivo, senza password) e per email.
    I link assoluti usano `SITO_URL`;
  - le modifiche ai dati restano proposte da confermare nella conversazione.
- **Produzione**: lo streaming lo serve il servizio `stream` del compose (uvicorn, ASGI), e nginx gli instrada
  `/ai/flusso/`; il resto resta su gunicorn (WSGI). Quando cambiano i moduli installati, `stream` risponde 503 e
  si riavvia da solo, come il worker.

## Distribuire i moduli

Un modulo si consegna come pacchetto zip firmato da ICHNOBYTE; ogni istanza accetta solo le chiavi di cui si fida.

1. **Chiavi** (una volta): `python manage.py modulo chiavi --uscita ~/chiavi/moduli.pem` crea la chiave privata
   (da custodire fuori dal repository) e stampa la chiave pubblica e la sua impronta. Sulle istanze:
   `MODULI_CHIAVI_FIDATE=<chiave pubblica>` nel `.env`. In produzione la firma è obbligatoria
   (`MODULI_FIRMA_OBBLIGATORIA`, default il contrario di `DEBUG`).
2. **Collaudo** prima di pubblicare: `python manage.py modulo collauda crm` (o `--tutti`) installa il modulo con le
   sue dipendenze in un'istanza usa e getta (DB vuoto), carica i demo, esegue i suoi test e lo disinstalla.
3. **Pacchetto**: `python manage.py modulo impacchetta crm --firma ~/chiavi/moduli.pem` crea `dist/crm-1.0.1.zip`
   con la descrizione (SHA-256 di ogni file) e la firma.
4. **Consegna**, in uno dei due modi:
   - **caricamento**: da `/moduli/` → "Carica un modulo", oppure `python manage.py modulo carica crm-1.0.1.zip`;
   - **catalogo**: `python manage.py modulo indice dist/ --firma ~/chiavi/moduli.pem --url-base https://…/moduli`
     crea `indice.json` e `indice.sig`; pubblica la cartella e imposta sulle istanze
     `MODULI_CATALOGO_URL=https://…/moduli/indice.json`. In `/moduli/` compare la sezione "Catalogo" con i moduli
     nuovi o aggiornati e il bottone "Scarica".
5. **Installazione o aggiornamento**: il caricamento controlla il pacchetto (firma, hash, percorsi, dimensioni,
   manifest) e lo estrae in `addons/` senza toccare il database; poi si installa o aggiorna dalla scheda del modulo,
   con il backup automatico. Una versione minore di quella presente è rifiutata; la cartella precedente resta in
   `backup/moduli/`.

## Comandi `modulo`

| Comando | Effetto |
|---|---|
| `modulo lista` | moduli su disco e installati, versioni, stato |
| `modulo verifica <cartella>` | valida il manifest |
| `modulo installa <slug>... [--demo] [--riavvia] [--si]` | backup, stato, migrazioni, fixture, gruppi, hook; installa anche le dipendenze mancanti (chiede conferma, salvo `--si`) |
| `modulo aggiorna <slug>...` / `--tutti` `[--riavvia]` | per i moduli con versione nuova su disco |
| `modulo disinstalla <slug> [--elimina-dati] [--riavvia] [--si]` | rifiuta se altri moduli ne dipendono; senza `--elimina-dati` le tabelle restano |
| `modulo sincronizza` | allinea la tabella `Modulo` al disco |
| `modulo chiavi` · `impacchetta` · `carica` · `indice` · `collauda` | distribuzione dei moduli (vedi sopra) |

Il lavoro vero lo fa `modulo_applica` (uso interno) in un processo nuovo, che legge il file
di stato aggiornato e quindi ha il modulo in `INSTALLED_APPS`. Se fallisce, il file di stato
torna com'era e il modulo va in stato `errore`. Log in `logs/moduli.log`.

La pagina **`/moduli/`** (solo superuser) lancia gli stessi comandi con `--riavvia` e mostra
il log in pagina. `RELOAD_STRATEGY` decide come si ricarica il server: `gunicorn` (SIGHUP al
pid in `GUNICORN_PIDFILE`), `runserver` (tocca `config/settings.py`), `none` (a mano).

## Multi-azienda

Ogni utente ha un `ProfiloUtente` con le aziende consentite e una predefinita (creato in
automatico con tutte le aziende attive). L'azienda corrente (`request.azienda`) si cambia dal
selettore nella barra dell'app; via API con l'header `X-Azienda: <pk>`. Le aziende si
gestiscono da `/core/aziende/`.

## API

`/api/v1/`, documentazione su `/api/v1/docs` (solo utenti autenticati). Autenticazione con la
sessione (stesso dominio, con CSRF) o `Authorization: Bearer <token>`; i token si creano dal
profilo e si vedono in chiaro una volta sola. Per ogni `ModelView` con `api = True`:
`GET` lista (`q`, `f_<campo>`, `o`, `p`, `per_page` fino a 200), `POST`, `GET/PATCH/DELETE
/<pk>/`, con gli stessi permessi e filtri della vista; errori di validazione come `422
{"errori": {...}}`. Fissi: `GET /api/v1/me/`, `GET /api/v1/moduli/` (superuser).

## Backup e ripristino

Prima di ogni installazione, aggiornamento o disinstallazione il kernel salva il DB in
`backup/` (`<data>-pre-<operazione>-<slug>.sqlite3` o `.dump`) e tiene gli ultimi
`BACKUP_CONSERVA` (default 10). Senza backup riuscito l'operazione non parte.

- **SQLite**: ferma il server e copia il file: `cp backup/<file>.sqlite3 db.sqlite3`.
- **Postgres**: `pg_restore --clean --if-exists --dbname "$DATABASE_URL" backup/<file>.dump`.

Dopo un ripristino rimetti `addons/installed.json` coerente con il DB (la riga del modulo
installato prima del backup va tolta a mano) e riavvia.

## Sicurezza inclusa

- django-axes: blocco per coppia username+IP. Al 5° tentativo fallito (`AXES_FAILURE_LIMIT`)
  il login risponde HTTP 429 con la pagina di blocco, per 15 minuti (`AXES_COOLOFF_MINUTES`).
  Un login riuscito azzera il conteggio.
- Sessione 30 min rinnovata a ogni richiesta, cookie HttpOnly, `X-Frame-Options: DENY`.
- Con `DEBUG=False`: cookie Secure, `X-Forwarded-Proto` dal proxy, log su file in
  `logs/`, mail agli `ADMINS` sugli errori 500. HSTS spento finché non lo accendi
  tu con `SECURE_HSTS_SECONDS`.

## Produzione

- Docker: `docker compose up -d --build`. `deploy/entrypoint.sh` esegue `collectstatic` e
  `migrate`, poi `exec gunicorn ... --pid /tmp/gunicorn.pid`: il pidfile serve alla ricarica
  dopo un'installazione (`RELOAD_STRATEGY=gunicorn`, già impostato nel compose).
  `addons/`, `backup/`, `media/` e `private/` (allegati) sono volumi: restano sull'host. Il servizio `worker`
  esegue lavori e pianificazioni; nginx serve gli allegati con `X-Accel-Redirect` (`ALLEGATI_X_ACCEL=True`).
  Installare un modulo nel container:
  `docker compose exec web python manage.py modulo installa <slug> --si --riavvia`.
- Servizio `stream` (uvicorn) per lo streaming dell'assistente AI su `/ai/flusso/`: nginx lo raggiunge senza
  buffer (`proxy_buffering off`, vedi `deploy/nginx.conf`).
- Database: Postgres (`DATABASE_URL=postgres://...`); SQLite solo in sviluppo. L'immagine
  include `postgresql-client` per `pg_dump`.

- `SECRET_KEY` ha un default di sviluppo: in produzione va **sempre** impostata in `.env`.
  `python manage.py check --deploy` la segnala (`security.W009`) se resta quella di default.
- Proxy: la configurazione presuppone esattamente **un** reverse proxy fidato (nginx)
  davanti a gunicorn, con queste direttive nel `location` che fa `proxy_pass`:
  ```nginx
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
  ```
  `$proxy_add_x_forwarded_for` aggiunge **in coda** a `X-Forwarded-For` l'IP reale del
  client; le voci a sinistra le ha scritte il client e sono falsificabili. Per questo
  axes (tramite django-ipware, installato con `django-axes[ipware]`) usa
  `AXES_IPWARE_PROXY_COUNT=0` e `IPWARE_STRICT=False`: prende sempre l'ultima voce.
  Non usare `AXES_IPWARE_PROXY_COUNT=1`: con ipware 8 conta i proxy *dentro*
  l'header, quindi restituirebbe la voce scelta dal client (o nessun IP per le
  richieste normali). Con più proxy in catena (es. un bilanciatore davanti a nginx)
  va rivisto il conteggio (`config/tests/test_axes_ip.py`).
  gunicorn deve ascoltare solo su `127.0.0.1` (o socket unix): se l'app è raggiungibile
  direttamente, `X-Forwarded-Proto`/`X-Forwarded-For` sono falsificabili e il blocco
  di axes si aggira cambiando IP dichiarato.
- Mail: senza `EMAIL_URL` le mail (errori 500 agli `ADMINS`) finiscono sulla console.
  In produzione imposta in `.env` per esempio
  `EMAIL_URL=smtp+tls://utente:password@smtp.example.com:587` (`smtp+ssl://` per la 465;
  caratteri speciali nella password vanno codificati, es. `@` → `%40`) e
  `DEFAULT_FROM_EMAIL` con un mittente accettato dal server SMTP. Le mail agli `ADMINS`
  partono solo con `DEBUG=False`.
- Con `DEBUG=False` Django non serve gli static: esegui `python manage.py collectstatic`
  e fai servire `STATIC_ROOT` (`staticfiles/`) da nginx.
- `check --deploy` con la configurazione di default segnala solo `security.W004` (HSTS)
  e `security.W008` (SSL redirect): sono spenti di proposito finché il 443 non è verificato,
  poi si accendono con `SECURE_HSTS_SECONDS` e `SECURE_SSL_REDIRECT` in `.env`.
- Per provare la modalità produzione in locale su http, imposta in `.env`
  `SESSION_COOKIE_SECURE=False` e `CSRF_COOKIE_SECURE=False` (altrimenti il login
  non funziona: il browser non rimanda i cookie Secure su http).

## Portare `theme/` in un altro progetto

`theme/` non importa nulla dal resto del progetto, ma si aspetta che il progetto
che lo ospita abbia:

- `"theme"` in `INSTALLED_APPS` **prima** di `"django.contrib.admin"` (sovrascrive
  i template dell'admin);
- `"theme.context_processors.theme"` in `TEMPLATES[0]["OPTIONS"]["context_processors"]`
  (insieme a `request`, `auth` e `messages`);
- `path("", include("theme.urls"))` nell'urlconf principale (favicon);
- le viste di `django.contrib.auth` con i nomi URL `login`, `logout`,
  `password_change` e `password_change_done` (es. `path("accounts/", include("django.contrib.auth.urls"))`);
- `django.contrib.admin` installato e incluso negli URL: l'header punta a `admin:index`;
- facoltativo: il dizionario `THEME` nei settings (senza, valgono i default di
  `theme/context_processors.py`);
- facoltativo: una route `core:profilo`; se esiste, il menu utente mostra il link Profilo.

## Test

```bash
pytest                    # tutta la suite, compresa l'installazione vergine di todo
pytest -m "not slow"      # senza i test end-to-end
```

I test di concorrenza (worker, pianificazioni, sequenze) girano solo su Postgres:

```bash
deploy/test-postgres.sh           # Postgres usa e getta in Docker, solo i test marcati postgres
deploy/test-postgres.sh -q        # tutta la suite su Postgres
```

I test che generano PDF veri girano nell'immagine Docker (Pango e font): `docker compose build web && deploy/test-pdf.sh`.
