# Modulo «Previsioni» — piano di lavoro

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** un modulo `previsioni` venduto in licenza che, anche senza l'assistente, prevede vendite e consumi di magazzino
(data di esaurimento e di riordino) con Timestral, e si usa dai moduli, da una sua pagina e dalla chat.

**Architecture:** il motore di previsione esce da `addons/ai/specialisti.py` ed entra in `addons/previsioni/motore.py`,
lavorando su una `request` (utente e azienda) invece che sul contesto di Ada. Sopra il motore: previsione per gruppo,
calcolo del magazzino, previsioni pronte di Vendite salvate ogni notte, pagina, vista «Articoli in esaurimento»,
riquadro nella scheda prodotto. Analisi e Ada chiamano lo stesso motore solo se il modulo è attivo e in licenza.

**Tech Stack:** Django 6.1 (CI) / 5.2 (container), pytest-django, kernel AdaBox (`core.registry.hooks`,
`core.viste.interroga`, `core.misure`, `core.regole`, `core.cifratura`, `core.licenza`), servizio HTTP Timestral.

**Spec:** `docs/superpowers/specs/2026-11-25-modulo-previsioni-design.md` (leggerlo prima di ogni task).

## Global Constraints

- Slug `previsioni`, `depends: []`, `application: True`, versione iniziale `1.0.0`; test in `addons/previsioni/tests/`,
  slug aggiunto a `ADDONS_FORCE` in `pytest.ini`.
- Il modulo funziona **senza** il modulo `ai`: nessun import di `ai` fuori da `previsioni/ai.py`.
- I numeri della previsione vengono solo dal servizio; la storia dal database con i permessi di chi guarda.
- Ogni previsione mostrata ha la fascia 10–90 % e l'affidabilità («alta», «media», «bassa» con i motivi).
- Quantili `[0.1, 0.5, 0.9]`; `MIN_PERIODI = 6`; `MAX_PERIODI = 120`; `MAX_ORIZZONTE = 24`; primi gruppi di default
  `10`; orizzonte delle previsioni pronte di Vendite `3` mesi; orizzonte del magazzino `12` mesi; serie del magazzino
  settimanale se la storia è sotto `12` mesi.
- Al servizio solo serie di numeri con id opachi (`"s1"`, `"s2"`…): mai nomi di prodotti, clienti o aziende.
- Richiesta al servizio: `POST {url}/v1/forecast`, corpo `{"series": [{"id", "values"}], "horizon", "quantiles"}`,
  intestazione `Authorization: Bearer <chiave>` solo se la chiave c'è; al massimo `512` serie per chiamata.
- Attribuzione accanto a ogni previsione: `modello <nome dal servizio> · licenza Modified MIT di Mistral AI`.
- Ogni dato salvato ha l'azienda (`AziendaMixin`); le viste dichiarano `company_field = "azienda"`.
- Nessuna compatibilità con le previsioni di oggi (decisione 6 della spec).
- Test mirati con `.venv/bin/pytest -q -p no:cacheprovider <file>`; la suite intera la fa la CI.
- Commit che finiscono con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Servizio giù o lento durante il lavoro notturno: restano le previsioni di prima con la loro data e un avviso «non
   aggiornata dal …» (test nel Task 8).
2. Articolo senza movimenti di uscita, o con consumo previsto zero: «nessun consumo previsto», nessuna data, nessun
   errore o divisione per zero (test nel Task 7).
3. Giacenza già sotto la soglia o già a zero: «riordina ora» e «finito» invece di date nel passato (test nel Task 7).
4. Azienda senza Magazzino o senza Vendite: la pagina mostra solo le sezioni delle app attive, senza errori (test nel
   Task 11).
5. Utente con regole di riga o campi nascosti sulle viste di origine: non vede le previsioni salvate per l'azienda
   intera, le vede calcolate con i suoi permessi (test nel Task 10).

---

### Task 1: Scheletro del modulo, impostazione e client del servizio

**Files:**
- Create: `addons/previsioni/__init__.py`, `__manifest__.py`, `apps.py`, `models.py`, `servizio.py`, `forms.py`,
  `views.py`, `urls.py`, `templates/previsioni/servizio.html`, `migrations/0001_iniziale.py`, `static/previsioni/icon.svg`
- Modify: `pytest.ini` (`ADDONS_FORCE`: aggiungere `previsioni`)
- Test: `addons/previsioni/tests/__init__.py`, `addons/previsioni/tests/test_servizio.py`

**Interfaces:**
- Produces: `servizio.url() -> str`, `servizio.chiave() -> str`, `servizio.attivo() -> bool`,
  `servizio.chiama(percorso: str, dati: dict) -> dict`, `servizio.ErrorePrevisione(Exception)`,
  `servizio.TIMEOUT = 120`, modello `ServizioPrevisioni` (`chiave_cifrata`, classmethod `corrente()`),
  URL `previsioni:servizio`.

- [ ] **Step 1: Generare lo scheletro** con `.venv/bin/python manage.py modulo nuovo previsioni --nome "Previsioni"`
  e adattare il manifest: `summary` «Previsioni di vendite e magazzino sui dati dell'azienda, con Timestral»,
  `category` «Direzione», `depends: []`, `application: True`, `settings: [{"chiave": "url_servizio", "label": "URL del
  servizio di previsione", "tipo": "testo", "default": "", "help": "es. http://adabox-forecast-1:8080 o un servizio
  remoto; vuoto = previsioni spente"}]`, gruppi `Previsioni / Utente` (lettura) e `Previsioni / Responsabile` (tutto).
- [ ] **Step 2: Scrivere i test che falliscono** in `test_servizio.py`:
  `test_senza_url_il_modulo_non_e_attivo` (url vuoto → `attivo()` False), `test_con_url_e_licenza_e_attivo`,
  `test_la_chiave_va_nell_intestazione_solo_se_c_e` (con `httpx`/urllib finto: intestazione `Authorization: Bearer abc`
  presente con chiave, assente senza), `test_servizio_giu_messaggio_chiaro` (connessione rifiutata →
  `ErrorePrevisione` con «Il servizio di previsione non risponde»), `test_la_pagina_del_servizio_solo_al_global_admin`
  (superuser 200, utente normale 403; la chiave salvata non compare mai nella pagina, si vede «impostata»).
- [ ] **Step 3: Eseguire** `.venv/bin/pytest -q -p no:cacheprovider addons/previsioni/tests/test_servizio.py` → FAIL.
- [ ] **Step 4: Implementare.** `ServizioPrevisioni(models.Model)` senza azienda (configurazione dell'istanza, una riga,
  nessuna ModelView), chiave cifrata con `core.cifratura.cifra/decifra`; form con «nuova chiave» e «togli la chiave»
  come `sharepoint/forms.py`; vista `servizio` solo superuser. `attivo()` = `"previsioni"` in
  `core.registry.modules.manifests_attivi()` e `core.licenza.ammesso("previsioni")` e `url()` non vuoto. `chiama`
  usa `urllib.request` come oggi `ai.specialisti.chiama` (rete interna ammessa: l'URL lo decide il Global Admin).
- [ ] **Step 5: Eseguire** i test → PASS; `makemigrations previsioni`; `modulo controlla previsioni` senza errori.
- [ ] **Step 6: Commit** `feat(previsioni): scheletro del modulo e client del servizio`.

### Task 2: Il motore esce dall'assistente

**Files:**
- Create: `addons/previsioni/motore.py`, `addons/previsioni/migrations/0002_url_da_ai.py`
- Modify: `addons/ai/specialisti.py` (resta solo il decisore: `url`, `chiama`, `decidi`), `addons/ai/artifact.py:85-87,117-120`,
  `addons/grafici/motore.py:49-62`
- Test: `addons/previsioni/tests/test_motore.py` (i test di previsione di `addons/ai/tests/test_specialisti.py`
  spostati qui e adattati); `addons/ai/tests/test_specialisti.py` tiene solo `test_classifica` e simili

**Interfaces:**
- Consumes: `servizio.chiama`, `servizio.ErrorePrevisione` (Task 1).
- Produces in `motore.py`: le costanti dei Global Constraints e `UNITA`; `inizio(d, per)`, `avanti(d, per, n=1)`,
  `etichetta(d, per)`, `periodi_completi(valori: dict, per) -> (list[tuple[date, float]], date)`,
  `vista_accessibile(request, nome: str)`, `serie_storica(vista, request, data, misura="count", per="mese",
  filtri=None, testo="", lista=None)`, `prevedi(storia, orizzonte) -> (list[tuple[float, float, float]], str)`,
  `prevedi_molte(storie: dict[str, list[tuple]], orizzonte) -> (dict[str, list[tuple]], str)`,
  `calcola_previsione(spec: dict, request) -> dict` (stesse chiavi di oggi: `storico`, `futuro`, `totale`, `modello`,
  `affidabilita`), `affidabilita(...)`, `totale(futuro)`, `svg_previsione(dati, titolo)`. Errori: `ErrorePrevisione`.

- [ ] **Step 1: Spostare i test** di previsione in `test_motore.py`, sostituendo `strumenti_specialisti.previsione(...)`
  con `motore.calcola_previsione(spec, request)` e il finto `specialisti.chiama` con il finto `servizio.chiama`;
  aggiungere `test_prevedi_molte_una_sola_chiamata_con_id_opachi` (3 storie → una chiamata, `id` `s1`,`s2`,`s3`, nessun
  nome nel corpo; risultato ricomposto per chiave originale) e `test_prevedi_molte_a_blocchi_oltre_512` (600 storie →
  2 chiamate).
- [ ] **Step 2: Eseguire** `.venv/bin/pytest -q -p no:cacheprovider addons/previsioni/tests/test_motore.py` → FAIL.
- [ ] **Step 3: Spostare il codice** da `ai/specialisti.py` a `previsioni/motore.py` senza cambiarne il comportamento,
  tranne: `calcola_previsione(spec, request)` prende la request; `vista_accessibile` cerca la vista in
  `core.viste.interroga.viste_accessibili(request)` per `id_vista`; gli errori diventano `ErrorePrevisione`.
  `prevedi` chiama `prevedi_molte({"serie": storia}, ...)`. In `ai/artifact.py` e `grafici/motore.py` importare da
  `previsioni.motore` dentro un `apps.is_installed("previsioni")` (vedi Task 3 per il controllo di licenza).
- [ ] **Step 4: Migrazione dati** `0002_url_da_ai`: se `ai.url_forecast` ha un valore globale e
  `previsioni.url_servizio` no, lo copia; reversibile senza azione. Test `test_l_url_dell_assistente_si_copia_una_volta`.
- [ ] **Step 5: Eseguire** `addons/previsioni/tests`, `addons/ai/tests/test_specialisti.py`,
  `addons/ai/tests/test_grafici_cliccabili.py`, `addons/grafici/tests` → PASS.
- [ ] **Step 6: Commit** `refactor(previsioni): il motore di previsione esce dall'assistente`.

### Task 3: Solo con il modulo in licenza

**Files:**
- Create: `addons/previsioni/ai.py`
- Modify: `addons/previsioni/__manifest__.py` (`"ai": "previsioni.ai"`), `addons/ai/strumenti/specialisti.py` (resta
  `classifica`), `addons/ai/__manifest__.py` (via `url_forecast`; funzione `specialisti` → label «Classificazioni»,
  help «con il decisore locale»), `addons/grafici/motore.py` (`previsioni_disponibili`, `_previsione`),
  `addons/grafici/costruttore.py:37-38`, `addons/ai/artifact.py`
- Test: `addons/previsioni/tests/test_licenza.py`

**Interfaces:**
- Consumes: `servizio.attivo()`, `motore.calcola_previsione` (Task 1-2).
- Produces: strumento di Ada `previsione` (stesso nome e schema di oggi) registrato da `previsioni/ai.py`;
  `grafici.motore.previsioni_disponibili()` = `apps.is_installed("previsioni") and previsioni.servizio.attivo()`;
  messaggio `SENZA_MODULO = "Serve il modulo Previsioni."` in `previsioni/servizio.py`.

- [ ] **Step 1: Test che falliscono:** `test_senza_licenza_niente_tipo_previsione_nel_costruttore`
  (`core.licenza.ammesso` finto False → «Previsione» non tra i tipi di `grafici.costruttore`),
  `test_senza_licenza_niente_strumento_previsione` (non tra `ai.strumenti.disponibili(...)`),
  `test_grafico_previsione_salvato_senza_modulo_mostra_il_messaggio` (card con «Serve il modulo Previsioni.»),
  `test_con_licenza_tutto_come_prima`.
- [ ] **Step 2: Eseguire** → FAIL.
- [ ] **Step 3: Implementare.** Lo strumento in `previsioni/ai.py` converte il contesto in request con
  `ai.strumenti.richiesta.per(contesto)` e `ErrorePrevisione` in `ErroreStrumento`; `disponibile=servizio.attivo`.
  In `grafici.motore._previsione` e `ai.artifact._calcola` senza modulo attivo: errore con `SENZA_MODULO`.
- [ ] **Step 4: Eseguire** il test e `addons/ai/tests/test_funzioni.py`, `test_misure_ada.py`,
  `addons/grafici/tests/test_fase3.py`, `test_statistiche.py` → PASS (aggiornare in quei test la presenza del modulo).
- [ ] **Step 5: Commit** `feat(previsioni): previsioni solo con il modulo in licenza`.

### Task 4: Previsione per gruppo

**Files:**
- Modify: `addons/previsioni/motore.py`, `core/misure.py:476` (`storia(..., scelti=None)` passato a `calcola`)
- Test: `addons/previsioni/tests/test_gruppi.py`

**Interfaces:**
- Consumes: `prevedi_molte`, `serie_storica`, `core.viste.interroga.aggrega`, `core.misure.calcola/storia`.
- Produces: `motore.calcola_per_gruppo(spec: dict, request) -> dict` con spec come `calcola_previsione` più
  `"raggruppa": str` (campo della vista o raggruppamento della misura, es. `"prodotto"`, `"cliente"`) e
  `"primi": int` (default 10). Ritorna `{"periodi": [etichette future], "gruppi": [{"chiave", "nome",
  "storico": [[etichetta, valore]], "futuro": [[etichetta, p10, p50, p90]], "totale": {...}, "affidabilita": {...}}],
  "modello": str, "esclusi": int}` in ordine di totale storico decrescente; `motore.come_tabella(dati) -> {"colonne",
  "righe"}` con colonne `Gruppo`, gli ultimi 3 periodi di storia, i periodi previsti (mediana), `Totale previsto
  (10–90 %)`, `Affidabilità`.

- [ ] **Step 1: Test che falliscono:** `test_primi_tre_prodotti_in_una_chiamata` (vista con righe di 5 prodotti,
  `primi=3` → 3 gruppi, una chiamata al servizio con 3 serie), `test_gruppo_con_poca_storia_resta_con_affidabilita_bassa`
  (una serie sotto `MIN_PERIODI` → `"esclusi": 1` e il gruppo non c'è), `test_misura_aziendale_per_prodotto`
  (`vendite.quantita_venduta` raggruppata per `prodotto`), `test_come_tabella_ha_fascia_e_affidabilita`.
- [ ] **Step 2: Eseguire** → FAIL.
- [ ] **Step 3: Implementare.** Primi gruppi: `aggrega(vista, request, per=raggruppa, ...)` (vista) o
  `misure.calcola(nome, request, per=raggruppa, primi=primi)` (misura); storia di ogni gruppo con il filtro del gruppo
  (`filtri={raggruppa: chiave}` o `misure.storia(..., scelti={raggruppa: chiave})`); tutte le storie in
  `prevedi_molte`; affidabilità per gruppo senza backtest (il backtest moltiplica le chiamate: solo storia e larghezza).
- [ ] **Step 4: Eseguire** il test e `core/tests/test_misure*.py` → PASS.
- [ ] **Step 5: Commit** `feat(previsioni): previsione per gruppo, una chiamata per tutti i gruppi`.

### Task 5: Ada prevede per gruppo

**Files:**
- Modify: `addons/previsioni/ai.py`, `addons/ai/artifact.py` (`_calcola`: spec con `"grafico": "previsione"` e
  `"raggruppa"` → `motore.come_tabella(motore.calcola_per_gruppo(...))`)
- Test: `addons/previsioni/tests/test_ai.py`

**Interfaces:**
- Consumes: `calcola_per_gruppo`, `come_tabella` (Task 4).
- Produces: lo strumento `previsione` accetta `raggruppa` (string) e `primi` (integer, 1–50, default 10); con
  `raggruppa` crea un artifact di tipo tabella (`Artifact.TABELLA`) con spec `{"tipo": "tabella", "grafico":
  "previsione", ..., "raggruppa", "primi"}` e restituisce ad Ada `{"artifact", "gruppi": [{"nome", "totale",
  "affidabilita"}], "modello", "nota"}`.

- [ ] **Step 1: Test che falliscono:** `test_ada_prevede_i_primi_prodotti_in_una_tabella` (artifact tabella con
  3 righe e le colonne di `come_tabella`), `test_senza_raggruppa_resta_il_grafico_di_prima`, `test_primi_fuori_limite`
  (`primi=80` → 50).
- [ ] **Step 2: Eseguire** → FAIL. **Step 3: Implementare.** **Step 4: Eseguire** il test e
  `addons/ai/tests/test_grafici_cliccabili.py` → PASS.
- [ ] **Step 5: Commit** `feat(previsioni): Ada prevede per prodotto, cliente o altro gruppo`.

### Task 6: Analisi prevede per gruppo

**Files:**
- Modify: `addons/grafici/costruttore.py` (campi «Raggruppa per» e «Primi» per il tipo Previsione),
  `addons/grafici/templates/grafici/costruttore.html`, `addons/grafici/motore.py` (`_previsione`: con `raggruppa`
  restituisce `{"tipo": "tabella", **come_tabella(...)}`)
- Test: `addons/previsioni/tests/test_analisi.py`

**Interfaces:**
- Consumes: Task 4. Produces: grafico salvato `Grafico.PREVISIONE` con spec `raggruppa`/`primi` mostrato come tabella
  nella card (`grafici/_widget.html`, ramo `w.serie.tipo == "tabella"`).

- [ ] **Step 1: Test che falliscono:** `test_costruttore_previsione_raggruppata_si_salva_e_si_vede_come_tabella`,
  `test_raggruppa_tra_i_campi_della_vista` (le scelte di «Raggruppa per» sono i campi raggruppabili della vista).
- [ ] **Step 2: Eseguire** → FAIL. **Step 3: Implementare.** **Step 4: Eseguire** il test e `addons/grafici/tests` →
  PASS.
- [ ] **Step 5: Commit** `feat(previsioni): previsione per gruppo nel costruttore di Analisi`.

### Task 7: Magazzino — consumo, soglie e proiezione

**Files:**
- Create: `addons/previsioni/magazzino.py`
- Test: `addons/previsioni/tests/test_magazzino.py`

**Interfaces:**
- Produces:
  - `Chiave = tuple[int, int | None]` (prodotto, magazzino; `None` = azienda intera).
  - `consumi(azienda, per: str) -> dict[Chiave, dict[date, float]]`: uscite per periodo (spec §4, «Consumo»):
    scarichi; rettifiche negative non collegate a un `Inventario` e senza causale «Inventario iniziale»; per le chiavi
    di un magazzino i trasferimenti in uscita; meno i carichi collegati allo stesso documento (`content_type`,
    `object_id`) di uno scarico (storni). Non contano: carichi dei ricevimenti, scarichi collegati a un documento con
    carichi (storni dei ricevimenti), rettifiche positive, rettifiche d'inventario, trasferimenti nelle chiavi
    `None`. Valori del periodo mai sotto zero.
  - `chiavi_e_soglie(azienda) -> dict[Chiave, tuple[Decimal | None, Decimal | None]]` (riordina sotto, riporta a):
    chiave per magazzino dove c'è `ScortaMagazzino`; altrimenti chiave `None` con `acquisti.RegolaRiordino` se
    Acquisti è installato, altrimenti `(Prodotto.scorta_minima or None, None)`.
  - `partenze(azienda) -> dict[Chiave, Decimal]`: giacenza + in arrivo − impegnato (`magazzino.models.giacenza`,
    `impegni_e_arrivi`), per magazzino e totale.
  - `per_della_storia(azienda) -> str`: `"mese"` se i movimenti coprono almeno 12 mesi, altrimenti `"settimana"`.
  - `proietta(partenza, futuro: list[tuple[float, float, float]], per, primo_periodo: date, riordina_sotto, riporta_a,
    oggi) -> dict` con `esaurimento`, `esaurimento_da`, `esaurimento_a`, `riordino`, `quantita_suggerita`, `stato`
    (`"ok" | "riordina_ora" | "finito" | "nessun_consumo" | "oltre"`).

- [ ] **Step 1: Test che falliscono** (numeri fissi, `oggi = 2026-11-25`, mese di 30 giorni per i conti):
  - `test_esaurimento_e_riordino_dalla_mediana`: partenza 120, mediana 30/mese da dicembre, riordina sotto 60 →
    riordino `2027-01-31` circa (giacenza 60 a fine gennaio), esaurimento `2027-03-31` circa;
    `esaurimento_da` con il 90 %, `esaurimento_a` con il 10 %.
  - `test_gia_sotto_soglia_riordina_ora` (partenza 40, soglia 60 → `stato == "riordina_ora"`, `riordino == oggi`).
  - `test_giacenza_zero_finito` (partenza 0 → `"finito"`).
  - `test_nessun_consumo` (mediane tutte 0 → `"nessun_consumo"`, nessuna data).
  - `test_oltre_l_orizzonte` (consumo minimo, 12 mesi non bastano → `"oltre"`).
  - `test_quantita_suggerita_fino_a_riporta_a` e `test_quantita_suggerita_tre_mesi_senza_riporta_a`.
  - `test_consumi_contano_prelievi_a_mano_non_inventari`, `test_storno_di_consegna_si_compensa`,
    `test_storno_di_ricevimento_non_e_consumo`, `test_trasferimenti_solo_per_magazzino`.
  - `test_soglie_magazzino_poi_acquisti_poi_scorta_minima`, `test_settimane_con_meno_di_un_anno`.
- [ ] **Step 2: Eseguire** → FAIL.
- [ ] **Step 3: Implementare** come funzioni pure dove possibile (`proietta` non tocca il database); il consumo di un
  periodo si distribuisce uniformemente sui suoi giorni; la data è il primo giorno in cui la giacenza proiettata è
  ≤ 0 (esaurimento) o < riordina sotto (riordino).
- [ ] **Step 4: Eseguire** il test → PASS.
- [ ] **Step 5: Commit** `feat(previsioni): consumo, soglie e proiezione del magazzino`.

### Task 8: Calcolo salvato, lavoro notturno e «Aggiorna»

**Files:**
- Modify: `addons/previsioni/models.py` (`PrevisioneArticolo`, `StatoCalcolo`), `__manifest__.py` (`cron`),
  `views.py`, `urls.py`; Create: `addons/previsioni/calcolo.py`, migrazione
- Test: `addons/previsioni/tests/test_calcolo.py`

**Interfaces:**
- Consumes: Task 2 (`prevedi_molte`, `affidabilita`), Task 7.
- Produces: `PrevisioneArticolo(AziendaMixin)` con `prodotto` (FK `prodotti.Prodotto`), `magazzino` (FK
  `magazzino.Magazzino`, null = azienda intera), `per`, `partenza`, `futuro` (JSON `[[etichetta, p10, p50, p90]]`),
  `consumo_mensile` (mediana media al mese), `esaurimento`, `esaurimento_da`, `esaurimento_a`, `riordino`,
  `quantita_suggerita`, `stato`, `affidabilita` (JSON), `modello`, `calcolata_il`; unico (azienda, prodotto, magazzino).
  `StatoCalcolo(AziendaMixin)`: `cosa` («magazzino», «vendite»), `ultimo_tentativo`, `ultimo_ok`, `errore`.
  `calcolo.magazzino(azienda) -> int` (righe salvate), `calcolo.notturno()` (tutte le aziende con il modulo attivo),
  vista POST `previsioni:aggiorna` (`?cosa=magazzino|vendite`, permesso `previsioni.change_previsionearticolo`).
  `calcolo.request_per(azienda) -> HttpRequest | None`: la request con cui si calcola di notte per l'intera azienda
  (`request.azienda = azienda`, utente = il primo superuser attivo); senza superuser `None`, nessun calcolo e
  `StatoCalcolo.errore` «nessun utente con cui calcolare».
  Manifest: `"cron": [{"nome": "Previsioni della notte", "funzione": "previsioni.calcolo.notturno", "ogni": "1d",
  "alle": "02:00"}]`. I modelli con FK a `magazzino` e `prodotti` stanno in un modulo che dipende da `[]`: dichiarare
  le FK con stringhe e creare le righe solo con `apps.is_installed("magazzino")`; la migrazione deve girare anche senza
  Magazzino (scelta del costruttore: modelli in un'app figlia, o dipendenza `magazzino` in `depends` della migrazione
  con `run_before` — scegliere quella che `modulo collauda` accetta).

- [ ] **Step 1: Test che falliscono:** `test_calcolo_salva_una_riga_per_chiave`, `test_request_per_senza_superuser`,
  `test_servizio_giu_restano_le_vecchie`
  (con righe del giorno prima e servizio giù → righe invariate, `StatoCalcolo.errore` pieno, `ultimo_ok` invariato),
  `test_notturno_salta_aziende_senza_modulo_o_magazzino`, `test_aggiorna_solo_con_permesso`,
  `test_articoli_senza_storia_sufficiente_non_hanno_riga`.
- [ ] **Step 2: Eseguire** → FAIL. **Step 3: Implementare** (serie a blocchi di 512 con `prevedi_molte`; la
  sostituzione delle righe dell'azienda in una transazione solo se il servizio ha risposto).
- [ ] **Step 4: Eseguire** il test → PASS; `modulo collauda previsioni` senza errori.
- [ ] **Step 5: Commit** `feat(previsioni): previsioni del magazzino salvate ogni notte`.

### Task 9: «Articoli in esaurimento» e riquadro nella scheda prodotto

**Files:**
- Modify: `addons/previsioni/views.py` (`ArticoliInEsaurimentoView(ModelView)`), `apps.py`
  (`hooks.sezione_dettaglio("prodotti.Prodotto", "previsioni/_prodotto.html", order=40,
  permission="previsioni.view_previsionearticolo")`), `__manifest__.py` (menu «Articoli in esaurimento»);
  Create: `templates/previsioni/_prodotto.html`, `templates/previsioni/_attribuzione.html`
- Test: `addons/previsioni/tests/test_esaurimenti.py`

**Interfaces:**
- Consumes: `PrevisioneArticolo`, `StatoCalcolo` (Task 8).
- Produces: vista `previsioni.esaurimenti` di sola lettura, `company_field = "azienda"`, `list_display` (prodotto,
  magazzino, partenza, consumo mensile, riordino, esaurimento, stato, affidabilità), ordinamento per `riordino`
  (nulli in fondo), filtri per magazzino e «entro N giorni» (7, 30, 90), `ai_descrizione` «Gli articoli di
  magazzino con la data prevista di esaurimento e di riordino, calcolate ogni notte dal modulo Previsioni».
  `_attribuzione.html` con `modello` → «modello {{ modello }} · licenza Modified MIT di Mistral AI».

- [ ] **Step 1: Test che falliscono:** `test_lista_ordinata_per_riordino_e_filtro_entro_30_giorni`,
  `test_un_azienda_non_vede_le_righe_di_un_altra`, `test_vista_in_sola_lettura` (niente nuovo, modifica, elimina),
  `test_riquadro_nella_scheda_prodotto_con_fascia_affidabilita_e_attribuzione` (testi «Finisce verso il», «tra il»,
  «Riordina entro il», «Affidabilità», «licenza Modified MIT di Mistral AI»), `test_riquadro_avviso_se_non_aggiornata`
  («non aggiornata dal» con `StatoCalcolo.errore`), `test_ada_vede_la_vista` (tra `viste_accessibili` con il modulo).
- [ ] **Step 2: Eseguire** → FAIL. **Step 3: Implementare.** **Step 4: Eseguire** → PASS.
- [ ] **Step 5: Commit** `feat(previsioni): articoli in esaurimento e previsione nella scheda prodotto`.

### Task 10: Previsioni pronte di Vendite

**Files:**
- Create: `addons/previsioni/pronte.py`; Modify: `models.py` (`PrevisionePronta`), `calcolo.py` (`vendite(azienda)`,
  nel `notturno`), migrazione
- Test: `addons/previsioni/tests/test_pronte.py`

**Interfaces:**
- Consumes: `calcola_previsione`, `calcola_per_gruppo` (Task 2, 4), `StatoCalcolo` (Task 8), `core.regole`.
- Produces:
  - `pronte.registra(chiave, titolo, app, permesso, spec: Callable[[azienda], dict], campi: tuple[str, ...])` e
    `pronte.per_request(request) -> list[dict]` (le pronte delle app visibili all'utente).
  - Registrate in v1: `vendite.fatturato_mese` (titolo «Fatturato previsto per mese» con spec
    `{"misura_aziendale": "fatturazione.fatturato", "per": "mese", "orizzonte": 3}` se Fatturazione è attivo,
    altrimenti «Ordinato previsto per mese» con `vendite.ordinato`), `vendite.prodotti` («Prodotti: quantità prevista,
    primi 10», `vendite.quantita_venduta` raggruppata per `prodotto`), `vendite.clienti` («Clienti: vendite previste,
    primi 10», fatturato o ordinato per `cliente`).
  - `PrevisionePronta(AziendaMixin)`: `chiave`, `dati` (JSON), `modello`, `calcolata_il`; unico (azienda, chiave).
  - `pronte.limitato(request, vista_id: str, campi) -> bool`: True se l'utente non è superuser e ha `RegolaRiga` per
    quella vista nel suo ruolo o un campo di `campi` tra `core.regole.nascosti(vista, request)`.
  - `pronte.dati_per(request, chiave) -> dict`: la `PrevisionePronta` salvata se `not limitato(...)`, altrimenti il
    calcolo con i permessi della request (cache 10 minuti per utente e chiave).

- [ ] **Step 1: Test che falliscono:** `test_fatturato_se_c_e_fatturazione_altrimenti_ordinato`,
  `test_prodotti_primi_dieci`, `test_notturno_salva_le_pronte_di_vendite`,
  `test_chi_ha_regole_di_riga_non_vede_le_salvate` (commerciale con `RegolaRiga` sugli ordini → dati calcolati con le
  sue righe, diversi dai salvati), `test_campo_nascosto_non_usa_le_salvate`, `test_senza_vendite_nessuna_pronta`.
- [ ] **Step 2: Eseguire** → FAIL. **Step 3: Implementare.** **Step 4: Eseguire** → PASS.
- [ ] **Step 5: Commit** `feat(previsioni): previsioni pronte di Vendite`.

### Task 11: La pagina «Previsioni» e i widget della dashboard

**Files:**
- Modify: `views.py` (`pagina`), `urls.py`, `templates/previsioni/_prodotto.html`, `apps.py` (`hooks.widget_dashboard("previsioni.pagine.widget",
  "previsioni", permission="previsioni.view_previsionepronta")`), `__manifest__.py` (menu «Previsioni»);
  Create: `addons/previsioni/pagine.py`, `templates/previsioni/pagina.html`, `templates/previsioni/_pronta.html`
- Test: `addons/previsioni/tests/test_pagina.py`

**Interfaces:**
- Consumes: `pronte.per_request`, `pronte.dati_per` (Task 10), `PrevisioneArticolo`/`StatoCalcolo` (Task 8-9),
  `motore.svg_previsione`, `motore.come_tabella`.
- Produces: URL `previsioni:pagina`; sezioni per app (Vendite, Magazzino) con le pronte (grafico per le serie
  singole, tabella per i gruppi), fascia, affidabilità, ora di calcolo, attribuzione, «Aggiorna»; in Magazzino i primi
  10 «Articoli in esaurimento» con il link alla vista; bottone «Nuova previsione» →
  `grafici:costruttore?tipo=previsione` solo se Analisi è attivo e l'utente ha `grafici.add_grafico` (senza Analisi
  il bottone non c'è: limite della v1, scritto nella pagina di aiuto); `pagine.widget(request)` dà le pronte come
  widget per la libreria della dashboard (forma di `hooks.widget_dashboard`). Nel riquadro della scheda prodotto
  (`_prodotto.html`, Task 9) la riga «Vendite previste nei prossimi 3 mesi» dal gruppo del prodotto in
  `vendite.prodotti` (via `pronte.dati_per`); se il prodotto non è tra i primi 10, «non tra i 10 più venduti».

- [ ] **Step 1: Test che falliscono:** `test_pagina_con_vendite_e_magazzino`, `test_senza_magazzino_niente_sezione`
  (e nessun errore), `test_senza_servizio_messaggio_e_ultime_salvate`, `test_nuova_previsione_solo_con_analisi`,
  `test_widget_nella_libreria_della_dashboard`, `test_utente_senza_permesso_403`,
  `test_vendite_previste_nella_scheda_prodotto` (prodotto tra i primi 10 → mediana e fascia; fuori → «non tra i 10
  più venduti»).
- [ ] **Step 2: Eseguire** → FAIL. **Step 3: Implementare.** **Step 4: Eseguire** → PASS.
- [ ] **Step 5: Commit** `feat(previsioni): pagina Previsioni e widget della dashboard`.

### Task 12: Documentazione, versioni e rilascio

**Files:**
- Modify: `docs/note-di-rilascio.md`, `README.md` (riga del modulo nella tabella «Le app»), `addons/ai/__manifest__.py`
  (versione minore), `addons/grafici/__manifest__.py` (versione minore), `core/__init__.py` (solo se il Task 4 ha
  cambiato `core.misure`: versione di correzione), `docs/features-gap-analisi.md` (AI-07: previsioni pronte di vendite
  e magazzino fatte, cassa e scostamenti ancora no)
- Test: nessuno nuovo; eseguire `addons/previsioni/tests`, `addons/ai/tests`, `addons/grafici/tests`,
  `core/tests/test_misure*.py`

- [ ] **Step 1: Note di rilascio:** modulo nuovo in licenza; con l'aggiornamento chi aveva le previsioni attraverso
  l'assistente le perde finché non ha il modulo (grafici Previsione salvati: «Serve il modulo Previsioni.»); l'URL del
  servizio passa a `previsioni.url_servizio` (copiato da sé); chiave API facoltativa nella pagina del servizio (solo
  Global Admin); limite della licenza di Timestral (20 milioni di dollari di ricavi al mese) e file LICENSE accanto ai
  pesi; dopo l'aggiornamento `modulo installa previsioni` e `collectstatic`.
- [ ] **Step 2: Eseguire** i test elencati → PASS; `modulo controlla previsioni` e `modulo collauda previsioni` → ok.
- [ ] **Step 3: Commit** `docs(previsioni): note di rilascio e analisi delle lacune`.
