# Note di rilascio

Ciò che chi aggiorna un'istanza deve sapere: cambi di comportamento, azioni da fare, migrazioni. Il dettaglio è nei
commit; qui solo ciò che si vede o che chiede un intervento.

## 2026-11-12

**Da sapere prima di aggiornare**

- **Kernel 1.2.0.** I moduli possono dichiarare indirizzi alla radice dell'istanza (`urlpatterns_radice`), per i
  percorsi fissati da uno standard. Serve al nuovo modulo «Chat AI esterne», che sulle istanze con il kernel 1.1 non si
  installa: va aggiornata prima l'immagine (`deploy/flotta.py aggiorna`). Gli altri moduli non cambiano.

**Novità**

- **Chat AI esterne 1.0.0 (`connettore_ai`)**: adabox come connettore dentro Claude, ChatGPT, Gemini e Le Chat
  (migrazione `connettore_ai.0001`). Ogni persona collega la chat che usa già e da lì legge ciò che in adabox può
  vedere, con il suo abbonamento: sola lettura, permessi di ogni momento, registro delle chiamate, mascheramento dei
  dati personali se l'azienda lo accende. Spento finché un'azienda non lo accende in Impostazioni; serve un'istanza
  pubblica in https con `SITO_URL` corretto. Alla radice dell'istanza compaiono `/mcp` e due indirizzi sotto
  `/.well-known/`: il proxy deve passarli all'app. Provato con client simulati, non ancora con i quattro veri.

## 2026-11-11

**Da sapere prima di aggiornare**

- **Documenti 1.2.0 — gli spazi personali diventano privati.** L'impostazione «I responsabili dei documenti vedono gli
  spazi personali» passa a spenta di default: gli spazi personali li vede solo il proprietario, anche nell'elenco dei
  documenti dei responsabili e nella ricerca dell'assistente. Le aziende che l'avevano esplicitamente accesa non
  cambiano. Chi vuole il comportamento di prima la riaccende in Impostazioni → Documenti. Corretto anche un difetto:
  prima l'elenco dei documenti mostrava ai responsabili gli spazi personali anche con l'impostazione spenta.
- **Posta e calendario — invio dal chatter.** Le caselle collegate prima di questa versione non hanno il permesso di
  inviare: gli utenti che vogliono rispondere ai clienti dalla propria casella devono ricollegarla (la pagina lo
  dice). Fino ad allora i messaggi partono dall'indirizzo di sistema, come prima.

**Novità**

- **Connettori 1.4.0 — Odoo**, contatti e opportunità, con «ogni utente con la sua chiave»: ognuno collega il suo
  account da «I miei account esterni» e in adabox vede solo ciò che Odoo mostra a lui (migrazione `connettori.0005`).
  Le aziende si agganciano per partita IVA, anche negli altri connettori. Provato su un Odoo 19 vero.
  Con «le modifiche fatte in adabox tornano lì» contatti e opportunità salvati in adabox si scrivono in Odoo con la
  chiave di chi li salva (migrazione `connettori.0006`).
  Con «anche il calendario» arrivano anche gli appuntamenti di Odoo, in sola lettura (migrazione `connettori.0007`).
  Con «anche gli ordini di vendita» arrivano gli ordini di Odoo con righe e prodotti, in sola lettura: consegne e
  fatture restano a Odoo (migrazione `connettori.0008`). Nuovo nel kernel `core.esterni`: i documenti gestiti da un
  altro sistema non si modificano e non generano fatture né consegne.
- **Discuss 1.13.0 e Portale 1.2.0 — assistente nel portale clienti.** Nello sportello del sito si attiva «risponde
  anche nel portale clienti»: i clienti autenticati trovano la sezione «Assistente», che risponde con la conoscenza
  dello sportello, la guida pubblicata e il riepilogo dei loro documenti (gli stessi della home del portale). Non ha
  strumenti né accesso al database; quando non sa propone una richiesta di assistenza. Le domande sono visibili allo
  staff in Discuss → Domande dal portale (migrazione `discuss.0015`). Spento finché non si attiva.
- **AI 1.34.0 — ricerca mirata.** Si può chiedere all'assistente di cercare solo nei propri documenti o solo nella
  cartella dell'area di lavoro; le pagine della wiki sono indicizzate per intero, divise per sezioni.
- **Wiki 1.1.0 — «Chiedi alla wiki»** e domande senza risposta per i responsabili (migrazione `wiki.0002`).
- **Discuss 1.12.0 — la wiki come fonte dell'assistente del sito**: nello sportello si scelgono gli spazi pubblici
  (migrazione `discuss.0014`). Nessun cambiamento finché non se ne sceglie uno.
- **Connettori 1.3.0 — Salesforce e Zoho CRM** sullo stesso motore di HubSpot (migrazione `connettori.0004`). Provati
  solo contro sistemi simulati: prima di venderli, una prova con un'organizzazione vera (docs/collegamenti-esterni.md).
- **Nuovo modulo Posta e calendario**: casella e calendario Google o Microsoft per utente, da installare dove serve.
