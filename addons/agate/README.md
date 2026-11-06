# Agate — «Controllo AI»

Collega l'assistente AI di adabox-hub ad **Agate**, il livello di controllo per gli agenti AI.

- **Le modifiche dell'assistente passano dalle regole di Agate.** Quando un utente conferma una
  proposta dell'assistente (crea, modifica, elimina, bottone, azione...), prima di eseguirla adabox
  chiede ad Agate (`POST /v1/evaluate`, strumento `adabox.<nome>`). Agate risponde:
  - *consentita*: si esegue come sempre;
  - *da approvare*: la proposta resta in attesa con il link ad Agate, e si esegue da sola quando
    una persona dà l'ok (webhook firmato, oppure controllo ogni minuto);
  - *bloccata*: si chiude con il motivo delle regole;
  - *con un limite*: non si esegue, si chiede all'assistente di rifarla entro il limite.

  Tutto resta nel registro di Agate, con chi ha confermato.
- **I modelli possono passare dal proxy di Agate.** Un provider «Agate» compatibile OpenAI usa i
  nomi logici dei modelli scelti dall'azienda in Agate: le chiavi dei fornitori restano in Agate,
  i dati personali vengono mascherati lì, i costi si contano lì.

Modalità: **Spenta**; **In prova (registra soltanto)**: Agate valuta e registra, adabox esegue
comunque, per vedere cosa cambierebbe prima di accendere; **Attiva**: decide Agate, e se Agate non
risponde non si esegue nulla. (I valori salvati restano `spento`, `osservazione`, `attivo`.)

## L'area «Controllo AI»

Non è un'app della barra in alto (`"application": False`): la voce **Controllo AI** sta nel menu del
profilo (chiave `menu_profilo` del manifest), solo per chi ha `agate.change_collegamento` (gruppo
«Agate / Amministratore»). Tre schede:

- **Stato** (`/agate/`): la protezione in una frase — «Protezione attiva ✓», «In prova (registra
  soltanto)» o «Spenta» — con i conti di oggi dalle valutazioni (controllate, consentite, bloccate),
  quante aspettano l'ok (tutte) e un bottone principale: «Vedi le N in attesa», oppure «Configura il
  Controllo AI» se manca il collegamento.
- **Registro delle azioni AI** (`/agate/valutazioni/`, permesso `agate.view_valutazione`): una frase
  per azione («Mario Rossi ha chiesto all'assistente: «Elimina l'attività…» — in attesa dell'ok in
  Agate»), con l'esito come pillola, il motivo (in prova: cosa avrebbe scelto Agate), «Decidi in
  Agate» per quelle in attesa e i filtri per esito, periodo (oggi, 7 e 30 giorni) e persona.
- **Impostazioni** (`/agate/impostazioni/`): la prima volta tre passi — 1 indirizzo di Agate, console
  e chiave (il collegamento nasce spento) → 2 prova (legge i modelli; «Riprova» se non va) → 3 modalità
  (proposta: in prova). Poi il modulo completo: modalità con una frase ciascuna, indirizzi e chiave; in
  **Avanzate** segreto dei webhook, prefisso degli strumenti e l'esportazione degli strumenti; a parte
  «Usa Agate per i modelli» e «Prova il collegamento».

## Installazione

```bash
python manage.py modulo installa agate --si      # dipende da "ai"
```

Il punto di aggancio è `ai.proposte.registra_guardia`: il modulo registra la sua guardia all'avvio.
Senza collegamento, o con la protezione spenta, l'assistente funziona come prima.

## Collegare Agate con un codice (consigliato)

Una volta sola, all'installazione (§8 del contratto dei plugin, `agentlia-workforce/docs/plugin-api.md`):

1. Nella console di Agate, Collegamenti → «Collega un'applicazione con un codice», prefisso `awf`, con
   «Permetti ad Agentic Workforce di proporre contratti» acceso: Agate mostra un codice `agc_…` (7 giorni,
   una volta sola).
2. In adabox, **Controllo AI → Impostazioni**: si incollano l'indirizzo di Agate e il codice. adabox manda ad
   Agate il suo server MCP (con la chiave appena generata), gli strumenti dell'assistente e l'indirizzo del
   webhook; Agate li attiva e restituisce tre chiavi separate — `evaluate` (l'assistente), `decide` (le
   decisioni delle persone), `sync` (risincronizzare gli strumenti) — più il segreto del webhook e il codice
   per la fabbrica. Tutto si salva cifrato e la protezione diventa «Attiva».

Da lì nessuno deve più aprire Agate: gli strumenti si risincronizzano da soli quando cambia «cosa può fare» degli
agenti, e le decisioni si prendono in adabox.

## Agate incluso: l'azienda senza Agate (§8.6)

L'azienda che non ha Agate non incolla nessun codice: alla **prima assunzione** dal Negozio degli Agenti AI la
conferma (con la password) chiede alla fabbrica di aprire il suo Agate, ospitato da Agentlia (`POST
{forge}/api/agate/included`), e adabox si collega subito con il codice ricevuto, come al passo 2 qui sopra
(`applicazione.collega(..., incluso=True)`). Chi conferma è il titolare: riceve l'invito alla console per vedere il
registro quando vuole. Il collegamento ricorda che è incluso (`Collegamento.incluso`): Impostazioni e Stato dicono
«Agate incluso, aperto per voi da Agentlia — console: <link>». Ricollegarsi con un codice allo stesso Agate lo lascia
incluso. Errori, «Riprova» e il ritorno al codice quando la fabbrica non offre il servizio (503) sono descritti nel
README del modulo `awf` (Agate incluso).

## Le decisioni in adabox: «Da approvare»

**Controllo AI → Da approvare** (anche nel menu del profilo, con il numero quando ce ne sono): le richieste degli
agenti e le proposte dell'assistente che aspettano una persona, ognuna in una frase (per gli agenti: «Il
Qualificatore lead chiede di cambiare «Preventivo gestionale per 3 negozi»: fase → Qualificata», da `awf.frasi`), con **Approva / Rifiuta** e
un motivo facoltativo. Per le azioni irreversibili e per i contratti si riscrive la password. adabox decide con la
chiave `decide`, sempre a nome di chi clicca («Nome Cognome <email>»): Agate registra chi ha deciso e da dove
(`app:adabox-hub`) e tiene regole, tetti e scadenze. Se l'azienda ha acceso in Agate la doppia conferma per i
contratti sopra una soglia, la pagina dice che è partita un'email ai responsabili e il contratto parte quando
confermano.

## Collegare Agate a mano (alternativa)

1. In Agate: una chiave con gli scope `evaluate` e `llm` (pagina Chiavi della console) e, se si
   vogliono gli esiti subito, un webhook verso `https://<adabox>/agate/webhook/` con l'evento
   `approval.decided`.
2. In adabox, **Controllo AI → Impostazioni**: i tre passi (o il modulo completo).
3. Gli strumenti dell'assistente in Agate:

   ```bash
   python manage.py agate_strumenti --output strumenti.json             # qui
   manage.py agate_add_internal_tools <tenant> production strumenti.json   # in Agate (T127)
   ```

   Nascono disattivati: chi gestisce Agate li rivede, li attiva e scrive le regole (soglie,
   approvazioni). Gli strumenti `irreversible` (invii, emissioni, movimenti) in Agate chiedono
   sempre una persona, salvo una regola esplicita.
4. Facoltativo, **Usa Agate per i modelli**: crea il provider e i modelli; poi nei Profili
   dell'assistente si mette «Agate» nella catena dei compiti.

## Cosa non fa

- Non decide approvazioni: si decidono in Agate.
- Non manda ad Agate le letture dell'assistente (non cambiano nulla).
- Non manda chiavi o password: gli argomenti delle proposte sono quelli che l'assistente ha
  preparato; Agate maschera i dati personali prima di salvarli e di mostrarli a chi approva.

## Limiti

- Gli strumenti registrati in Agate vanno riesportati quando cambiano (aggiornamenti dei moduli):
  in Agate una definizione cambiata torna disattivata.
- Una proposta in attesa scade in adabox dopo un giorno (regola dell'assistente): se l'approvazione
  in Agate arriva dopo, la proposta non si esegue e va rifatta.
- Il provider «Agate» non usa le funzioni proprie di Claude (ragionamento, cache del prefisso):
  passa dal formato OpenAI del proxy.
