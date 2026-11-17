# Misure aziendali di Ada — piano di lavoro

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** le misure delle aree da demo (fatturato, scaduto, ordinato, sotto scorta, appuntamenti...) hanno una
definizione fissata nel codice, uguale per Ada, la dashboard, Analisi e le chat esterne. Ada le legge in 1-2 passi e
sotto la risposta mostra i numeri usati con il link ai record. In più: la chat che si allarga davvero.

**Architecture:** un registro nel kernel (`core/misure.py`) raccoglie le misure dichiarate dalle app con la chiave
`"misure"` del manifest. Una misura aggregata è fatta di componenti `{vista, misura, filtri, segno}` calcolate con
`core.viste.interroga.aggrega`, quindi con i permessi di chi chiede. Una misura calcolata è una funzione. Sopra il
registro: lo strumento `misura` di Ada, `misura_aziendale` in grafico, previsione e Analisi, il blocco nel prompt, la
provenienza, il connettore e la valutazione.

**Tech Stack:** Django, pytest, SVG lato server (`core/svg.py`), CSS e JS della chat (`addons/ai/static/ai/`).

**Spec:** `docs/superpowers/specs/2026-11-17-ada-misure-aziendali-design.md`

## Global Constraints

- I dati si leggono solo da `ModelView` con i permessi di chi chiede: `vista_per_nome`, `filtra`, `aggrega`. Mai
  `Modello.objects` diretto in una misura aggregata.
- Il prompt di sistema resta byte-stabile: il blocco delle misure dipende solo dai moduli installati, in ordine di nome.
- Multi-azienda: `aziende` (vedi `interroga.aziende_di`) passa in tutte le componenti.
- Testi per l'utente in italiano, importi in formato italiano (1.234,56 €).
- «Vendite» = fatturato (deciso dall'utente). Se l'utente parla di ordini, `vendite.ordinato`. La risposta dice quale.
- Il periodo detto in modo relativo («quest'anno») resta relativo nei grafici salvati. Una data esplicita («2026»)
  diventa `dal`/`al` fissi.
- Obiettivo di velocità sulle domande d'oro da demo con Claude Haiku 5.5: mediana ≤ 5 s, 90 % ≤ 12 s.
- Lo sviluppo è nel worktree `wt-misure`, ramo `misure-aziendali`. Mai cambiare ramo in `/opt/adabox-hub`.
- Test dal worktree: `cd <worktree> && /opt/adabox-hub/.venv/bin/python -m pytest <percorso> -q`. Ogni avvio costa
  circa 3 minuti. Per i giri ripetuti su un modulo si usa `--reuse-db` con un file di impostazioni fuori dal
  repository, come nella memoria «Test lenti, database riusabile». Il controllo finale si fa sempre senza
  `--reuse-db`.

## Review Focus

1. **Utente senza permesso sulla vista di una componente** (es. vede le fatture ma non le note di credito): la misura
   non deve dare un numero parziale spacciato per intero. Si rifiuta con un messaggio chiaro. Test nel Task 1.
2. **Periodo che contiene oggi con `confronta=anno_prima`**: va confrontato lo stesso tratto (1/1-17/11 con
   1/1-17/11), non l'anno intero. Test nel Task 1.
3. **Misura senza dati nel periodo** (nessuna fattura a novembre): valore 0 e gruppi vuoti, mai un errore né `None`.
   Test nel Task 2.
4. **Nota di credito senza fatture nello stesso gruppo** (cliente con solo una nota a novembre): il gruppo compare
   con valore negativo, non sparisce. Test nel Task 2.
5. **Modulo non installato** (es. magazzino assente): la misura non è nel prompt né nello schema dello strumento.
   Chiedere `magazzino.sotto_scorta` dà un errore leggibile. Test nel Task 5.

---

### Task 1: Il registro delle misure nel kernel

**Files:**
- Create: `core/misure.py`
- Modify: `core/registry/manifest.py` (chiave `"misure"` in `CHIAVI`, attributo `misure: str | None`, validazione come
  `"ai"`: modulo Python dell'app stessa)
- Test: `core/tests/test_misure.py`

**Interfaces:**
- Produces:
  - `Componente(vista: str, misura: str, filtri: dict = {}, segno: int = 1)` (dataclass)
  - `Misura(nome, etichetta, definizione, unita="€", sinonimi=(), raggruppamenti={}, periodo_su="", componenti=(),
    funzione=None, filtri_utente=None, periodo_predefinito="anno", app="")` (dataclass).
    `raggruppamenti`: `{"cliente": "cliente", "mese": "data:mese"}`, cioè nome semplice → `per` di `aggrega`.
    `funzione(request, **parametri) -> {"valore", "righe": [{"etichetta", "valore", "url"}], "url"}` per le misure
    calcolate. `filtri_utente(request) -> dict` si aggiunge ai filtri di ogni componente quando `di != "tutti"`.
  - `registra(misura) -> Misura`, `carica()` (importa i moduli `"misure"` dei manifest attivi, una volta per processo,
    come `ai/strumenti/app.py`), `tutte() -> list[Misura]` (moduli attivi, ordinate per nome),
    `per_nome(nome) -> Misura` (`ErroreInterrogazione` se non c'è).
  - `Periodo(dal: date, al: date, etichetta: str, relativo: bool)` e
    `risolvi_periodo(periodo="", dal=None, al=None, oggi=None) -> Periodo`.
    Nomi ammessi: `oggi, ieri, domani, settimana, settimana_scorsa, settimana_prossima, mese, mese_scorso, trimestre,
    trimestre_scorso, anno, anno_scorso, ultimi_12_mesi`. Sono intervalli di calendario interi.
  - `calcola(nome, request, periodo="", dal=None, al=None, per="", primi=None, confronta="", aziende=None, di="") -> dict`
    con le chiavi `nome, etichetta, definizione, unita, valore, periodo ({dal, al, etichetta} o None), gruppi
    ([{gruppo, valore, url}]), confronto ({valore, delta_percento, periodo} o None), url`.
  - `serie(spec, request) -> {"serie": [(etichetta, valore)], "chiavi": [...], "totale", "misura", "per"}` (stessa
    forma di `interroga.calcola`), `kpi(spec, request, storia=12)` (stessa forma di `interroga.kpi`),
    `storia(nome, request, per, aziende=None) -> {date_inizio_periodo: float}` per le previsioni. `spec` usa le chiavi
    `misura_aziendale, per, periodo | dal+al, primi, di, aziende`.
  - `testo_prompt() -> str`: una riga per misura, `nome — Etichetta: definizione. Sinonimi: ... Per: cliente, mese`.

- [ ] **Step 1: Write the failing tests** in `core/tests/test_misure.py`. Usa una misura di prova registrata nel test
  sulla vista `core.lavoro` (`Lavoro`, data `creato`, come in `addons/ai/tests/test_specialisti.py`), con due
  componenti di segno opposto filtrate su `funzione`:
  - `test_somma_componenti_con_segno`: 5 lavori `a.x` e 2 `b.y` nel mese; componenti `+count funzione=a.x` e
    `−count funzione=b.y` → `valore == 3`;
  - `test_periodo_anno_e_scorso`: `risolvi_periodo("anno", oggi=date(2026,11,17))` → `dal=date(2026,1,1)`,
    `al=date(2026,12,31)`, `relativo=True`; `risolvi_periodo(dal=date(2026,3,1), al=date(2026,6,30))` → `relativo=False`;
  - `test_confronto_anno_prima_stesso_tratto`: con `oggi` il 17/11/2026 e `periodo="anno"`, `confronto["periodo"]` va
    dal 1/1/2025 al 17/11/2025 e il periodo corrente si ferma al 17/11/2026;
  - `test_primi_ordina_per_valore`: `per="funzione"`, `primi=1` → un solo gruppo, il più grande;
  - `test_gruppo_solo_negativo_resta`: un gruppo presente solo nella componente negativa ha valore negativo;
  - `test_componente_senza_permesso_rifiuta`: utente che vede la vista della prima componente ma non della seconda →
    `ErroreInterrogazione` con il nome della misura nel messaggio;
  - `test_url_lista_filtrata`: `url` inizia con `vista.url("lista")` e contiene `f_creato_da=` e `f_creato_a=` (i
    parametri che capisce `core/viste/filtri.py`), i gruppi hanno `f_<campo>=<chiave>`;
  - `test_testo_prompt_stabile_e_ordinato`: due chiamate a `testo_prompt()` uguali; la riga della misura `a` precede
    quella della misura `b`;
  - `test_manifest_misure_valida`: `"misure": "altro.misure"` nel manifest di `prova` → `ManifestNonValido`.
- [ ] **Step 2: Run, expect FAIL** — `core/tests/test_misure.py`: `ModuleNotFoundError: core.misure`.
- [ ] **Step 3: Implement** `core/misure.py` e la chiave del manifest. Somma per gruppi: chiama `aggrega(...,
  con_chiavi=True)` per componente e somma `valore × segno` per `chiave`. Il filtro del periodo è
  `{periodo_su}__gte`/`__lte` sui `DateField`. Sui `DateTimeField` si usano datetime aware: inizio di `dal` con `__gte`
  e inizio del giorno dopo `al` con `__lt`. Il confronto «anno_prima»/«periodo_prima» sposta l'intervallo; se
  l'intervallo contiene oggi, sia il periodo corrente sia quello di confronto finiscono «a oggi». `delta_percento` è
  `None` se il confronto vale 0.
- [ ] **Step 4: Run, expect PASS** — stesso file.
- [ ] **Step 5: Commit** — `feat(core): registro delle misure aziendali`.

### Task 2: Le misure della Fatturazione e la sua dashboard

**Files:**
- Create: `addons/fatturazione/misure.py`
- Modify: `addons/fatturazione/__manifest__.py` (`"misure": "fatturazione.misure"`, versione minore +1),
  `addons/fatturazione/dashboard.py`
- Test: `addons/fatturazione/tests/test_misure.py`

**Interfaces:**
- Consumes: `core.misure.registra, Misura, Componente, calcola` (Task 1).
- Produces: le misure `fatturazione.fatturato`, `fatturazione.fatture_emesse`, `fatturazione.da_incassare`,
  `fatturazione.scaduto`, `fatturazione.incassato`.

Definizioni (viste `fatturazione.fatture`, `fatturazione.scadenze`, `fatturazione.incassi`):

| Misura | Componenti | `periodo_su` | Raggruppamenti | Sinonimi |
|---|---|---|---|---|
| fatturato | `+sum:imponibile` stato=emessa, tipo in `VENDITE` di `dashboard.py`; `−sum:imponibile` stato=emessa, tipo=TD04 | `data` | cliente, mese, trimestre (`data:mese`...), anno | vendite, ricavi, fatturato |
| fatture_emesse | `+count` stato=emessa, tipo≠TD04 (unità «») | `data` | cliente, mese | |
| da_incassare | `+sum:importo −sum:incassato` su scadenze pagata=False, fattura emessa (istantanea: `periodo_su=""`) | — | cliente (`fattura__cliente`) | crediti aperti |
| scaduto | come da_incassare + `data__lt` oggi. Il filtro su oggi lo mette `filtri_utente`, che riceve la request e gira a ogni calcolo | — | cliente | insoluti |
| incassato | `+sum:importo` incassi di tipo «incasso» | `data` | mese, cliente | incassi |

Se `aggrega` non accetta una misura «importo − incassato», si usano due componenti `+sum:importo` e `−sum:incassato`.

- [ ] **Step 1: Write the failing tests** in `addons/fatturazione/tests/test_misure.py`, con la `scena` e `_fattura`
  di `test_fatturazione.py`:
  - `test_fatturato_imponibile_meno_note_credito`: due fatture emesse da 1.000 e 500 di imponibile, una bozza da 300,
    una nota di credito emessa da 200 → `calcola("fatturazione.fatturato", req, periodo="anno")["valore"] == 1300`;
  - `test_fatturato_senza_dati_vale_zero`: nessuna fattura nel mese → `valore == 0`, `gruppi == []` con `per="cliente"`;
  - `test_cliente_con_sola_nota_credito`: gruppo `cliente` con valore −200;
  - `test_primi_5_clienti`: 7 clienti, `per="cliente", primi=5` → 5 gruppi in ordine decrescente (il caso della torta
    con 4 spicchi);
  - `test_dashboard_uguale_alla_misura`: il primo KPI di `dashboard.kpi(request)` contiene il valore di
    `fatturato`/`mese` formattato con `core.dashboard.numero`;
  - `test_dashboard_campo_nascosto_non_disponibile`: con un ruolo che nasconde `imponibile` (permessi per campo,
    PLT-03), il KPI del fatturato vale «non disponibile» e la pagina non dà errore;
  - `test_scaduto_solo_passate`: due scadenze aperte, una ieri e una domani → `scaduto` = solo la prima.
- [ ] **Step 2: Run, expect FAIL** — `per_nome` solleva perché la misura non esiste.
- [ ] **Step 3: Implement** `misure.py`. Poi `dashboard.py` usa `calcola` per fatturato del mese, da incassare e
  scaduto (in caso di `ErroreInterrogazione`: «non disponibile»), e il grafico dei 6 mesi usa
  `calcola(..., per="mese", dal=primo_di_6_mesi_fa, al=oggi)`. `_netto` sparisce.
- [ ] **Step 4: Run, expect PASS** — il file nuovo e `addons/fatturazione/tests/test_fatturazione.py`.
- [ ] **Step 5: Commit** — `feat(fatturazione): misure aziendali; la dashboard le usa`.

### Task 3: Vendite, acquisti, magazzino, calendario

**Files:**
- Create: `addons/vendite/misure.py`, `addons/acquisti/misure.py`, `addons/magazzino/misure.py`,
  `addons/calendario/misure.py`
- Modify: i quattro `__manifest__.py` (chiave `"misure"`, versione minore +1), `addons/magazzino/dashboard.py`
- Test: `test_misure.py` nella cartella `tests/` di ciascuna delle quattro app

**Interfaces:**
- Consumes: Task 1. `magazzino.pagine.situazione(request, solo_sotto_scorta=True)`.
- Produces:
  - `vendite.ordinato`: `+sum:imponibile` su `vendite.ordini` con stato=confermato; `periodo_su="data"`; per cliente,
    mese. Sinonimi: ordini, ordinato.
  - `vendite.preventivi_aperti` (unità «», `count`) e `vendite.valore_preventivi_aperti` (€, `sum:imponibile`): stato
    in (bozza, inviato), istantanee.
  - `acquisti.acquistato`: `+sum:imponibile` su `acquisti.ordini` con stato=confermato; `periodo_su="data"`; per
    fornitore, mese.
  - `magazzino.sotto_scorta`: calcolata. `valore` = numero di prodotti. `righe` = prodotto, mancante
    (`scorta_minima − previsto`), link al prodotto. `url` = lista giacenze con `?sotto_scorta=1`.
  - `calendario.appuntamenti`: `+count` su `calendario.eventi`; `periodo_su="inizio"`; per giorno (`inizio:giorno`),
    settimana. `filtri_utente(request)` → `{"pk__in": [id degli eventi visibili dove l'utente è organizzatore o
    partecipante]}`; con `di="tutti"` non si applica. Sinonimi: appuntamenti, riunioni, agenda. `periodo_predefinito`
    = `"oggi"`. (Cambia la spec: invece del segnaposto `"@utente"` si usa l'hook `filtri_utente`, perché
    «organizzatore OPPURE partecipante» non si esprime con un dizionario di filtri.)
- [ ] **Step 1: Write the failing tests**:
  - vendite `test_ordinato_solo_confermati`: un ordine confermato da 1.000, uno in bozza da 400 → 1000;
    `test_preventivi_aperti`: due bozze e un inviato → numero 3;
  - acquisti `test_acquistato_solo_confermati`;
  - magazzino `test_sotto_scorta_come_situazione`: il `valore` è uguale a `len(situazione(request, True)[1])`; la
    dashboard del magazzino mostra lo stesso numero;
  - calendario `test_appuntamenti_miei_e_tutti`: 3 eventi di oggi, l'utente organizza il primo, partecipa al secondo,
    non c'entra con il terzo (pubblico) → `di=""` dà 2, `di="tutti"` dà 3; `test_appuntamenti_domani`:
    `periodo="domani"` conta solo quelli di domani.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** le quattro `misure.py`. La dashboard del magazzino usa `calcola("magazzino.sotto_scorta")`.
- [ ] **Step 4: Run, expect PASS** — i quattro file nuovi e `addons/magazzino/tests/test_magazzino.py`.
- [ ] **Step 5: Commit** — `feat: misure aziendali di vendite, acquisti, magazzino e calendario`.

### Task 4: Ordinamento e primi N negli strumenti generici

**Files:**
- Modify: `addons/ai/strumenti/viste.py` (`aggrega_record` e il suo schema), `addons/ai/artifact.py` (`grafico`,
  `tabella`, `calcola`, schemi)
- Test: `addons/ai/tests/test_strumenti_viste.py`, `addons/ai/tests/test_artifact.py`

**Interfaces:**
- Produces:
  - `aggrega_record(contesto, vista, per="", misura="count", filtri=None, testo="", aziende=None, ordina="", primi=None)`
    con `ordina` in `("", "valore", "-valore")` e `primi` intero da 1 a 100;
  - `grafico(..., ordina="", primi=None, ...)`: con `primi`, le prime N per valore più «Altro» (le date restano in ordine
    di tempo). `primi` e `ordina` vanno nella spec, così Analisi e la pagina dell'artifact li rispettano;
  - `tabella(contesto, vista, testo="", filtri=None, ordina="", campi=None, limite=50, titolo="", per="", misura="count")`:
    con `per` la tabella ha colonne `[gruppo, misura]`, una riga per gruppo, ordinata per valore decrescente.
- [ ] **Step 1: Write the failing tests**:
  - `test_aggrega_primi_5_decrescente`: 7 clienti con fatturati diversi, `per="cliente", misura="sum:totale",
    ordina="-valore", primi=5` → 5 gruppi decrescenti e `totale` ancora sul totale di tutti;
  - `test_grafico_primi_con_altro`: `primi=5` su 7 categorie → 6 punti, l'ultimo «Altro»;
  - `test_tabella_raggruppata`: `per="cliente", misura="sum:totale"` → `colonne == ["cliente", <etichetta misura>]`;
  - `test_argomenti_del_12_novembre`: le tre chiamate fallite del turno 537 (`aggrega_record` con `ordina` e `limite`,
    `grafico` con `limite`, `tabella` con `per`) ora non danno «unexpected keyword». `limite` è accettato come
    sinonimo di `primi` in `aggrega_record` e `grafico`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** L'ordinamento si fa sui gruppi già calcolati da `aggrega`; il limite di 100 gruppi resta.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `fix(ai): ordinamento e primi N in aggrega_record, grafico e tabella`.

### Task 5: Lo strumento `misura` e `misura_aziendale` in grafici, previsioni e Analisi

**Files:**
- Create: `addons/ai/strumenti/misure.py` (registrato come gli altri moduli di `ai/strumenti/`)
- Modify: `addons/ai/artifact.py` (`grafico`, `calcola`), `addons/ai/strumenti/specialisti.py` (`previsione`),
  `addons/ai/specialisti.py` (`serie_storica`, `calcola_previsione`), `addons/grafici/ai.py` (`_specifica`,
  `salva_grafico`, schema), `addons/grafici/motore.py` (righe 84-88: ramo per `misura_aziendale`)
- Test: `addons/ai/tests/test_misure_ada.py`, `addons/grafici/tests/` (file esistente sui grafici salvati)

**Interfaces:**
- Consumes: `core.misure.calcola, serie, kpi, storia, tutte, carica` (Task 1). Le misure dei Task 2-3.
- Produces:
  - strumento `misura(contesto, nome, periodo="", dal="", al="", per="", primi=None, confronta="", di="", aziende=None)`:
    lettura, concorrente, `funzione_licenza` uguale a quella di `aggrega_record`. Lo schema ha `nome` come `enum` delle
    misure di `tutte()`, `periodo` come enum dei nomi del Task 1, `confronta` in (`periodo_prima`, `anno_prima`), `di`
    in (`miei`, `tutti`). Restituisce `calcola(...)` più
    `"nota": "Riporta il valore e, la prima volta, la definizione in mezza frase. I link ai record sono sotto la risposta."`;
  - `grafico(..., misura_aziendale="", periodo="", dal="", al="")`: con `misura_aziendale` non servono `vista`/`misura`/
    `filtri`, e `per` è un raggruppamento della misura (`cliente`, `mese`). Spec salvata:
    `{"tipo": "grafico", "grafico": tipo, "misura_aziendale": nome, "per", "periodo" | "dal"+"al", "primi"}`;
  - `previsione(..., misura_aziendale="")`: la storia viene da `core.misure.storia`;
  - `analisi_salva_grafico(..., misura_aziendale="")`: anche per i KPI (`core.misure.kpi`);
  - `artifact.calcola` e `grafici.motore` passano a `core.misure.serie`/`kpi` quando la spec ha `misura_aziendale`;
  - titolo predefinito: `«{etichetta} {periodo.etichetta}»` («Fatturato dell'anno in corso» se relativo,
    «Fatturato 2026» se `dal`/`al` coprono un anno intero).
- [ ] **Step 1: Write the failing tests** in `test_misure_ada.py` (dati come nel Task 2, `Contesto` come in
  `test_specialisti.py`):
  - `test_strumento_misura_fatturato`: `valore` uguale a `core.misure.calcola`, `definizione` presente;
  - `test_grafico_con_misura_aziendale_si_ricalcola`: crea il grafico con `periodo="anno"`, aggiunge una fattura,
    `artifact.ricalcola` → il totale cambia;
  - `test_periodo_relativo_resta_relativo`: spec con `periodo="anno"` → nessun `dal`/`al`; con `dal`/`al` → fissi;
  - `test_previsione_con_misura_aziendale`: la storia passata al servizio finto (fixture `servizi`) sottrae le note di
    credito;
  - `test_misura_non_installata`: `misura(nome="magazzino.sotto_scorta")` con il magazzino escluso dai moduli attivi →
    errore leggibile e misura assente dall'`enum` dello schema;
  - in grafici `test_grafico_salvato_con_misura`: un `Grafico` con spec `misura_aziendale` si calcola in
    `motore.dati_grafico` (o la funzione delle righe 84-88).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — più `addons/ai/tests/test_artifact.py`, `test_specialisti.py` e i test di grafici.
- [ ] **Step 5: Commit** — `feat(ai): strumento misura e misure aziendali in grafici, previsioni e Analisi`.

### Task 6: Prompt e segnaposto dei grafici

**Files:**
- Modify: `addons/ai/motore/prompt.py` (`sistema`), `addons/ai/markdown.py` (`rendi`)
- Test: `addons/ai/tests/test_motore.py`, test di `markdown` (file esistente con `rendi`)

**Interfaces:**
- Consumes: `core.misure.testo_prompt` (Task 1).
- Produces: in `sistema()`, dopo `SISTEMA` e prima delle istruzioni dell'assistente:

```
Misure aziendali (definizioni fisse dell'azienda):
<testo_prompt()>
- Per le domande su una di queste misure usa lo strumento misura (o grafico/previsione con misura_aziendale): senza elenco_viste né descrivi_vista, e senza ricostruirla con aggrega_record.
- «Vendite» è il fatturato; se l'utente parla di ordini usa vendite.ordinato. Di' quale misura hai usato.
- Periodo detto a parole («quest'anno», «il mese scorso») → periodo; anni o date precise («2026», «da marzo a giugno») → dal e al.
- Grafici e tabelle compaiono da soli sotto la risposta: non scrivere segnaposto come ![titolo](artifact:N).
```

  Il blocco compare solo se `tutte()` non è vuoto. `rendi` toglie le righe che contengono solo `![...](artifact:N)`
  e, in mezzo al testo, il solo segnaposto.
- [ ] **Step 1: Write the failing tests**: `test_prompt_con_misure_stabile` (due `sistema()` identici; contiene
  `fatturazione.fatturato`; ordine per nome); `test_prompt_senza_misure` (nessuna misura → nessun blocco);
  `test_rendi_toglie_segnaposto_artifact` (`"Ecco:\n\n![Top 5](artifact:44)\n\nTotale 3 €"` → nell'HTML non c'è
  `artifact:44`, c'è «Totale 3 €»).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — più `addons/ai/tests/test_ai.py` (controlla che i test sul prompt esistenti
  reggano).
- [ ] **Step 5: Commit** — `feat(ai): le misure nel prompt; via i segnaposto dei grafici`.

### Task 7: «Numeri usati» sotto la risposta

**Files:**
- Modify: `addons/ai/provenienza.py` (`calcola`), `addons/ai/templates/ai/_provenienza.html`,
  `addons/ai/static/ai/chat.css` (solo lo stile della card)
- Test: `addons/ai/tests/test_fiducia.py`

**Interfaces:**
- Consumes: i risultati dello strumento `misura` (Task 5) negli eventi del turno.
- Produces: in `provenienza.calcola` la chiave `"numeri": [{"etichetta", "valore", "unita", "periodo",
  "definizione", "url"}]` (al massimo 8, dai risultati non in errore di `misura`, nell'ordine delle chiamate). Nel
  template c'è un chip «N numeri usati» che si apre con una card nello stile di quelle esistenti: per ogni numero
  etichetta, valore formattato in italiano, periodo, definizione e link «Apri i record». Il chip compare anche quando
  `esito == "conversazione"`.
- [ ] **Step 1: Write the failing tests**: `test_provenienza_numeri_usati` (un turno con un evento `misura` riuscito
  e uno in errore → `numeri` ha un elemento con `url` della lista filtrata); `test_template_numeri_usati` (la chat
  mostra «1 numero usato» e il link).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — più `test_guardia.py` (la guardia sui numeri vede i valori della misura come fonti).
- [ ] **Step 5: Commit** — `feat(ai): sotto la risposta i numeri usati con definizione e link`.

### Task 8: Misure nel connettore verso le chat esterne

**Files:**
- Modify: `addons/connettore_ai/catalogo.py` (`TITOLI["misura"] = "Misure aziendali"`, `TOLTI["misura"] =
  ("aziende",)`), `addons/connettore_ai/__manifest__.py` (versione minore +1)
- Test: test del catalogo in `addons/connettore_ai/tests/`

- [ ] **Step 1: Write the failing test** `test_catalogo_ha_misura_senza_aziende`: nell'elenco MCP c'è `misura`, con
  `readOnlyHint` e senza la proprietà `aziende` nello schema.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS** — tutta la cartella di test del connettore.
- [ ] **Step 5: Commit** — `feat(connettore_ai): le misure aziendali anche nelle chat esterne`.

### Task 9: Valutazione: numeri esatti, passi e domande da demo

**Files:**
- Modify: `addons/ai/valutazione/__init__.py` (`controlla`, `valuta`), `addons/ai/management/commands/ai_eval.py`,
  `addons/ai/valutazione/domande.json`
- Test: test esistenti di `ai_eval`/valutazione in `addons/ai/tests/` (cercare `valuta(`)

**Interfaces:**
- Consumes: `core.misure.calcola`.
- Produces:
  - nella domanda `"misura": {"nome", "periodo"?, "dal"?, "al"?, "per"?, "primi"?, "di"?}`: `controlla` calcola il
    valore vero con la request dell'utente della valutazione e segnala `manca il valore <x>` se la risposta non contiene
    nessuna delle forme di `varianti(valore)`: intero arrotondato con i punti delle migliaia («579.831») e con due
    decimali («579.831,40»). Con `per` si controllano i valori dei gruppi;
  - `"passi_massimi": n`: problema `lenta: <passi> passi` se `turno.passi > n`;
  - `valuta` aggiunge `"passi"` a ogni risultato;
  - `ai_eval` stampa i passi e, in fondo, mediana e 90° percentile dei secondi. Nuova opzione `--modello <id_api>`: la
    catena di ogni profilo diventa quel solo modello, come fa `_modello_finto` per il finto;
  - circa 20 domande nuove, ognuna con `misura` (dove c'è un numero), `passi_massimi: 2` (3 per i grafici) e il suo
    `copione`: fatturato dell'anno; fatturato del mese con confronto sull'anno prima; vendite di quest'anno (deve usare
    `fatturazione.fatturato`); i 5 clienti che hanno fatturato di più, in torta (5 spicchi); grafico del fatturato per
    mese del 2026 (`dal`/`al`); previsione del fatturato a 3 mesi; quanto è scaduto; chi ci deve più soldi; incassato
    il mese scorso; fatture emesse questo mese; ordini confermati del mese; preventivi aperti e loro valore; fornitori
    da cui abbiamo comprato di più; prodotti sotto scorta; appuntamenti di domani; appuntamenti della settimana; uno
    sulla differenza tra fatturato e ordinato; uno fuori dalle misure (es. «quanti contatti di Cagliari») per
    controllare che non peggiori.
- [ ] **Step 1: Write the failing tests**: `test_controlla_misura_trova_valore` (risposta «579.831 €» con il valore
  579831.4 → nessun problema; «580.000 €» → problema); `test_controlla_passi_massimi`; `test_copioni_domande_demo`
  (`ai_eval --copioni` su tutto `domande.json` passa: lo fa già la CI, qui con le domande nuove).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat(ai): valutazione con numeri esatti, passi e domande da demo`.

### Task 10: La chat che si allarga

**Files:**
- Modify: `addons/ai/static/ai/chat.css` (righe 99-101 e 706), `addons/ai/static/ai/chat.js` (`applica`, righe
  752-760: classe `is-piena`), `core/svg.py` (`torta`), `addons/ai/__manifest__.py` (versione)
- Test: `core/tests/` (test di `svg.torta`, se esiste il file; altrimenti nuovo `core/tests/test_svg.py`)

**Interfaces:**
- Produces:
  - `.ai-msg:not(.ai-msg-utente) .ai-msg-corpo { flex: 1 1 auto; width: 100%; }`: la risposta occupa la colonna;
  - testo: la regola delle 82 battute diventa `.ai-chat.is-piena .ai-md > :is(p, ul, ol, blockquote, h1, h2, h3, h4) { max-width: 120ch; }`;
    in «Larga» il testo segue la colonna. `applica` mette `is-piena` sulla chat quando il valore è `piena`;
  - `.ai-artifact-grafico svg { max-height: 420px; }` (le proporzioni restano, come fa già l'SVG);
  - `svg.torta(dati, titolo="", larghezza=720, altezza=320)`: torta di diametro al massimo `altezza − 40`, a sinistra,
    legenda a destra con etichetta, valore e percentuale. Il disegno resta proporzionato a qualunque larghezza
    mostrata.
- [ ] **Step 1: Write the failing test** `test_torta_legenda_accanto`: in `svg.torta([("A", 3), ("B", 1)])` il raggio è
  ≤ 140 e il testo della legenda sta a destra del centro della torta (x delle etichette > cx + r).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** CSS, JS e `torta`.
- [ ] **Step 4: Run, expect PASS.** Verifica a mano con la skill `run`: chat con una risposta di testo, una con un
  grafico a barre, una con una torta e una con una tabella, a 760 px, in «Larga» e in «Piena» su 1920 px. Screenshot
  per l'utente. Atteso: risposta e grafici si allargano con la colonna, il testo si ferma a ~120 battute in «Piena»,
  la torta non supera i 420 px di altezza.
- [ ] **Step 5: Commit** — `fix(ai): testo e grafici seguono la larghezza della chat`.

### Task 11: Documentazione, versioni, prova vera

**Files:**
- Modify: `README.md` (sezione «Assistente AI»: misure aziendali, strumento `misura`, chiave `"misure"` del
  manifest in «Scrivere un'app», profilo consigliato per le demo: Haiku 5.5 come «Veloce»), `docs/note-di-rilascio.md`,
  `addons/ai/__manifest__.py`, `addons/grafici/__manifest__.py` (versioni minori +1 dove non già fatto)

- [ ] **Step 1:** README e note di rilascio, scritte per chi usa e per chi sviluppa le app.
- [ ] **Step 2: Suite intera senza `--reuse-db`**, divisa in 4 parti come `.github/workflows/ci.yml`. Atteso: tutto
  verde.
- [ ] **Step 3: Prova vera** sull'istanza di sviluppo, dopo il merge e `modulo aggiorna --tutti`:
  `docker exec adabox_hub_web python manage.py ai_eval --modello <id_api>` per Haiku 5.5, Mistral Medium 3.5 e GLM
  flash. Atteso: le domande da demo passano su tutti e tre con gli stessi numeri; con Haiku mediana ≤ 5 s e 90 % ≤ 12 s.
  Se un obiettivo manca, riportare i numeri all'utente senza nasconderli. Se la chiave di un modello non funziona, lo
  si salta e lo si dice.
- [ ] **Step 4: Commit** — `docs: misure aziendali di Ada`.
