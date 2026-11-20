# Filtri sul grafico

Data: 2026-11-20 · Dimensione: media · Scelte dell'utente: «procedi» sulla proposta (cliente e commerciale su fatturato
e ordinato per primi; stesso «Filtra» sui grafici degli elenchi).

## Cosa

Accanto ai pulsanti del periodo un pulsante **Filtra**: apre un pannello con i filtri possibili del grafico, ognuno con
i valori presenti nei dati (i più grandi per primi). La scelta compare come etichetta con la × per toglierla; il grafico
si ricalcola lì dov'è e i link ai record portano il filtro. Un valore per filtro.

## Quali filtri

- Misure aziendali: i raggruppamenti non per data (fatturato: cliente; ordinato: cliente e **commerciale**, che si
  aggiunge ai raggruppamenti di `vendite.ordinato`).
- Grafici su una vista: i filtri dell'elenco (`list_filter`) che non sono date e non sono il campo del raggruppamento.
- Non sulle previsioni, KPI e tabelle.

## Regole

- La scelta resta nella specifica (`scelti: {campo: {chiave, etichetta}}`), separata dai filtri di Ada: togliere un
  filtro non tocca quelli scritti da Ada. Solo il proprietario (come il periodo).
- Il link ai record porta il filtro; se l'elenco non sa applicarlo, niente link (regola dei grafici cliccabili).
- Il confronto con l'anno prima usa gli stessi filtri. Il filtro si vede accanto al titolo, anche per chi riceve il
  grafico condiviso.

## Fuori

Più valori per lo stesso filtro, filtri su date, ricerca testuale nel pannello, filtri nelle pagine «Apri in grande».
