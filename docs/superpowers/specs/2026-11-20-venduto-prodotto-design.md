# Venduto per prodotto e dati non calcolabili

Data: 2026-11-20 · Dimensione: piccola (proposta approvata dall'utente in chat: «1 e 2 insieme»)

## Perché

«Elenca i 10 prodotti più venduti»: Ada non poteva sommare le righe degli ordini per prodotto. Mistral ha letto gli
ordini uno per uno fino al limite di 12 passi e, al «continua», ha inventato una classifica.

## Cosa

1. Misure `vendite.venduto` (importo) e `vendite.quantita_venduta`, sulla vista in sola lettura
   `vendite.righe_vendute`: righe degli ordini confermati che contano nel totale (opzionali solo se scelte), per
   azienda dell'ordine. Raggruppamenti: prodotto, cliente, commerciale, mese, anno; periodo sulla data dell'ordine.
   Il totale coincide con l'ordinato (stesse righe dell'imponibile). Il clic apre quella lista filtrata.
2. Regola nel prompt di Ada: se un dato non si calcola con gli strumenti lo dice subito; classifiche e totali solo da
   strumenti che lavorano su tutti i record, mai da una parte letta a mano.

## Decisioni mie

- Misure separate dall'ordinato (stesso totale, raggruppamenti diversi): una misura ha una sola vista per componente.
- Vista filtrata nel `get_queryset` (confermati e righe valide) invece di filtri nella misura: così il link del clic
  mostra esattamente le righe sommate (i filtri con `__` non passano nei link).
- La vista è esclusa dall'indice della ricerca di Ada (`MODELLI_ESCLUSI`): il modello non ha l'azienda.
- Fuori: fatturato per prodotto dalle righe fattura (la misura si aggiunge allo stesso modo se servirà).
