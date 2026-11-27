# Ricerca in Preferiti e Aree di lavoro (colonna di sinistra della chat)

Data: 2026-11-27 · Modifica piccola · Approvato dall'utente il 2026-11-27 («procedi con la tua proposta»).

## Perché

Nella colonna di sinistra della chat solo la Cronologia ha un campo di ricerca. Preferiti e Aree di lavoro non ne
hanno: con l'uso reale le liste crescono e scorrerle per ritrovare una voce diventa scomodo. Sulla demo oggi i numeri
sono piccoli (0–1 preferiti, 1–3 aree per utente): il bisogno è per i clienti veri.

## Obiettivi

- **Preferiti**: un campo «Cerca nei preferiti…» in cima al pannello filtra subito le voci di tutti i gruppi (Chat,
  Documenti, Grafici e tabelle, Condivisi con me) per titolo, area e azienda.
- **Aree di lavoro**: un campo «Cerca nelle aree…» filtra le aree per nome, comprese quelle delle altre aziende.
- I gruppi senza risultati si nascondono, quelli con risultati si aprono; i numeri accanto ai gruppi contano i
  risultati. Senza risultati compare «Nessun preferito trovato» / «Nessuna area trovata». Svuotato il campo tutto torna
  com'era, anche i gruppi che l'utente aveva chiuso.

## Non obiettivi

- Cercare dentro le aree (chat di altri membri, documenti, file, record collegati): scartato per ora, il contenuto delle
  proprie chat si trova già dalla Cronologia. Si può aggiungere dopo come ricerca sul server.
- Cercare nel testo dei messaggi dai Preferiti (lo fa la Cronologia).
- Ricordare il testo cercato tra una pagina e l'altra.

## Vincoli

- Niente script nella pagina (la Content-Security-Policy li segnalerebbe, e prima o poi si applicherà): il codice va
  in `addons/ai/static/ai/chat.js`.
- Accenti e maiuscole non contano, più parole devono esserci tutte: come la ricerca della pagina Applicazioni
  (`core/static/core/applicazioni.js`).
- Funziona uguale sul telefono (stesso pannello).

## Approcci

1. **Filtro nella pagina sui nomi** (scelto): voci e aree sono già tutte nella pagina, il filtro è immediato e non
   chiede nulla al server. Lavoro piccolo.
2. **Ricerca sul server dentro le aree**: trova anche chat condivise da altri membri, documenti, file e record
   collegati, risultati raggruppati per area. Più lavoro (vista, permessi, aziende); scartato per ora (vedi Non
   obiettivi).
3. Un'unica ricerca in cima a tutta la colonna per tutti i pannelli: cambierebbe anche la Cronologia, che funziona già;
   scartato.

## Come

- Ogni pannello filtrabile ha `data-filtra`; il campo `data-filtra-campo`; il messaggio senza risultati
  `data-filtra-vuoto hidden`; i gruppi (`<details>` dei Preferiti e delle aziende nelle Aree) `data-filtra-gruppo`.
- Ogni voce cercabile ha `data-cerca="<testo in cui cercare>"`: chat = titolo, area, azienda; documento = titolo,
  azienda; grafico/tabella = titolo; condiviso = titolo e nome di chi l'ha condiviso; area = nome.
- Le righe che non sono voci (la «Nuova chat» nelle aziende dove non c'è ancora un'area, la frase dell'elenco vuoto
  delle aree) hanno `data-filtra-nascondi`: mentre si cerca non si vedono.
- Il campo compare solo se c'è qualcosa da cercare: nei Preferiti almeno una voce, nelle Aree almeno due (l'area
  personale c'è sempre; scelta presa durante la costruzione).
- AI 1.62.0 (il manifest che cambia fa ricaricare l'istanza); nota in `docs/note-di-rilascio.md`.

## Prove

- Test in `addons/ai/tests/`: il markup (campi, gruppi, `data-cerca` con i testi giusti, campo assente senza voci) e i
  pezzi chiave dello script, come `core/tests/test_cerca_applicazioni.py`.
- Comportamento dello script provato con jsdom fuori dal repository (la CI non ha un DOM), come per gli altri script.

## Lasciato a chi costruisce

Testi esatti dei messaggi, stile del campo (quello della Cronologia), dettagli del codice.
