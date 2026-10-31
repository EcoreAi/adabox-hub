# Agentic Workforce (`awf`)

Collega adabox ad **Agentic Workforce**, il servizio che dà in affitto alle aziende squadre di agenti AI. Gli
agenti lavorano nel gestionale **solo attraverso Agate**, il garante neutrale: ogni loro azione arriva qui come
chiamata MCP fatta da Agate, dopo che le regole di Agate (e, se serve, una persona nella sua console) l'hanno
decisa. Per questo, a differenza della chat, le scritture non diventano una proposta da confermare: la decisione
di Agate prende il posto della conferma.

Il modulo implementa il contratto dei plugin di reparto di tipo `django` (`docs/plugin-api.md` del repository
`agentlia-workforce`) con le convenzioni di adabox. Non usa il pacchetto generico `django-agentlia`.

## Cosa fa

- **Server MCP** su `/awf/mcp/` (JSON-RPC su POST: `initialize`, `ping`, `tools/list`, `tools/call`), autenticato
  con un bearer di cui si salva solo l'impronta SHA-256, confrontata a tempo costante.
  - `tools/list` espone uno strumento MCP per ogni strumento dell'assistente AI ammesso (vedi sotto), con il suo
    schema; se le voci ammesse indicano delle viste, l'argomento `vista` è ristretto a quelle (`enum`).
  - Le annotazioni seguono il `rischio` dello strumento: lettura → `readOnlyHint: true`; scrittura →
    `readOnlyHint: false, destructiveHint: false`; irreversibile → `destructiveHint: true`. Un bottone o
    un'azione irreversibile in una vista ammessa rende irreversibile tutto `esegui_bottone` / `esegui_azione`.
    Agate le legge all'importazione (`agate_import_mcp_tools`): lettura = `read`, scrittura = `write`,
    irreversibile = `irreversible` (sempre con approvazione).
  - `tools/call` risolve l'agente, usa l'utente agente e l'azienda degli agenti
    (`Contesto(utente=agente, azienda=...)`), controlla la coppia (strumento, vista), esegue le letture
    direttamente e le scritture con anteprima e operazione in una transazione; nel chatter del record scrive
    «Tramite agente AWF <nome>». Rispetta `_meta.idempotencyKey` di Agate: una scrittura già eseguita con la
    stessa chiave non si ripete. Gli errori non riportano mai i valori dei parametri.
  - Ogni chiamata finisce nel registro (`Chiamata`), visibile in «Stato e collegamento».
- **Operazioni ammesse**: l'elenco chiuso di coppie (strumento, vista facoltativa). Di default solo letture
  (`elenco_viste`, `descrivi_vista`, `cerca_record`, `leggi_record`, `aggrega_record`, `data_e_ora`). Non si
  possono ammettere gli strumenti che chiamano modelli o servizi o che vivono nella chat (`chiedi_esperto`,
  `classifica`, `previsione`, `crea_pianificata`, `grafico`, `tabella`...) né le viste di `ai` e `awf`.
- **Collegamento alla fabbrica** (`/awf/stato/`): codice `wfc_...`, battito ogni 15 minuti (e all'apertura
  della pagina), stato dell'ingaggio (stato, giorni rimasti, agenti, blocco, link alla console di Agate).
- **Agenti**: un utente `awf-<nome>` per ogni agente dell'ingaggio, più `awf-tecnico` per le chiamate che non
  indicano un agente.
- **Approvazioni in attesa** (`/awf/approvazioni/`): dal webhook firmato di Agate, con il link per decidere in
  Agate.
- **Eventi alla fabbrica**: un record assegnato a un agente → `record.assigned` con solo vista, id e agente.

## Installazione in adabox

```bash
python manage.py modulo installa awf --si          # installa anche ai, se manca
```

All'installazione: elenco delle operazioni con le sole letture, gruppo «AWF / Agenti», azienda degli agenti =
la prima azienda attiva. Il gruppo «AWF / Amministratore» (tutti i permessi di `awf`) dà accesso alle pagine.
Nelle Impostazioni: «Scritture degli agenti sempre in osservazione» e «Avvisa la fabbrica quando un'attività è
assegnata a un agente».

Per i test: `awf` è in `ADDONS_FORCE` di `pytest.ini`;
`python -m pytest addons/awf -q -p no:cacheprovider`. Le migrazioni:
`ADDONS_FORCE=ai,awf python manage.py makemigrations awf`.

## Collegamento alla fabbrica

1. Nella fabbrica, pagina dell'ingaggio: copia il codice di collegamento (`wfc_` + 32 caratteri, vale 7 giorni,
   una volta sola).
2. In adabox, «Agenti → Stato e collegamento»: incolla codice, indirizzo della fabbrica, indirizzo pubblico di
   questa istanza (quello da cui Agate la raggiunge) e scegli l'azienda in cui lavorano gli agenti.
3. Il modulo chiama `POST {fabbrica}/api/plugins/connect` con `kind: "django"`, la versione, `base_url` e le
   operazioni ammesse nel formato del contratto (`name`, `description`, `effect`, `risk`, `external_content`,
   `params_schema`). Salva il token `wpt_...` cifrato e crea gli utenti agente.
4. La pagina mostra **una volta sola** l'indirizzo MCP (`{base_url}/awf/mcp/`) e il bearer da dare ad Agate. Se
   lo perdi, «Rigenera il bearer MCP» ne crea uno nuovo (il vecchio smette di valere).

La versione dichiarata è quella del modulo più l'impronta delle operazioni (es. `1.0.0+3fa2c91b`): cambia quando
cambia l'elenco, e si dichiara al battito.

## Configurare Agate

1. Metti il bearer in una variabile d'ambiente del gateway di Agate (es. `ADABOX_MCP_TOKEN`) e importa gli
   strumenti:
   ```bash
   manage.py agate_import_mcp_tools <tenant> production https://erp.cliente.it/awf/mcp/ \
       --prefix adabox --auth-ref env:ADABOX_MCP_TOKEN --internal
   ```
   Gli strumenti nascono **disattivati**: rivedi effetto, rischio e schema nell'Admin di Agate e attivali.
   Dopo ogni cambio dell'elenco delle operazioni ammesse rifai l'importazione: in Agate uno schema cambiato va in
   quarantena finché qualcuno non lo rivede.
2. In Agate, Impostazioni → Webhook: registra `{base_url}/awf/agate-webhook/` con gli eventi
   `approval.requested` e `approval.decided`, e incolla il segreto `whsec_...` in «Stato e collegamento».
   La firma `X-Agate-Signature: t=<unix>,v1=<hmac-sha256 hex di "t." + corpo>` si verifica byte per byte come in
   `agategw.contracts.webhooks`, con tolleranza di 5 minuti.
3. Agate indica l'agente con `_meta["agentlia/agent"]` (o `_meta["agent"]`) in `tools/call`; in alternativa
   l'argomento `agente`. Senza indicazione agisce `awf-tecnico`.

## Scelte di progetto

- **Identità degli agenti**: utenti Django `awf-<nome>` attivi (le `ModelView` controllano i permessi solo agli
  utenti attivi), password inutilizzabile, nessuna email, mai staff né superuser, una sola azienda (quella degli
  agenti). Un nome già usato da una persona non diventa mai un agente. Un agente che la fabbrica non elenca più
  resta come utente (le sue azioni passate restano sue) ma le sue chiamate si rifiutano.
- **Niente interfaccia**: oltre alla password inutilizzabile e alla mancanza di email, un ricevitore di
  `user_logged_in` svuota la sessione e risponde 403 se entra un utente agente, con qualunque backend; un
  ricevitore di `pre_save` di `TokenApi` rifiuta i token API degli agenti. Così non serve toccare i middleware né
  i backend del kernel (le liste in `config/settings.py`).
- **Permessi**: vengono **solo** dal gruppo «AWF / Agenti», ricalcolato dalle operazioni ammesse: per ogni voce
  con una vista, i permessi che servono allo strumento su quel modello (vedere; aggiungere, modificare,
  eliminare; i permessi dei bottoni e delle azioni). Le voci senza vista non danno permessi. A ogni chiamata
  l'utente agente viene riportato nei suoi confini: se un'altra app lo ha messo nei suoi gruppi («tutti gli utenti
  attivi»), ne esce.
- **Azienda**: una sola, scelta in «Stato e collegamento». Senza azienda configurata non gira nessuna operazione
  (le viste per azienda, senza azienda, mostrerebbero tutto).
- **Pagine non `ModelView`**: così le tabelle di AWF (e l'elenco delle operazioni ammesse) non compaiono fra le
  viste che l'assistente, e quindi gli agenti, può leggere o modificare.
- **Osservazione**: se l'ultimo stato dell'ingaggio è in osservazione (`observe_until` futuro), bloccato
  (`blocked`) o non `active`, o se l'impostazione lo chiede, le scritture non girano: la risposta è un errore MCP
  con `codice: 409` e la chiamata si registra con l'anteprima («cosa sarebbe successo»). Le letture continuano.
- **Eventi**: `model` è il nome della vista del record (es. `todo.attivita`), cioè quello che gli strumenti MCP
  accettano come `vista`; senza vista, l'etichetta del modello. Per un'attività del kernel si segnala il record su
  cui è pianificata. L'invio è un lavoro in background accodato dopo il commit: un errore non tocca il salvataggio.

## Cosa non fa mai

- non chiama modelli, non esegue agenti, non tiene memoria degli agenti;
- non manda alla fabbrica testi dei record: solo vista, id e nome dell'agente;
- non conosce chiavi degli agenti né la chiave della fabbrica; il token della fabbrica è cifrato, il bearer MCP
  non è salvato;
- non decide approvazioni e non cambia regole di Agate: le mostra e rimanda alla console;
- non fa entrare gli agenti nell'interfaccia, nelle API o nell'admin.

## Limiti

- Un solo collegamento e una sola azienda per istanza.
- Il bearer MCP è uno per installazione: l'identità dell'agente la dichiara Agate nella chiamata. Se arriva
  dall'argomento `agente` la sceglie chi chiama; tutti gli agenti hanno comunque gli stessi permessi.
- Lo stato dell'ingaggio è quello dell'ultimo battito (al più 15 minuti di ritardo); se la fabbrica non risponde
  resta valido l'ultimo stato noto.
- Gli eventi coprono le attività del kernel e i modelli con un campo `assegnatario` verso gli utenti; per
  un'attività del kernel l'agente riceve il record, non il testo dell'attività (che non può leggere via MCP).
- Le letture del registro si tengono 90 giorni; le scritture restano.
