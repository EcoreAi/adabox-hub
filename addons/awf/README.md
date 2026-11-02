# Agentic Workforce (`awf`)

Collega adabox ad **Agentic Workforce**, il servizio che dà in affitto alle aziende agenti AI (squadre di agenti).
Gli agenti lavorano nel gestionale **solo attraverso Agate**, il garante neutrale: ogni loro azione arriva qui come
chiamata MCP fatta da Agate, dopo che le regole di Agate (e, se serve, una persona) l'hanno decisa. Per questo, a
differenza della chat, le modifiche non diventano una proposta da confermare: la decisione di Agate prende il posto
della conferma.

Il modulo implementa il contratto dei plugin di reparto di tipo `django` (`docs/plugin-api.md` del repository
`agentlia-workforce`) con le convenzioni di adabox. Non usa il pacchetto generico `django-agentlia`.

Parole: nelle pagine per tutti si dice **contratto** (l'ingaggio della fabbrica), **periodo di prova**
(l'osservazione), **cosa può fare** (le operazioni ammesse). MCP, bearer, prefisso e codici `wfc_` restano nella
scheda **Avanzate**, per chi installa e assiste.

## L'area «Agenti AI»

Non è un'app della barra in alto (`"application": False`): la voce **Agenti AI** sta nel menu del profilo
(chiave `menu_profilo` del manifest), tra «Cambia password» e «Amministrazione», solo per chi ha
`awf.change_collegamento` (gruppo «AWF / Amministratore»). Chi non ha il permesso non vede nulla di nuovo. L'area ha
quattro schede, nella barra dell'app come le altre app:

- **Negozio** (`/awf/negozio/`, la prima pagina): una scheda per agente dal catalogo della fabbrica, con i gettoni dei
  reparti (`?reparto=crm`): icona, nome, frase, 2-3 vantaggi, giorni di prova, «da 150 €/settimana» (period_eur × 7 /
  period_days) e i bottoni **Scopri** e **Assumi**. Se la fabbrica non risponde: «La fabbrica non risponde, riprova tra
  poco». Senza indirizzo della fabbrica, un solo campo («Prima di iniziare»). `/awf/catalogo/` porta qui.
- **Scheda dell'agente** (`/awf/negozio/<slug>/`): Cosa fa per te, Una giornata tipo, Cosa può fare ✓ (in parole, con
  i nomi delle viste di adabox), Cosa non farà mai ✗, Quali dati vede (e cosa non vede), Quanto costa con il calcolo
  (settimane → `period_eur × ⌈settimane·7 / period_days⌉`, in pagina senza ricaricare e con `?settimane=`), consumo AI
  con il ricarico, credito iniziale, giorni di prova, Domande frequenti, **Assumi**. Avvisa se l'agente usa un'app non
  installata. La vetrina viene da `showcase` del catalogo (§7.1, facoltativo); quando manca si ricava da descrizione,
  ruoli e operazioni, con alcune domande frequenti di base.
- **Assumi** (`/awf/assumi/<slug>/`): **una pagina sola**, già compilata con valori prudenti — 4 settimane,
  responsabile chi chiede, nessuna persona, «cosa può fare» con le scelte proposte — un riepilogo (agente, cosa fa,
  costo stimato, prova, cosa succede adesso) e un bottone **Conferma**. Tutto si cambia in **Personalizza** (chiuso):
  settimane, note per Agentlia, reparto (testo libero, con i reparti di Personale come suggerimenti se l'app c'è),
  responsabile, persone a cui passa il lavoro (persone attive: mai utenti agente né clienti del portale) e, per ogni
  operazione, **Sì / Con il tuo ok / Mai**: le letture sono sempre sì (senza l'agente non lavora), le modifiche sì, le
  irreversibili con il tuo ok. Con un errore la pagina torna con quello che si era scritto e Personalizza aperta.
- **Richieste** (`/awf/richieste/`): una scheda per richiesta come un ordine da seguire, **Richiesta inviata →
  Contratto pronto → Periodo di prova → Al lavoro** (dallo stato della richiesta e dall'ultimo stato del contratto:
  `observe_until`, `status`, `blocked`), il messaggio di Agentlia, **un solo bottone principale** per quello che serve
  ora — «Collega adabox ad Agate» (una volta sola, finché manca), «Conferma il contratto» (`approve_url`, con una
  riga sul perché), «Vedi i tuoi agenti» — e «Ritira la richiesta» finché si può. Una richiesta collegata prima di
  una più recente è «Sostituita».
- **I miei agenti** (`/awf/miei/`): il contratto (fase: in prova, al lavoro, in pausa, scaduto; giorni rimasti;
  consumo AI; quante azioni **aspettano il tuo ok**, dalle approvazioni del webhook) e una scheda per agente con quello
  che ha fatto **oggi** (dal registro delle chiamate: letture, modifiche, «avrebbe cambiato» nella prova, fermate).
  Bottoni: **Cosa può fare** (`/awf/miei/<pk>/cosa-puo-fare/`: le stesse scelte, che riammettono o spengono le
  operazioni della squadra e riallineano i permessi), **Cambia persone** (`/awf/miei/<pk>/persone/`), **Metti in
  pausa · Rinnova · Disdici** (la pagina del contratto in Agate: si decide lì). Senza agenti: «Non hai ancora agenti —
  Vai al Negozio».
- **Avanzate** (`/awf/avanzate/`): collega adabox ad Agate (indirizzo MCP e chiave, mostrata una volta), indirizzo
  della fabbrica e le pagine tecniche: **Stato e collegamento** (`/awf/stato/`: stato del contratto, codice `wfc_`,
  segreto dei webhook, azienda degli agenti, ultime chiamate), **Cosa può fare, in dettaglio** (`/awf/operazioni/`,
  l'elenco delle operazioni ammesse), **Approvazioni** (`/awf/approvazioni/`), **Utenti degli agenti**
  (`/awf/agenti/`), Impostazioni.

### Cosa succede alla conferma

Nella stessa transazione: adabox ammette le operazioni scelte («Sì» e «Con il tuo ok» creano o riaccendono la voce,
«Mai» la spegne; le operazioni non disponibili qui restano fuori) e riallinea i permessi del gruppo «AWF / Agenti»,
**poi** chiede la squadra alla fabbrica (`POST /api/hire-requests`, §7.2 invariato). Così `plugin.operations`
dichiara alla fabbrica proprio le operazioni che gli agenti useranno. Se la fabbrica rifiuta, la transazione si
annulla e non resta ammesso nulla. La richiesta salva reparto, responsabile, persone e le scelte (`scelte`:
`{"strumento|vista": "si" | "ok" | "mai"}`); nelle note per Agentlia, dopo quelle della persona, va una riga «Lavora
per: reparto …; responsabile …; passa il lavoro a …» (solo i nomi). Se adabox è già collegato, un battito dichiara la
versione nuova. Il bearer MCP resta un passaggio a parte, in Avanzate.

«Con il tuo ok» per ora vale come «Sì» nelle operazioni ammesse: la conferma di una persona la chiede una regola di
Agate impostata da chi gestisce Agate. La pagina lo dice. La scelta è salvata per quando le regole nasceranno da sole.

## Cosa fa (in dettaglio)

- **Server MCP** su `/awf/mcp/` (JSON-RPC su POST: `initialize`, `ping`, `tools/list`, `tools/call`), autenticato
  con un bearer di cui si salva solo l'impronta SHA-256, confrontata a tempo costante.
  - `tools/list` espone uno strumento MCP per ogni strumento dell'assistente AI ammesso, con il suo schema; se le voci
    ammesse indicano delle viste, l'argomento `vista` è ristretto a quelle (`enum`).
  - Le annotazioni seguono il `rischio` dello strumento: lettura → `readOnlyHint: true`; scrittura →
    `readOnlyHint: false, destructiveHint: false`; irreversibile → `destructiveHint: true`. Un bottone o
    un'azione irreversibile in una vista ammessa rende irreversibile tutto `esegui_bottone` / `esegui_azione`.
    Agate le legge all'importazione: lettura = `read`, scrittura = `write`, irreversibile = `irreversible`.
  - `tools/call` risolve l'agente, usa l'utente agente e l'azienda degli agenti, controlla la coppia (strumento,
    vista), esegue le letture direttamente e le scritture con anteprima e operazione in una transazione; nel chatter
    del record scrive «Tramite agente AWF <nome>». Rispetta `_meta.idempotencyKey`. Gli errori non riportano mai i
    valori dei parametri.
  - Ogni chiamata finisce nel registro (`Chiamata`): da qui i conti di «I miei agenti».
- **Cosa può fare (operazioni ammesse)**: l'elenco chiuso di coppie (strumento, vista facoltativa). Di default solo
  letture (`elenco_viste`, `descrivi_vista`, `cerca_record`, `leggi_record`, `aggrega_record`, `data_e_ora`). Non si
  possono ammettere gli strumenti che chiamano modelli o servizi o che vivono nella chat (`chiedi_esperto`,
  `classifica`, `previsione`, `crea_pianificata`, `grafico`, `tabella`...) né le viste di `ai` e `awf`.
- **Collegamento alla fabbrica**: dalla conferma in Agate (da solo) o con un codice `wfc_...`; battito ogni 15
  minuti (e all'apertura delle pagine), stato del contratto.
- **Agenti**: un utente `awf-<nome>` per ogni agente del contratto, più `awf-tecnico` per le chiamate che non indicano
  un agente.
- **Approvazioni in attesa**: dal webhook firmato di Agate, con il link per decidere in Agate.
- **Eventi alla fabbrica**: un record assegnato a un agente → `record.assigned` con solo vista, id e agente.

## Installazione in adabox

```bash
python manage.py modulo installa awf --si          # installa anche ai, se manca
```

All'installazione: elenco delle operazioni con le sole letture, gruppo «AWF / Agenti», azienda degli agenti =
la prima azienda attiva. Il gruppo «AWF / Amministratore» (tutti i permessi di `awf`) dà accesso all'area. Nelle
Impostazioni: «Agenti sempre come nel periodo di prova» e «Avvisa la fabbrica quando un'attività è assegnata a un
agente».

Per i test: `awf` è in `ADDONS_FORCE` di `pytest.ini`;
`python -m pytest addons/awf -q -p no:cacheprovider`. Le migrazioni:
`ADDONS_FORCE=ai,awf python manage.py makemigrations awf`.

## Collegamento con un codice (Avanzate → Stato e collegamento)

Per un contratto preparato da Agentlia con un codice; i contratti chiesti dal Negozio si collegano da soli.

1. Nella fabbrica, pagina del contratto: copia il codice di collegamento (`wfc_` + 32 caratteri, vale 7 giorni,
   una volta sola).
2. In adabox, Agenti AI → Avanzate → Stato e collegamento: incolla codice, indirizzo della fabbrica, indirizzo
   pubblico di questa istanza e scegli l'azienda in cui lavorano gli agenti.
3. Il modulo chiama `POST {fabbrica}/api/plugins/connect` con `kind: "django"`, la versione, `base_url` e le
   operazioni ammesse nel formato del contratto. Salva il token `wpt_...` cifrato e crea gli utenti agente.
4. La pagina mostra **una volta sola** l'indirizzo MCP (`{base_url}/awf/mcp/`) e il bearer da dare ad Agate. Se
   lo perdi, se ne genera uno nuovo (il vecchio smette di valere), anche da Avanzate.

La versione dichiarata è quella del modulo più l'impronta delle operazioni (es. `1.0.0+3fa2c91b`): cambia quando
cambia l'elenco, e si dichiara al battito.

## Catalogo e richiesta (§7 del contratto con la fabbrica)

- **Catalogo**: `GET {fabbrica}/api/catalog?kind=django&saas=adabox`, pubblico, tenuto 10 minuti in cache. Di ogni
  squadra si tengono solo i campi che servono, con i tipi attesi; la vetrina (`showcase`: icon, tagline, benefits ≤ 5,
  day ≤ 8 con l'ora HH:MM, never ≤ 6, faq ≤ 6) solo come testo semplice.
- **Indirizzo della fabbrica**: quello del collegamento; se manca, `AWF_FORGE_URL` (impostazione Django o variabile
  d'ambiente); se manca anche quello, il Negozio lo chiede.
- **Richiesta**: `POST {fabbrica}/api/hire-requests` con squadra e versione, settimane, note, i dati dell'azienda
  (nome, partita IVA, email di chi chiede o dell'azienda, nome di chi chiede), il blocco `plugin` (`kind: django`,
  `saas: adabox`, versione, `base_url` e le operazioni ammesse **ora**, cioè già con quelle scelte) e, se il modulo
  `agate` è attivo e collegato, il blocco `agate` (`gateway_url`, `console_url`). Il token `wfr_...` si salva cifrato
  in `RichiestaAgenti` e serve solo a leggere lo stato e a ritirarla.
- **Stato**: ogni 5 minuti (lavoro «Stato delle richieste di agenti») e all'apertura di Richieste (se l'ultima
  lettura ha più di un minuto) si legge `GET /api/hire-requests/{id}` per le richieste inviate o da confermare. Una
  richiesta collegata, rifiutata o ritirata non si legge più, e non torna mai indietro da collegata.
- **Collegamento da solo**: alla prima lettura `connected` arriva `plugin_token` (`wpt_...`). adabox fa quello che
  fa il collegamento con il codice (`fabbrica.completa`): salva il token cifrato, l'installazione, la versione e lo
  stato, sceglie l'azienda della richiesta e crea gli utenti agente. Il bearer MCP resta quello già dato ad Agate.
  Se la lettura con il token si perde, la richiesta resta collegata con un messaggio: serve un codice da Agentlia.
- **Collega adabox ad Agate, una volta sola** (Avanzate): va fatto **prima** che Agentlia proponga il contratto,
  perché Agate accetta un contratto solo se gli strumenti che la squadra userà (`awf.modifica_record`...) sono già
  attivi nel suo catalogo. Genera indirizzo e bearer del server MCP, da incollare nella console di Agate →
  Collegamenti → «Applicazione dell'azienda (server MCP)» con il prefisso `awf`. Richieste lo mostra come passo
  finché manca (`Collegamento.mcp_impronta` vuoto).

Un'istanza ha un solo collegamento: una squadra confermata prende il posto del contratto precedente.

## Assunzione guidata dalla chat

Con la chiave `"ai": "awf.ai"` del manifest il modulo dà all'assistente AI tre strumenti, visibili solo a chi
gestisce AWF (permesso `awf.change_collegamento`; anche le funzioni lo ricontrollano):

- `catalogo_agenti` (lettura, `reparto` facoltativo): gli agenti in breve (slug, nome, reparto, in breve, per te,
  ruoli, cosa può fare, cosa non farà mai, prezzo, giorni di prova, link alla scheda);
- `richiedi_squadra` (scrittura: `team`, `settimane`, `note`): diventa una **proposta** che la persona conferma con
  il bottone (il link porta alla scheda dell'agente). L'anteprima mostra agente, ruoli, durata, prezzo, il costo fisso
  stimato, il consumo AI con il ricarico, i giorni di prova, cosa può fare e i prossimi passi. Alla conferma la
  richiesta parte come dal Negozio, con le scelte proposte (si cambiano poi da I miei agenti), e l'esito porta a
  `/awf/richieste/`;
- `stato_richieste_agenti` (lettura): le richieste con stato, messaggio e prossimo passo.

I tre strumenti sono in `operazioni.ESCLUSI` (e nessuno strumento dell'app `awf` è ammissibile): non arrivano mai
agli agenti via MCP. Con il modulo `agate` attivo, `richiedi_squadra` è una scrittura come le altre.

## Configurare Agate (per chi assiste)

1. Dalla console di Agate: Collegamenti → «Applicazione dell'azienda (server MCP)», con indirizzo, bearer e
   prefisso `awf`. Oppure dalla riga di comando, con il bearer in una variabile d'ambiente del gateway di Agate:
   ```bash
   manage.py agate_import_mcp_tools <tenant> production https://erp.cliente.it/awf/mcp/ \
       --prefix awf --auth-ref env:AWF_MCP_TOKEN --internal
   ```
   Il prefisso è **`awf`**: in Agate gli strumenti si chiamano `awf.cerca_record`, `awf.modifica_record`…, come nel
   catalogo della fabbrica. Gli strumenti nascono **disattivati**: rivedi effetto, rischio e schema e attivali. Dopo
   ogni cambio di «cosa può fare» rifai l'importazione: in Agate uno schema cambiato va in quarantena finché qualcuno
   non lo rivede.
2. In Agate, Impostazioni → Webhook: registra `{base_url}/awf/agate-webhook/` con gli eventi
   `approval.requested` e `approval.decided`, e incolla il segreto `whsec_...` in Stato e collegamento. La firma
   `X-Agate-Signature: t=<unix>,v1=<hmac-sha256 hex di "t." + corpo>` si verifica con tolleranza di 5 minuti.
3. Agate indica l'agente con `_meta["agentlia/agent"]` (o `_meta["agent"]`) in `tools/call`; in alternativa
   l'argomento `agente`. Senza indicazione agisce `awf-tecnico`.

## Scelte di progetto

- **Identità degli agenti**: utenti Django `awf-<nome>` attivi, password inutilizzabile, nessuna email, mai staff né
  superuser, una sola azienda. Un nome già usato da una persona non diventa mai un agente. Un agente che la fabbrica
  non elenca più resta come utente ma le sue chiamate si rifiutano.
- **Niente interfaccia per gli agenti**: un ricevitore di `user_logged_in` svuota la sessione e risponde 403 se entra
  un utente agente; un ricevitore di `pre_save` di `TokenApi` rifiuta i token API degli agenti.
- **Permessi degli agenti**: vengono **solo** dal gruppo «AWF / Agenti», ricalcolato da «cosa può fare».
- **Azienda**: una sola, scelta in Stato e collegamento. Senza azienda non gira nessuna operazione.
- **Pagine non `ModelView`**: le tabelle di AWF non compaiono fra le viste che l'assistente (e gli agenti) può
  leggere o modificare.
- **Periodo di prova**: se l'ultimo stato del contratto è nel periodo di prova (`observe_until` futuro), bloccato o
  non `active`, o se l'impostazione lo chiede, le scritture non girano: la risposta è un errore MCP con `codice: 409`
  e la chiamata si registra con l'anteprima («cosa sarebbe successo»). Le letture continuano.
- **Assumi senza bozze**: la pagina è una sola e tutto viaggia nel modulo; nessuna bozza in sessione o nel database.
- **Eventi**: solo il nome della vista, l'id e l'agente; l'invio è un lavoro in background accodato dopo il commit.

## Cosa non fa mai

- non chiama modelli, non esegue agenti, non tiene memoria degli agenti;
- non manda alla fabbrica testi dei record: solo vista, id e nome dell'agente (e, nelle note della richiesta, i nomi
  del reparto e delle persone scelte);
- non conosce chiavi degli agenti né la chiave della fabbrica; il token della fabbrica è cifrato, il bearer MCP
  non è salvato;
- non decide approvazioni e non cambia regole di Agate: le mostra e rimanda ad Agate;
- non fa entrare gli agenti nell'interfaccia, nelle API o nell'admin.

## Prossimi passi (non ancora fatti)

- **Collegamento ad Agate con un codice solo**, senza indirizzo e bearer da copiare: sparirà il passo «Collega adabox
  ad Agate».
- **Regole in Agate dalle scelte**: «Con il tuo ok» creerà da sola la regola di approvazione in Agate (oggi la imposta
  chi gestisce Agate), e la conferma del contratto potrà avvenire da adabox.
- **Avvisi** al responsabile (riepiloghi, richieste di ok) e **persone passate agli agenti** (a chi consegnare il
  lavoro): oggi reparto, responsabile e persone si salvano e vanno solo nelle note per Agentlia.
- **Pausa, rinnovo e disdetta da adabox**: oggi si fanno nella pagina del contratto in Agate.

## Limiti

- Un solo collegamento e una sola azienda per istanza.
- Il bearer MCP è uno per installazione: l'identità dell'agente la dichiara Agate nella chiamata.
- Lo stato del contratto è quello dell'ultimo battito (al più 15 minuti di ritardo); se la fabbrica non risponde
  resta valido l'ultimo stato noto.
- Le richieste di ok (approvazioni) non dicono quale agente le ha chieste: in I miei agenti si contano per contratto.
- Gli eventi coprono le attività del kernel e i modelli con un campo `assegnatario` verso gli utenti.
- Le letture del registro si tengono 90 giorni; le scritture restano.
