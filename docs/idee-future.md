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
