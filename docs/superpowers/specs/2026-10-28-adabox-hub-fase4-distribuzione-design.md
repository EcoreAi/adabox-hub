# adabox-hub — fase 4: distribuzione dei moduli

Data: 2026-10-28
Stato: approvato (l'utente ha chiesto di procedere con la fase successiva; decisioni prese qui e motivate)
Precede: fasi 1-3 (kernel, servizi, prime app) e la dashboard/chat

## Scopo

Fino a oggi un modulo si installa copiandone la cartella in `addons/`. Per rivendere il prodotto a più clienti, con
app ufficiali e moduli custom in repository separati, serve un modo sicuro e verificabile di **consegnare** i moduli:

1. un **pacchetto** standard (zip) per ogni versione di un modulo, prodotto da un comando;
2. la **firma** del pacchetto da parte di ICHNOBYTE, verificata dall'istanza prima di installare;
3. il **caricamento** del pacchetto da `/moduli/` (e da riga di comando), con tutti i controlli;
4. un **catalogo** (indice firmato) dei moduli approvati, da cui l'istanza scarica e aggiorna;
5. il **collaudo**: per ogni modulo, installazione vergine con le dipendenze in un DB vuoto, prima di pubblicarlo.

## Decisioni

1. **Formato**: `<slug>-<versione>.zip` con dentro la cartella `<slug>/` e, alla radice, `adabox-modulo.json`
   (slug, versione, kernel minimo, data, SHA-256 di ogni file) e, se firmato, `adabox-modulo.sig` (firma della
   descrizione). Esclusi `__pycache__`, `*.pyc`, file nascosti; i test restano (servono al collaudo).
2. **Firma Ed25519** con la libreria `cryptography` (standard di fatto, chiavi corte, verifica veloce). La chiave
   privata resta a ICHNOBYTE (file fuori dal repository); le istanze si fidano delle chiavi pubbliche elencate in
   `MODULI_CHIAVI_FIDATE` (base64, separate da virgola).
3. **Firma obbligatoria in produzione**: `MODULI_FIRMA_OBBLIGATORIA` ha di default il contrario di `DEBUG`. In
   sviluppo si caricano anche pacchetti non firmati (con un avviso in pagina).
4. **Il caricamento non installa**: estrae il modulo in `addons/` dopo i controlli; installazione e aggiornamento
   restano i bottoni della pagina Moduli (stesso flusso con backup della fase 1). Così un caricamento non può
   modificare il database.
5. **Controlli del pacchetto** prima di scrivere su disco: dimensione massima (`MODULI_ZIP_MAX_MB`, 20), dimensione
   decompressa massima (100 MB) e numero di file (protezione da zip bomb), nessun percorso assoluto, `..` o link
   simbolico, una sola cartella radice uguale allo slug, manifest valido (validatore della fase 1), descrizione
   coerente con il manifest, hash di ogni file, firma.
6. **Sostituzione di una versione presente**: ammessa solo con versione maggiore (o uguale con conferma esplicita
   da CLI `--forza`); la cartella precedente si archivia in `backup/moduli/<slug>-<versione>.zip` e il modulo
   risulta "da aggiornare". Un modulo installato non si sovrascrive con una versione minore.
7. **Catalogo**: `indice.json` (elenco con slug, nome, riassunto, versione, dipendenze, URL, SHA-256 del pacchetto)
   più `indice.sig`, generati da `modulo indice <cartella>` dai pacchetti firmati. L'istanza lo legge da
   `MODULI_CATALOGO_URL` (http(s) o file), verifica la firma e mostra in `/moduli/` i moduli nuovi o più recenti con il
   bottone "Scarica": download, controllo dell'hash dell'indice, poi lo stesso caricamento del punto 5.
8. **Collaudo**: `modulo collauda <slug>...|--tutti` crea per ogni modulo una istanza temporanea (cartella addons con
   il modulo e le sue dipendenze, DB SQLite vuoto), migra, installa con `--demo`, esegue i test del modulo,
   disinstalla con `--elimina-dati`, e riporta OK/KO. Gira in un sottoprocesso per modulo, come gli end-to-end.

## Comandi

| Comando | Effetto |
|---|---|
| `modulo chiavi` | genera una coppia di chiavi Ed25519 (privata su file, pubblica stampata in base64) |
| `modulo impacchetta <slug> [--firma <chiave>] [--uscita dist/]` | crea lo zip (firmato se si passa la chiave) |
| `modulo carica <zip> [--forza]` | controlla ed estrae il pacchetto in `addons/` |
| `modulo indice <cartella> --firma <chiave> [--url-base <url>]` | crea `indice.json` e `indice.sig` dai pacchetti |
| `modulo collauda <slug>... \| --tutti` | installazione vergine e test di ogni modulo, in ordine di dipendenze |

## Interfaccia

`/moduli/` aggiunge una card "Carica un modulo" (zip) con l'esito dei controlli, e, se il catalogo è configurato,
la sezione "Catalogo" con i moduli scaricabili. Ogni modulo mostra se proviene da un pacchetto firmato (e da chi:
l'impronta della chiave) o da una cartella locale.

## Test

Pacchetto: contenuto, esclusioni, hash, firma. Caricamento: pacchetto valido, firma mancante con firma
obbligatoria, firma di una chiave non fidata, hash alterato, zip con `..`/percorso assoluto/link, zip bomb, cartella
radice sbagliata, slug riservato, versione minore, sostituzione con archivio della precedente. Catalogo: indice
firmato, firma alterata, download con hash sbagliato, moduli già aggiornati non mostrati. Collaudo: un modulo che
passa e uno che fallisce. Pagina: upload e catalogo con i permessi (solo superuser).

## Fuori scope

Pubblicazione del catalogo su un server ICHNOBYTE (qui basta una cartella o un URL statico), licenze e scadenze dei
moduli, aggiornamento automatico senza intervento, revoca delle chiavi (si toglie la chiave da `MODULI_CHIAVI_FIDATE`).
