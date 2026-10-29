# adabox-hub — Assistenza clienti per software house

Data: 2026-10-29
Stato: decisioni dell'utente (29/10): i clienti hanno un accesso (portale); le loro applicazioni sono web, basta un
widget; l'instradamento è per progetto; ci sono contratti SLA; il codice sta su GitHub.

## Obiettivo

I clienti segnalano bug e richieste dalla loro applicazione (widget) o dal portale; il ticket nasce già sul
progetto giusto, con il team e il responsabile del progetto, con le scadenze del contratto SLA del cliente; un bug
diventa un compito di sviluppo e, quando il compito è chiuso, il cliente lo sa.

Fasi (questa spec copre la prima):
1. **Assistenza** (questa): modulo `assistenza`, portale clienti, widget, instradamento, contratti SLA, ticket ↔ compito.
2. Progetti software: tipi di lavoro, sprint e milestone, release, dipendenze, avanzamento sul budget.
3. Qualità e GitHub: casi e piani di test, difetti, ambienti; commit e pull request collegati ai compiti.

## Architettura

- Modulo nuovo **`assistenza`** (dipende da `helpdesk` e `progetti`): Helpdesk e Progetti restano generici e
  installabili da soli; il ponte tra i due e il portale stanno qui.
- Kernel: **utenti esterni** (`ProfiloUtente.esterno`) che vedono solo il portale (middleware: ogni altro indirizzo
  rimanda al portale), e le pagine per **impostare la password** da un link (inviti e password dimenticata).

## Modello (`assistenza`)

- `PoliticaSLA`: nome; ore di **prima risposta** e di **risoluzione** per priorità (urgente, alta, media, bassa);
  conteggio sulle ore lavorative (giorni e fascia oraria) o sulle 24 ore.
- `Contratto`: cliente (Contatto), politica, inizio, fine, attivo. Il contratto valido del cliente fissa le scadenze
  dei suoi ticket; senza contratto valgono le ore dell'helpdesk di oggi.
- `Supporto` (uno per progetto): team dell'helpdesk, responsabile (default: il responsabile del progetto), contratto
  (default: quello del cliente), chiave del widget, domini da cui il widget può segnalare, attivo.
- `DatiTicket` (uno per ticket): progetto, compito collegato, tipo (bug, richiesta, domanda), dati tecnici
  (pagina, browser, schermo, versione, errori), canale (widget, portale, email, interno), scadenza della prima
  risposta, prima risposta data il.

## Regole

- **Instradamento**: ticket con progetto → team del supporto del progetto; assegnatario = responsabile del supporto o,
  se non c'è, il membro del team con meno ticket aperti. Email senza progetto: se il cliente ha un solo progetto con
  supporto, quello; altrimenti il primo team come oggi. I membri del team seguono il ticket.
- **SLA**: alla creazione e al cambio di priorità si calcolano scadenza della prima risposta e scadenza di risoluzione
  (quella che l'helpdesk già segue: `scadenza_sla` e avvisi). La prima risposta è il primo messaggio pubblico di un
  utente interno.
- **Widget**: script da incollare nell'applicazione del cliente con la chiave del progetto; bottone «Segnala un
  problema», form (tipo, oggetto, descrizione, email, screenshot), dati tecnici raccolti da solo. Endpoint pubblico con
  controlli: dominio di origine ammesso (CORS), limite di frequenza per indirizzo, campo esca anti-bot, dimensioni.
  L'email del segnalante si collega al contatto del cliente (o a una persona nuova dell'azienda cliente).
- **Portale** (`/assistenza/portale/`): il cliente vede ticket e progetti della sua azienda, apre ticket, risponde,
  allega file; vede solo i messaggi pubblici (mai le note interne). Gli utenti esterni nascono dall'invito su un
  contatto (email con link per impostare la password).
- **Ticket ↔ compito**: «Crea compito di sviluppo» dal ticket (progetto, titolo, descrizione, priorità); quando il
  compito arriva in una fase chiusa il ticket riceve un messaggio pubblico per il cliente e va nella fase «risolto».

## Fuori scope (fasi successive)

Sprint, release, QA, GitHub; valutazione del cliente; base di conoscenza pubblica; chat dal vivo.
