# adabox-hub — piano di implementazione, fase 4: distribuzione dei moduli

**Spec:** `docs/superpowers/specs/2026-10-28-adabox-hub-fase4-distribuzione-design.md`.

**Regole per chi esegue:** come nei piani precedenti (test prima, suite verde con l'esito di pytest che decide il
commit, un commit per task con push). Dipendenza nuova: `cryptography` (versione da `pip freeze`).

### Task 1: Pacchetti e firme — fatto
- `core/registry/pacchetti.py`: `descrivi(cartella)`, `impacchetta(cartella, uscita, chiave=None)`, `genera_chiavi()`,
  `firma(dati, chiave)`, `verifica(dati, firma, chiavi_fidate)`, `impronta(chiave_pubblica)`.
- Comandi `modulo chiavi`, `modulo impacchetta`. Settings `MODULI_CHIAVI_FIDATE`, `MODULI_FIRMA_OBBLIGATORIA`,
  `MODULI_ZIP_MAX_MB`.
- Test: contenuto ed esclusioni, hash, firma valida/alterata/chiave non fidata.

### Task 2: Caricamento — fatto
- `pacchetti.controlla(zip)` (tutti i controlli della spec, decisione 5) e `pacchetti.installa_su_disco(zip, forza)`
  (decisione 6, archivio della versione precedente in `backup/moduli/`), provenienza registrata nella riga `Modulo`
  (`firmato_da`, `origine`).
- Comando `modulo carica`; card "Carica un modulo" in `/moduli/`.
- Test: tutti i casi della spec.

### Task 3: Catalogo — fatto
- `modulo indice`; `pacchetti.leggi_catalogo()` (URL http(s) o file, timeout, firma), `pacchetti.scarica(voce)`.
- Sezione "Catalogo" in `/moduli/` con "Scarica"; settings `MODULI_CATALOGO_URL`.
- Test: indice, firma alterata, hash sbagliato, filtri delle voci.

### Task 4: Collaudo, documentazione, verifica — fatto
- `modulo collauda` (sottoprocesso per modulo con dipendenze e test del modulo); test lento che collauda un modulo che
  passa e uno che fallisce; collaudo di tutte le app ufficiali.
- README: distribuzione dei moduli (chiavi, pacchetti, firma, caricamento, catalogo, collaudo). Suite SQLite e
  Postgres.
