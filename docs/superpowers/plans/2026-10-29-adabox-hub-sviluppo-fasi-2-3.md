# adabox-hub — piano: progetti software (fase 2), qualità e GitHub (fase 3)

**Spec:** `docs/superpowers/specs/2026-10-29-adabox-hub-assistenza-software-design.md` (fasi 2 e 3).
**Regole:** test prima, test dei moduli toccati verdi a ogni task (SQLite), suite completa SQLite e Postgres e
collaudo dei moduli prima del deploy di ogni fase; un commit per task con push.

## Fase 2 — Progetti 1.1.0 (le novità servono a ogni progetto; nessun modulo nuovo)

### Task 1: tipi di lavoro, stima, completamento — fatto
- `TipoCompito` configurabile (Funzionalità, Bug, Miglioramento, Attività, con colore); `Compito.tipo`, `punti`
  (stima), `completato_il` (impostato quando il compito entra in una fase chiusa, tolto se riaperto, anche dal
  kanban).

### Task 2: milestone e dipendenze — fatto
- `Milestone` (progetto, scadenza, avanzamento); `Compito.milestone`.
- `Compito.bloccato_da` (molti-a-molti, non simmetrico): niente cicli né auto-blocchi; un compito con bloccanti
  aperti non si chiude (form, bottone «Completato», kanban: aggancio del kernel `kanban_vietato`).

### Task 3: sprint e rilasci — fatto
- `Sprint` (progetto, date, obiettivo, stato); scheda con punti e burndown in SVG; «Chiudi sprint» sposta i compiti
  aperti nello sprint pianificato successivo.
- `Rilascio` (progetto, versione, data prevista, stato); note di rilascio generate dai compiti completati per tipo;
  «Rilascia» pubblica e manda il segnale `rilascio_pubblicato`; l'assistenza avvisa i clienti dei ticket collegati.
- Sprint, milestone e rilascio devono essere del progetto del compito.

### Task 4: budget di ore — fatto
- `Progetto.budget_ore`; ore previste (compiti) e consumate (timesheet, se installato) con barra; nota nel chatter
  del progetto al superamento dell'80% e del 100%.

## Fase 3 — moduli `qualita` e `github`

### Task 5: modulo `qualita` — fatto
- `Ambiente` (progetto, tipo, url, rilascio installato); `CasoTest` (area, precondizioni, passi, risultato atteso,
  priorità); `Collaudo` (progetto, rilascio, ambiente) con `Esecuzione` per caso (esito, note, chi, quando).
- Pagina di esecuzione: esito per caso; da un caso fallito «Apri difetto» crea un compito di tipo Bug collegato.
- Scheda sul rilascio: esito dei collaudi.

### Task 6: modulo `github` — fatto
- `Repository` per progetto (owner/nome, segreto del webhook, token cifrato, chiusura al merge).
- Webhook firmato (HMAC SHA-256): push → commit sul compito citato (`ADA-123` nel messaggio); pull request →
  collegamento con stato (aperta, unita, chiusa), al merge il compito si chiude se richiesto; release pubblicata →
  rilascio con la stessa versione pubblicato.
- Bottone «Crea issue su GitHub» (con il token) come lavoro in background; scheda sul compito con riferimento,
  nome del ramo suggerito e collegamenti.

### Task 7: installazione, collaudo, README, prova dal vivo — fatto
