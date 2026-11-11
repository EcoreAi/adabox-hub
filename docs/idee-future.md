# adabox-hub — possibili sviluppi futuri

Idee valutate ma non decise: non sono nel piano di lavoro. Prima di partire servono una spec e le decisioni indicate.

## Agenti AI assegnabili e marketplace di agenti (proposta del 2026-10-29)

**Idea.** Un agente AI fa parte del team: lo si assegna a un compito o a un ticket come una persona, lavora in
background e riporta l'esito nel chatter. Gli agenti si distribuiscono come pacchetti in un marketplace e un'azienda
li «assume» per dei compiti.

**Cosa c'è già (modulo `ai`).** Assistenti configurabili (istruzioni, strumenti ammessi, modello, gruppi, domande
d'oro), esperti per app, attività pianificate, proposte con conferma per le scritture, tetto di spesa per azienda,
mascheramento dei dati personali, lavori in background; pacchetti zip dei moduli (`modulo carica`) e collaudo.

**Cosa manca.**
1. Agente come assegnatario: un utente di sistema legato a un assistente, scelto tra gli assegnatari.
2. Esecuzione su evento: all'assegnazione l'agente parte come lavoro in background e scrive l'esito nel chatter.
3. Limiti per agente: permessi dai gruppi, budget proprio, scritture solo come proposta o in autonomia sotto una
   soglia, registro delle azioni.
4. Marketplace: pacchetto agente (manifest, istruzioni, strumenti richiesti, domande d'oro), installazione con i
   permessi richiesti in vista, prova e attivazione.

**Primi casi d'uso.** Primo livello dell'assistenza (classificazione e risposte dalla base di conoscenza), casi di
test scritti da un compito, note di rilascio, controllo degli SLA in scadenza.

**Decisioni aperte.** Agenti solo interni o anche di terzi (revisione e accesso ai dati dei clienti); modello di
prezzo (consumo, abbonamento o solo tetto di spesa); se gli agenti possono anche scrivere codice e aprire pull request
su GitHub.

**Primo passo consigliato.** Agente come assegnatario con esecuzione su evento, provato sui ticket dell'assistenza; il
marketplace dopo, sopra il sistema dei moduli.

## Altre idee in sospeso

- Ricerca dell'assistente limitata a una cartella o a uno spazio dei Documenti.
- OCR delle scansioni per l'indice della conoscenza.
- WebDAV per i Documenti (serve un dominio con HTTPS).
- pgvector per gli embedding quando il server passa a Postgres.

## adabox dentro Claude e ChatGPT (proposta del 2026-11-11)

**Idea.** I clienti usano gli abbonamenti Claude o ChatGPT che hanno già, con i dati di adabox: ogni istanza espone
un server MCP con OAuth che l'utente aggiunge come connettore personalizzato; la chat resta nella cronologia del
fornitore, adabox applica i permessi dell'utente e, se l'azienda vuole, maschera i dati personali. Collegate: la
chiave API personale dentro Ada e l'importazione delle chat esportate da ChatGPT e Claude.

**Escluso.** Usare dentro adabox l'abbonamento dell'utente (sessioni o token dell'abbonamento): vietato dai termini
dei fornitori.

**Progetto tecnico.** `docs/progetto-connettore-ai.md` (verificato sulle fonti del 2026-11-11): protocollo MCP in
doppia versione (2025-11-25 e 2026-07-28), OAuth 2.1 con CIMD e DCR, strumenti di Ada in sola lettura, scritture come
proposte confermate in adabox, stime e fasi.

**Decisioni aperte.** Libreria OAuth o server nostro (dopo uno spike); scritture solo come proposte o anche dirette;
mascheramento di default; quali clienti hanno piani che ammettono i connettori (ChatGPT da verificare).

**Primo passo consigliato.** Spike di 3–4 giorni: OAuth minimo e uno strumento di lettura collegati davvero a Claude
e a ChatGPT.
