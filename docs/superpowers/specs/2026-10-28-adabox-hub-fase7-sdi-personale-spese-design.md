# adabox-hub — fase 7: SDI, personale, note spese

Data: 2026-10-28
Stato: approvato (l'utente ha chiesto di procedere; decisioni prese qui e motivate)
Precede: fasi 1-6

## Scopo

- **SDI**: le fatture elettroniche viaggiano davvero, in uscita e in entrata. Si valida l'XML con lo schema
  ufficiale, si invia, si ricevono e si leggono le notifiche dello SDI; si ricevono le fatture dei fornitori, si
  registrano e si pagano.
- **Il resto del gestionale**:
  - personale (dipendenti, reparti, assenze con approvazione e saldo ferie);
  - note spese (con approvazione e rimborso);
  - il collegamento vendite → magazzino anche nei dati demo.

Riferimenti: specifiche tecniche FatturaPA 1.2.2 e del Sistema di Interscambio (file, notifiche, PEC) e i moduli
HR ed Expenses di Odoo come requisiti funzionali. Non si copia codice né testi.

## Decisioni

1. **Tre app**:
   - `sdi` (dipende da `fatturazione`, che porta con sé `vendite`, `contatti` e `fiscale`);
   - `personale` (nessuna dipendenza);
   - `spese` (dipende da `personale`).
   Il collegamento vendite → magazzino nei dati demo si risolve nell'hook demo di `vendite`, che emette il
   segnale di conferma come la conferma vera.
2. **Validazione XSD**: lo schema FatturaPA 1.2.2 e lo schema xmldsig W3C stanno nel modulo
   (`sdi/schemi/`), con l'import reso locale. Si valida con `lxml` senza accesso alla rete. Ogni XML si valida
   prima dell'invio; un errore di schema blocca l'invio e lo mostra.
3. **Canali di trasmissione**, a scelta nelle impostazioni del modulo:
   - **manuale** (default): si scarica l'XML da caricare sul portale "Fatture e Corrispettivi" e si caricano qui i
     file di notifica ricevuti;
   - **PEC**: invio all'indirizzo PEC dello SDI con il server SMTP della PEC aziendale; le notifiche arrivano
     sulla casella PEC, letta via IMAP da un lavoro pianificato. Lo SDI comunica nella prima ricevuta l'indirizzo
     da usare per i successivi invii, e il modulo lo memorizza;
   - **prova**: simula lo SDI e risponde con una ricevuta di consegna. Serve per demo e test, non va usato in
     produzione.
   Il canale SDICoop (web service) richiede l'accreditamento e certificati: è fuori scope, ma l'interfaccia dei
   canali lo prevede.
4. **Trasmissione e notifiche**:
   - una `Trasmissione` per ogni invio di una fattura (file, canale, stato, identificativo SDI, errori);
   - una `NotificaSdi` per ogni file ricevuto: RC (consegna), NS (scarto), MC (mancata consegna), DT (decorrenza
     termini), NE (esito PA), AT (attestazione);
   - le notifiche si riconoscono dal nome del file `IT<piva>_<progressivo>_<TIPO>_<n>.xml` e dal contenuto.
     Lo stato della trasmissione e della fattura ne segue l'esito.
   - Dopo uno scarto la fattura si corregge con una nota di credito oppure, se il numero non è stato
     "consumato" (scarto), si reinvia con un nuovo progressivo di invio, come prevedono le specifiche.
5. **Fatture passive**:
   - arrivano dalla PEC (file della fattura + file di metadati) o si caricano a mano (XML o `.p7m` firmato:
     il contenuto si estrae con `openssl cms`, senza verificare la firma, che ha già verificato lo SDI);
   - l'azienda si riconosce dalla partita IVA del cessionario; il fornitore dalla partita IVA del cedente (se
     manca si crea il contatto fornitore);
   - i duplicati si scartano (stesso fornitore, numero e data);
   - si leggono righe, riepilogo IVA e scadenze; stato "da verificare" → "registrata"; pagamenti per scadenza;
   - registro IVA acquisti mensile/annuale con CSV; vista leggibile della fattura nel dettaglio; si conserva il
     file originale.
6. **Personale**:
   - `Reparto`; `Dipendente` (per azienda, collegabile a un utente, responsabile, contratto, ore settimanali,
     giorni di ferie e ore di permesso annui);
   - `TipoAssenza` (ferie, permesso, malattia, ...; a giorni o a ore; se scala dal saldo);
   - `Assenza` con flusso richiesta → approvata/rifiutata. Approva il responsabile del dipendente (il suo
     utente) o il gruppo "Personale / Responsabile". Il dipendente richiede per sé dalla pagina
     "Le mie assenze";
   - giorni lavorativi esclusi sabato, domenica e festività nazionali italiane (Pasqua compresa);
   - saldo ferie e permessi per anno sul dettaglio del dipendente; calendario delle assenze approvate.
7. **Note spese**:
   - `CategoriaSpesa` (limite per riga, ricevuta obbligatoria, rimborso chilometrico con tariffa al km);
   - `NotaSpese` del dipendente con righe (data, categoria, descrizione, importo o km, ricevuta allegata alla
     riga);
   - stati bozza → inviata → approvata/rifiutata → rimborsata. Approva il responsabile del dipendente o il gruppo
     responsabile; stampa PDF; totale da rimborsare in dashboard.
8. **Notifiche**: richieste di assenza e note spese inviate scrivono nel chatter, con il responsabile come
   follower. Se Discuss è installato, arrivano anche nella sua posta in arrivo. L'esito torna al dipendente allo
   stesso modo.

## Fuori scope

- SDICoop/SDIFTP (accreditamento), conservazione sostitutiva, firma digitale delle fatture in uscita (non
  obbligatoria tra privati).
- Paghe e cedolini, presenze con timbratura, valutazioni, recruiting.
- Carte aziendali e importazione degli estratti conto per le note spese; contabilizzazione in partita doppia.
