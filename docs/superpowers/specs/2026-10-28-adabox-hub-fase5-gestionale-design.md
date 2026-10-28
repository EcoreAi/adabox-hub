# adabox-hub — fase 5: il gestionale

Data: 2026-10-28
Stato: approvato (l'utente ha chiesto di procedere; decisioni prese qui e motivate)
Precede: fasi 1-4

## Scopo

Il ciclo commerciale completo di una PMI italiana, dall'articolo alla fattura elettronica:

**prodotti → preventivo → ordine di vendita → consegna (DDT, scarico di magazzino) → fattura → incasso**
e, sul lato fornitori, **ordine di acquisto → ricevimento (carico di magazzino)**.

Riferimento funzionale: Odoo 19 (Vendite, Magazzino, Acquisti, Fatturazione) e i moduli di `/opt/adaerp` come
requisiti; per la fattura elettronica le specifiche tecniche FatturaPA 1.2.x dell'Agenzia delle Entrate. Si
riproducono funzionalità e flussi, non codice né testi.

## Decisioni

1. **Ambito.** Prodotti, vendite, magazzino, acquisti, fatturazione con l'XML FatturaPA. **Fuori**: HR e note spese
   (non stanno nel ciclo ordine-fattura; fase successiva), invio e ricezione SDI (modulo `sdi` a parte, come da
   roadmap: qui si produce e si scarica l'XML), contabilità generale in partita doppia, multivaluta (solo EUR).
2. **Righe dei documenti nel kernel** (`ModelView.inlines`): preventivi, ordini, DDT, ricevimenti e fatture hanno
   righe; il kernel le rende modificabili nel form del documento (formset con "Aggiungi riga" e eliminazione) e in
   sola lettura nel dettaglio, con i totali forniti dalla vista. È l'equivalente dei campi one2many di Odoo.
3. **Dati demo in Python** (`demo(modulo)` nei hook, chiamato solo con `--demo`, dopo le fixture): i documenti demo
   citano clienti e prodotti; con le fixture servirebbero pk fissi di altre app. L'hook usa i record che ci sono e
   crea quelli che mancano.
4. **App e dipendenze**:
   - `fiscale`: aliquote IVA (con la natura N1-N7 per le operazioni senza imposta) e termini di pagamento (rate con
     giorni, fine mese) — dati di base comuni, nessuna interfaccia complessa;
   - `prodotti` (fiscale): prodotti e servizi, unità di misura, categorie, listini;
   - `vendite` (prodotti, contatti): preventivi e ordini di vendita;
   - `magazzino` (prodotti): magazzini, movimenti, giacenze, consegne (DDT) e ricevimenti;
   - `acquisti` (prodotti, contatti): ordini ai fornitori;
   - `fatturazione` (vendite, fiscale): fatture e note di credito, scadenze e incassi, XML FatturaPA, registro IVA.
5. **Collegamenti tra app con segnali**: `vendite` emette `ordine_confermato`, `acquisti` emette
   `ordine_acquisto_confermato`; `magazzino`, se installato, li ascolta e crea la consegna o il ricevimento. Così
   vendite e acquisti funzionano anche senza magazzino (servizi, professionisti), come in Odoo con i moduli ponte.
6. **Importi in `Decimal`**, arrotondati al centesimo con `ROUND_HALF_UP` per riga e per riepilogo IVA, come chiede
   la fattura elettronica; totali memorizzati sul documento e ricalcolati a ogni salvataggio delle righe.
7. **Giacenza calcolata dai movimenti** (somma con segno per prodotto e magazzino), senza una tabella di saldi: con
   l'indice su prodotto e magazzino basta per le dimensioni di una PMI e non può andare fuori quadro.
8. **Numerazioni** con le sequenze del kernel: preventivo `PV/{anno}/{numero:04d}` alla creazione, ordine
   `OV/{anno}/{numero:04d}` alla conferma, DDT `DDT/{anno}/{numero:04d}` alla spedizione, ordine d'acquisto
   `OA/{anno}/{numero:04d}`, fattura `{numero}/{anno}` **all'emissione** (mai in bozza: niente buchi), note di credito
   con la stessa sequenza (come d'uso).
9. **Fattura elettronica**: XML FPR12 (privati) con cedente dai dati fiscali dell'azienda (`DatiFiscali`, estensione
   uno-a-uno di `Azienda` registrata da `fatturazione`: regime fiscale, IBAN, REA), cessionario dal contatto (partita
   IVA o codice fiscale, codice SDI o PEC, "0000000" se mancano), righe, riepilogo per aliquota con natura ed
   esigibilità, pagamento con le scadenze. Nome file `IT<partita IVA>_<progressivo>.xml`. Validazione strutturale nei
   test (elementi obbligatori, totali); lo schema XSD ufficiale si aggiunge con il modulo `sdi`.
10. **Stampe**: preventivo/ordine, DDT, fattura con il layout di stampa del kernel; invio per email al cliente del
    PDF (allegato anche al chatter).

## Le app in breve

| App | Modelli | Funzioni principali |
|---|---|---|
| fiscale | AliquotaIva, TerminePagamento | `scadenze(termine, data, importo)` |
| prodotti | Categoria, UnitaMisura, Prodotto, Listino, PrezzoListino | `prezzo(prodotto, listino, quantità)` |
| vendite | OrdineVendita, RigaVendita | preventivo → invio → conferma → (consegna) → fattura |
| magazzino | Magazzino, Movimento, Consegna(+righe), Ricevimento(+righe) | giacenze, scorte minime, DDT, rettifiche |
| acquisti | OrdineAcquisto, RigaAcquisto | richiesta → conferma → (ricevimento) |
| fatturazione | DatiFiscali, Fattura, RigaFattura, Scadenza | emissione, incassi, note di credito, XML, registro IVA |

Ogni app: manifest con dipendenze, gruppi, dashboard, dati iniziali e demo, kanban o liste raggruppate, chatter,
import/export, stampe dove servono, test, collaudo.

## Fuori scope

HR, note spese, SDI (invio/ricezione/notifiche), contabilità in partita doppia, cespiti, multivaluta, varianti di
prodotto, lotti e numeri di serie, ubicazioni multilivello, produzione, POS, e-commerce.
