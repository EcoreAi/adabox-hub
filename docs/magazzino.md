# Magazzino: costi, ubicazioni, lotti e seriali

## Costo e valore di magazzino

Ogni movimento ha un **costo unitario** e un **valore**:

| Movimento | Costo |
|---|---|
| Ricevimento da un ordine d'acquisto | prezzo della riga dell'ordine, al netto dello sconto |
| Ricevimento con il costo scritto sulla riga | quel costo |
| Rettifica in carico con un costo | quel costo |
| Rettifica senza costo, reso senza ordine | il costo attuale del prodotto |
| Uscite (consegne, rettifiche in scarico) | il costo calcolato col metodo del prodotto |
| Trasferimenti tra magazzini o ubicazioni | non cambiano il costo |

**Metodo di costo** (Magazzino → Impostazioni, per azienda; si può cambiare sul singolo prodotto):

- **Costo medio ponderato** (predefinito): il costo medio si aggiorna a ogni carico;
- **FIFO**: escono prima le unità entrate prima, ognuna al suo costo;
- **Standard**: sempre il «costo» scritto sulla scheda del prodotto. Per rivalutare si cambia quel costo.

Il valore si calcola ripercorrendo i movimenti in ordine di data, quindi un movimento inserito con una data passata
corregge anche i costi delle uscite successive. La merce uscita in giacenza negativa si salda al costo del carico che
arriva dopo.

**Valore di magazzino**: l'inventario valorizzato a qualsiasi data, con CSV. «Ricalcola i costi» riallinea i costi
salvati sui movimenti dopo un cambio di metodo. Lo stesso inventario, a fine periodo, entra nel pacchetto per il
commercialista. Nessuna scrittura contabile.

## Ubicazioni

**Magazzino → Ubicazioni**: zone, scaffali e celle, una dentro l'altra (es. `A` → `A-01` → `A-01-3`), per magazzino.

- I carichi senza ubicazione vanno nell'ubicazione **predefinita** del magazzino.
- Le uscite senza ubicazione partono da quella che ha più merce di quel prodotto.
- Sulle righe di ricevimenti e consegne si può scegliere «metti in» e «preleva da».
- **Trasferisci**: sposta merce tra magazzini o tra ubicazioni.
- **Per ubicazione**: la merce posto per posto; la scheda dell'ubicazione mostra cosa contiene.

La merce entrata prima delle ubicazioni compare come «senza ubicazione»: si sistema con «Sposta».

## Lotti e seriali

Sulla scheda del prodotto, riquadro *Costo di magazzino*: **tracciamento** nessuno, per lotto o per numero di serie, e
se ha la scadenza. Si attiva solo quando il prodotto non ha merce senza lotto (prima va azzerata con una rettifica).

Sulle righe di ricevimenti e consegne, campo **lotti o seriali**:

- un lotto: `L24A` (vale tutta la quantità);
- più lotti: `L24A:5, L24B:3` (la somma deve fare la quantità della riga);
- seriali: uno per riga, tanti quanti la quantità.

Regole:

- per i prodotti tracciati il ricevimento non si conferma senza lotti; i lotti nuovi si creano da soli, la scadenza si
  scrive poi nella scheda del lotto (Magazzino → Lotti e seriali);
- un seriale già in magazzino non si può ricevere di nuovo; uno che non c'è non si può spedire;
- in consegna, se la riga non dice i lotti, escono prima quelli **che scadono prima** (FEFO), saltando gli scaduti; un
  lotto scaduto esce solo se lo si scrive apposta; i seriali vanno sempre scritti;
- i trasferimenti di un prodotto tracciato chiedono il lotto.

La scheda del lotto mostra la **tracciabilità**: da quale fornitore è arrivato, a quali clienti è andato, dove si trova
e tutti i movimenti con il documento.
