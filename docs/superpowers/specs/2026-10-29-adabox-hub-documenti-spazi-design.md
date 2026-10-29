# adabox-hub — Documenti: spazi di lavoro, quote, versioni

Data: 2026-10-29
Stato: decisioni dell'utente (29/10): spazi condivisi e personali, ogni utente nelle regole aziendali; quota per
azienda che l'azienda suddivide tra i suoi utenti; 20 MB per file aumentabili per azienda; si lavora online.

## Obiettivo

Ogni utente ha uno o più spazi di lavoro con cartelle e sottocartelle dove carica e salva file, entro la quota
che l'azienda gli assegna; ci sono spazi condivisi tra persone scelte. Passo successivo (non qui): collegare uno
spazio al PC come unità di rete (WebDAV, richiede HTTPS e password per le applicazioni).

## Modello

- `Spazio`: azienda, nome, tipo (`personale` | `condiviso`), proprietario, descrizione, quota in MB (solo per i
  condivisi; 0 = nessun limite proprio), creato.
- `MembroSpazio` (solo condivisi): spazio, utente, ruolo (`lettura` | `scrittura` | `gestione`).
- `Cartella.spazio`: le cartelle senza spazio sono l'**archivio aziendale** di oggi, con i permessi per gruppi
  invariati. Le cartelle di uno spazio seguono le regole dello spazio.
- `QuotaUtente`: azienda, utente, MB per l'insieme dei suoi spazi personali; senza riga vale il default
  dell'azienda.
- `Versione`: documento, numero, file, dimensione, caricato da, quando. Caricare un file con lo stesso nome nella
  stessa cartella crea una nuova versione del documento (salvare = nuova versione), si tengono le ultime N.

## Regole

- **Chi vede**:
  - spazio personale: il proprietario; i responsabili dei documenti (`documenti.vedi_tutte_cartelle`) se
    l'impostazione aziendale «I responsabili vedono gli spazi personali» è attiva (default sì: regole aziendali);
  - spazio condiviso: i membri (lettura, scrittura, gestione) e i responsabili;
  - archivio aziendale: come oggi.
- **Quote** (MB, impostazioni per azienda):
  - totale dell'azienda (`quota_azienda_mb`, 0 = senza limite): somma di tutti i documenti, versioni e cestino;
  - per utente (`quota_utente_mb` di default, o `QuotaUtente`): i suoi spazi personali;
  - per spazio condiviso: la sua quota;
  - un caricamento si rifiuta se supera una qualunque delle quote che lo riguardano, con il messaggio di quale.
- **Dimensione massima di un file**: `file_max_mb` per azienda (default 20, il massimo lo fissa
  `DOCUMENTI_FILE_MAX_MB` del server); gli allegati dei record restano a `ALLEGATI_MAX_MB`.
- **Versioni**: `versioni_max` per azienda (default 10); le versioni contano nella quota; si ripristinano
  dall'anteprima (il ripristino diventa una versione nuova).

## Interfaccia

- Archivio: a sinistra le sezioni «I miei spazi», «Spazi condivisi», «Archivio aziendale», ciascuna con il suo
  albero; in testa allo spazio la barra d'uso («120 MB di 500 MB»); «Nuovo spazio» per chi può.
- Anteprima: versioni del documento con scarica e ripristina.
- Gestione: viste «Spazi» (membri e quota dei condivisi) e «Quote degli utenti»; impostazioni per azienda.

## Fuori scope

WebDAV / unità di rete, sincronizzazione offline, antivirus, storage a oggetti (S3).
