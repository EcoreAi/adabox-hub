# adabox-hub — fase 3: le prime app

Data: 2026-10-27
Stato: approvato (l'utente ha chiesto di procedere senza conferme: le decisioni sono prese qui e motivate)
Precede: fase 1 (kernel) e fase 2 (servizi, viste, documenti), completate

## Scopo

Le prime app vere, sopra il kernel delle fasi 1 e 2: **contatti**, **calendario**, **crm**, **helpdesk**,
**progetti** e **timesheet**. Servono a due cose: dare al prodotto le funzioni che ogni cliente chiede per prime
(anagrafica, agenda, opportunità, assistenza, commesse e ore) e verificare che il kernel regga app reali, con
dipendenze tra loro, estensioni incrociate, regole di visibilità sui record ed email da clienti esterni.

Riferimento funzionale: Odoo 19 Community (Contatti, Calendario, CRM, Helpdesk/OCA, Progetti, Timesheet) e i moduli
di `/opt/adaerp` come requisiti. Si riproducono funzionalità e flussi, **non** codice, template o testi.

Metro di riuscita: ogni app sta in `addons/<slug>/`, usa solo attributi della `ModelView` e servizi del kernel
(niente viste generiche riscritte), si installa da `/moduli/` con le dipendenze, e un'installazione vergine di tutte
le app con i dati demo passa in un test end-to-end.

## Decisioni

1. **Contatti per azienda** (`AziendaMixin`). In Odoo i partner sono condivisi tra aziende; nelle PMI italiane con
   più società la separazione è la richiesta più frequente e il kernel filtra già per azienda. La condivisione si
   valuterà con un flag in una fase successiva.
2. **Una sola anagrafica** per aziende e persone (`tipo`), con la persona collegata alla sua azienda (`societa`), come
   in Odoo. Campi fiscali italiani (partita IVA con cifra di controllo, codice fiscale, codice SDI, PEC) validati.
3. **Le app dipendono da `contatti`** (`depends` nel manifest): crm, helpdesk, calendario e progetti collegano i loro
   record ai contatti. `timesheet` dipende da `progetti`.
4. **Visibilità sui record** (le "record rules" di Odoo) con permessi personalizzati del modello: chi non ha
   `progetti.vedi_tutti_progetti` vede solo i progetti di cui è responsabile o membro; chi non ha
   `timesheet.vedi_tutte_ore` vede solo le proprie ore; gli eventi privati del calendario li vedono solo
   organizzatore e partecipanti. Implementate in `get_queryset` della `ModelView`: valgono per lista, dettaglio,
   kanban, calendario, grafico, export e API.
5. **Clienti esterni nel chatter** (serve all'helpdesk): il kernel impara (a) a mandare i messaggi anche a indirizzi
   email che non sono utenti, se la vista li indica (`ModelView.destinatari_esterni(obj)`), (b) ad accettare in
   entrata le risposte da quegli indirizzi (messaggio senza utente, con `autore_email`), (c) a passare le email non
   abbinate a gestori registrati dalle app (`core.chatter.entrata.registra_gestore`): l'helpdesk ne crea un ticket.
6. **`todo` resta com'è**, app di riferimento del kernel. Spostarla sulle attività pianificate (ipotesi della fase 1)
   la renderebbe un doppione delle attività del kernel; resta l'esempio di app minima.
7. **Niente doppioni con il kernel**: le attività su lead, ticket e contatti sono le attività pianificate del kernel,
   i documenti sono gli allegati, le note sono il chatter.
8. **Dati demo autosufficienti per app**: le fixture `demo` di un'app non citano record demo di un'altra (si possono
   installare senza demo le dipendenze); gli utenti nelle demo restano vuoti.

## Le app

### contatti

- `Categoria` (nome, colore) globale; `Contatto(AziendaMixin, ProprietaMixin)`: `codice` (sequenza `C{numero:05d}`),
  `tipo` (azienda/persona), `nome`, `societa` (FK a un contatto di tipo azienda, per le persone), `ruolo`, `email`,
  `telefono`, `cellulare`, `sito`, `indirizzo`, `cap`, `citta`, `provincia`, `nazione` (default IT), `partita_iva`,
  `codice_fiscale`, `codice_sdi`, `pec`, `cliente`, `fornitore`, `categorie` (M2M), `responsabile` (utente), `note`,
  `attivo`.
- Validazione: partita IVA italiana (11 cifre e cifra di controllo), codice fiscale (16 caratteri, formato e carattere
  di controllo, o 11 cifre per le società), codice SDI (7 caratteri), unicità della partita IVA per azienda.
- Vista: lista, kanban per tipo, chatter con tracciamento, import/export (chiave `codice`), scheda PDF, filtri per
  tipo, cliente, fornitore, categoria. Nel dettaglio di un'azienda, la sezione "Persone" (punto di aggancio del
  kernel) con i contatti collegati.

### calendario

- `Evento(AziendaMixin)`: `titolo`, `inizio`, `fine`, `tutto_il_giorno`, `luogo`, `descrizione`, `organizzatore`,
  `partecipanti` (utenti), `contatti` (M2M contatti), `privato`, `promemoria` (minuti prima: nessuno, 15, 60, 1440),
  `promemoria_inviato`.
- Vista principale: calendario per `inizio`; lista e grafico. Validazione `fine >= inizio`.
- Invito per email ai partecipanti alla creazione (nel worker) con il file `.ics`; download `.ics` dal dettaglio;
  promemoria ogni 5 minuti (pianificazione del manifest).

### crm

- `FaseCrm` (nome, ordine, probabilità, vinta), `EtichettaCrm`, `MotivoPerdita` (dati iniziali);
  `Opportunita(AziendaMixin, ProprietaMixin)`: `titolo`, `contatto` (facoltativo), `nome_contatto`, `email`,
  `telefono` (per i lead senza contatto), `fase`, `stato` (aperta/vinta/persa), `valore_atteso`, `probabilita`,
  `chiusura_prevista`, `commerciale`, `priorita` (0-3), `etichette`, `motivo_perdita`, `note`.
- Kanban per fase (trascinamento = cambio fase; fase "vinta" → stato vinta e probabilità 100), totale del valore
  atteso, grafico per fase/commerciale/mese, calendario per chiusura prevista, bottoni "Vinta", "Persa",
  "Crea contatto" (dal lead), azione "Assegna a me". Parametro "probabilità dalla fase".

### helpdesk

- `Team` (nome, membri), `FaseTicket` (nome, ordine, chiusa), `Ticket(AziendaMixin, ProprietaMixin)`: `numero`
  (sequenza `TK/{anno}/{numero:05d}`), `oggetto`, `descrizione`, `contatto`, `email_cliente`, `team`, `assegnatario`,
  `fase`, `priorita` (bassa/media/alta/urgente), `scadenza_sla`, `chiuso_il`.
- SLA: ore per priorità dai parametri dell'app (urgente 4, alta 8, media 24, bassa 72), `scadenza_sla` alla creazione,
  pill "scaduto" in lista; pianificazione oraria che avvisa l'assegnatario dei ticket in scadenza.
- Email: una email nuova nella casella delle risposte, non abbinata a un record, apre un ticket (gestore del kernel);
  i messaggi del chatter arrivano anche al cliente (`email_cliente`) e le sue risposte tornano nel ticket.
- Kanban per fase, bottoni "Prendi in carico" e "Risolvi" (fase chiusa, `chiuso_il`).

### progetti

- `FaseCompito` (nome, ordine, chiusa) globale; `Progetto(AziendaMixin, ProprietaMixin)`: `codice`, `nome`, `cliente`
  (contatto), `responsabile`, `membri`, `inizio`, `fine`, `stato` (attivo/sospeso/chiuso), `descrizione`;
  `Compito(AziendaMixin, ProprietaMixin)`: `progetto`, `titolo`, `descrizione`, `fase`, `assegnatari`, `scadenza`,
  `priorita`, `ore_previste`, `padre` (sottocompiti).
- Visibilità (decisione 4); kanban dei compiti per fase, calendario per scadenza, grafico; nel dettaglio del progetto
  la sezione "Compiti" con avanzamento.

### timesheet

- `RigaOre(AziendaMixin)`: `data`, `utente`, `progetto`, `compito` (dello stesso progetto), `descrizione`, `ore`
  (0 < ore ≤ 24), `fatturabile`.
- Visibilità (decisione 4); lista con totali e raggruppamenti per progetto/utente/mese, grafico delle ore, export.
- Estende progetti senza toccarlo: sezioni "Ore" nel dettaglio di progetto e compito (ore registrate e, per il
  compito, rispetto alle previste) registrate da `timesheet` nel `ready()`.
- Pagina propria `/timesheet/settimana/`: griglia compiti × giorni della settimana dell'utente, per inserire le ore
  in un colpo solo (esempio di pagina scritta a mano dentro un'app).

## Modifiche al kernel

- `Messaggio.autore_email`; `ModelView.destinatari_esterni(obj)` (default `[]`) usato dalle notifiche e dalla posta
  in entrata; registro dei gestori delle email non abbinate.
- Nessun'altra modifica attesa: se un'app ne ha bisogno, si aggiunge al kernel con test e si annota nella sessione.

## Test

Per ogni app: modelli e validazioni, viste (permessi e visibilità), azioni e bottoni, servizi usati (sequenze,
chatter, email, pianificazioni), API. Un test end-to-end installa da zero tutte le app con i demo nell'ordine delle
dipendenze, verifica i dati e disinstalla. Suite verde su SQLite e Postgres.

## Fuori scope

Vendite, fatturazione e magazzino (fase 5); sincronizzazione con calendari esterni (CalDAV, Google, Outlook); portale
clienti per l'helpdesk; fatturazione delle ore; Gantt; condivisione dei contatti tra aziende.
