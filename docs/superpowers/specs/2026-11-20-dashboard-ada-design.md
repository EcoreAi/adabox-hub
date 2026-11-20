# Dashboard fatte da Ada

Data: 2026-11-20 · Dimensione: piccola (design breve, approvato dall'utente in chat)

## Perché

Terzo pezzo dei grafici interattivi per le demo di Ada. È il momento di maggiore effetto: con una frase («fammi una
dashboard delle vendite») Ada prepara una pagina intera di indicatori e grafici veri, già cliccabili e con periodo
e filtri. Oggi Ada salva un grafico alla volta: per sei pezzi servono sette conferme e sette giri del modello.

## Approcci

- **A. Ada sceglie liberamente** tra misure e liste: copre anche le richieste insolite, ma il risultato dipende dal modello.
- **B. Composizioni fisse** per area: sempre belle e uguali, niente fuori da quelle.
- **C. Ada sceglie, con le composizioni come traccia** nelle istruzioni: le richieste tipiche escono come in B, quelle
  insolite restano possibili.

**Scelto C** dall'utente il 2026-11-20.

## Cosa

- Strumento nuovo **`analisi_crea_dashboard`** (`addons/grafici/ai.py`): titolo e da 2 a 8 pezzi; ogni pezzo è un
  indicatore, un grafico o una previsione su una misura aziendale o su una vista, con gli stessi parametri di
  `analisi_salva_grafico` (senza `pagina` e `artifact`). Crea sempre una pagina nuova; se esiste già una pagina
  dell'utente con quel titolo, errore che chiede un titolo diverso. Per aggiungere a una pagina esistente resta
  `analisi_salva_grafico`.
- **Una sola conferma**: l'anteprima calcola ogni pezzo ed elenca titolo, tipo e query di ciascuno.
  - Un grafico senza dati o in errore viene tolto, e l'anteprima lo dice («tolto: … — nessun dato» / il motivo).
  - Un indicatore a zero resta («scaduto: 0 €» è una notizia).
  - Se restano meno di 2 pezzi: errore, niente dashboard.
- **Disposizione**: prima gli indicatori (larghezza 1), poi grafici e previsioni (larghezza 2), nell'ordine dato da Ada.
- I grafici su una misura con una data partono da **Anno** (`periodo: "anno"`) se Ada non indica un periodo;
  si cambia con i pulsanti del periodo.
- **Composizioni come traccia** (Panoramica dell'azienda, Vendite, Fatturazione e incassi, Acquisti e scorte: il
  magazzino ha una sola misura e sta con gli acquisti), scritte come dati nel modulo, mostrate
  ad Ada solo con le misure installate.
- **Dopo la conferma** l'esito porta il link della pagina; Ada risponde con «Apri la dashboard» (stessa scheda).

## Da evitare

- Un pezzo vuoto o sbagliato nella dashboard di una demo: si scarta prima della conferma, non dopo.
- Numeri del modello: tutti i valori li calcola il database, come per gli altri grafici salvati.

## Fuori

Ada che modifica o riordina una dashboard esistente; dashboard nelle aree di lavoro; anteprima dei grafici in chat;
condivisione automatica della pagina.

## Lasciato a chi costruisce

Dove mettere le composizioni (descrizione dello strumento o prompt) purché filtrate sulle misure installate; quanto
riusare di `_specifica`/`_controlla`; i messaggi d'errore; versione di Analisi (minore, nessuna migrazione).
