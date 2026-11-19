# Grafici cliccabili Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** in chat e in Analisi un clic su barra, punto o fetta apre l'elenco dei record di quel gruppo; in chat i grafici
si disegnano con lo script di Analisi.

**Architecture:** i link per punto si calcolano sul server insieme ai dati (`link` accanto a `serie`) e si salvano con
l'istantanea. Un solo costruttore nel kernel (`interroga.link_gruppo`) per i grafici sulle viste; per le misure il link
per gruppo di `misure.calcola`. In chat `_artifact.html` mette canvas + JSON e `core/grafici.js` disegna; l'SVG resta in
`<noscript>` e nel PDF.

**Tech Stack:** Django, Chart.js (`theme/vendor/chart.umd.js`), `core/static/core/grafici.js`, pytest, jsdom per lo script.

**Spec:** `docs/superpowers/specs/2026-11-19-grafici-cliccabili-design.md`

## Global Constraints

- Un link che mostra record diversi dal numero è peggio di nessun link: in quel caso `None`/`""` e niente manina.
- Dalla chat e dalla pagina del grafico l'elenco si apre in una scheda nuova; in Analisi nella stessa scheda, come oggi.
- I grafici già salvati senza `link` restano non cliccabili finché non si aggiornano con ↻.
- Previsioni, PDF e CSV non cambiano. Le previsioni in chat restano SVG.
- Versioni: kernel 1.5.0; AI 1.50.0 e Analisi 1.8.0 con `min_core` "1.5". Nessuna migrazione.
- Test mirati: `PYTHONPATH=<scratchpad>/impostazioni pytest --ds=prova_apertura --reuse-db …` (nota della memoria sui test lenti);
  controllo finale senza `--reuse-db`.

## Review Focus

- Torta con più di 5 fette: `grafici.js` riunisce le ultime in «Altro» e riordina; il clic deve aprire la fetta cliccata, «Altro» niente (Task 4).
- Grafico per data (`data:mese`) con mesi senza record: le chiavi `None` non devono spostare i link degli altri punti (Task 3).
- Grafico con `primi` (prime N più «Altro»): link allineati ai primi N, «Altro» senza link (Task 3).
- Misura raggruppata per un campo che l'elenco filtra (fatturato per cliente): il link deve portare anche i filtri della misura (solo emesse), non solo il cliente (Task 2).
- ↻ in chat: dopo l'aggiornamento il grafico si ridisegna con i link nuovi, senza duplicati del canvas (Task 5).

---

### Task 1: Costruttore dei link nel kernel e link nelle serie delle misure

**Files:**
- Modify: `core/viste/interroga.py` (nuova `link_gruppo`)
- Modify: `addons/grafici/motore.py:123-146` (`link_lista` diventa un richiamo a `interroga.link_gruppo`)
- Modify: `core/misure.py` (`serie` aggiunge `link`)
- Modify: `core/__init__.py` (1.5.0)
- Test: `core/tests/test_misure.py`

**Interfaces:**
- Produces: `interroga.link_gruppo(vista, spec: dict, chiave) -> str | None` (stesso comportamento di `link_lista` oggi);
  `misure.serie(spec, request)` ritorna anche `"link": list[str | None]`, allineata a `serie` («Altro» → `None`).

- [ ] **Step 1: test** `test_serie_porta_il_link_di_ogni_gruppo` in `core/tests/test_misure.py` con il registro di prova
  (`_netto` o una misura con `filtri_lista`/filtri esprimibili e `raggruppamenti={"stato": "stato"}`): `len(r["link"]) == len(r["serie"])`,
  ogni link contiene `f_stato=<chiave>` e i filtri della misura; con `primi=1` e due gruppi l'ultimo link è `None`.
- [ ] **Step 2:** eseguire, atteso FAIL (`KeyError: 'link'`).
- [ ] **Step 3:** `link_gruppo` = corpo di `link_lista` spostato; `misure.serie` prende `g["url"] or None` dai gruppi di `calcola`, aggiungendo `None` per «Altro».
- [ ] **Step 4:** eseguire `core/tests/test_misure.py` e `addons/grafici/tests` (il drill-down del costruttore non cambia): PASS.
- [ ] **Step 5: commit** `feat(kernel): link per gruppo nelle serie delle misure; costruttore dei link nel kernel`

### Task 2: Analisi usa i link delle misure

**Files:**
- Modify: `addons/grafici/motore.py` (`serie_di`: se `dati` ha `link` usa quelli, altrimenti `link_gruppo` come oggi)
- Modify: `addons/grafici/__manifest__.py` (1.8.0, `min_core` "1.5")
- Test: `addons/grafici/tests/test_misure.py`

- [ ] **Step 1: test** `test_grafico_su_misura_cliccabile_solo_sulle_emesse`: con la `scena` della fatturazione, una fattura emessa e una in bozza
  dello stesso cliente, `serie_di(Grafico(tipo="torta", spec={"misura_aziendale": "fatturazione.fatturato", "per": "cliente", "periodo": "anno"}), dati, vista)`
  → `link[0]` contiene `f_cliente=<pk>` e il filtro delle emesse (`LISTA_EMESSE` di `fatturazione/misure.py`) e le date dell'anno.
- [ ] **Step 2:** FAIL. **Step 3:** implementare. **Step 4:** `addons/grafici/tests` PASS.
- [ ] **Step 5: commit** `feat(analisi): grafici sulle misure aziendali cliccabili`

### Task 3: I grafici della chat portano i link

**Files:**
- Modify: `addons/ai/artifact.py` (`calcola`, ramo grafico su vista; `_serie_scelta` lavora su terne con la chiave)
- Test: `addons/ai/tests/test_grafici_cliccabili.py` (nuovo)

**Interfaces:**
- Consumes: `interroga.link_gruppo`, `misure.serie(...)["link"]`.
- Produces: `artifact.calcola(spec, contesto)` per i grafici ritorna `{"serie", "totale", "link": list[str | None]}` allineata a `serie`.

- [ ] **Step 1: test** (fixture come `test_strumenti_app.py`, vista `todo.attivita` che filtra per `stato`):
  - `test_grafico_per_stato_ha_un_link_per_barra`: `link == [lista + "?f_stato=aperta", lista + "?f_stato=fatta"]` nell'ordine della serie;
  - `test_primi_altro_senza_link`: `primi=1` → ultimo link `None`;
  - `test_campo_che_la_lista_non_filtra_niente_link`: `per="scadenza:mese"` → tutti `None`;
  - `test_grafico_su_misura_ha_i_link` (in `test_misure_ada.py`): `artifact.grafico(contesto, misura_aziendale="fatturazione.fatturato", per="cliente", periodo="anno")` → `Artifact.dati["link"][0]` non vuoto.
- [ ] **Step 2:** FAIL. **Step 3:** `aggrega(..., con_chiavi=True)`; la serie con «Altro»/ordina/primi tiene la chiave a fianco (riusare `interroga.serie_con_chiavi` e `_primi_con_chiavi` dove coincidono); `link = [link_gruppo(v, spec, k) for k in chiavi]`.
- [ ] **Step 4:** `addons/ai/tests/test_grafici_cliccabili.py addons/ai/tests/test_misure_ada.py addons/ai/tests/test_ai.py` PASS.
- [ ] **Step 5: commit** `feat(ai): i grafici della chat sanno quali record ci sono dietro ogni punto`

### Task 4: `grafici.js`: torta allineata e scheda nuova

**Files:**
- Modify: `core/static/core/grafici.js` (`fette` porta il link di ogni fetta, «Altro» senza; `apri` con `serie.nuova_scheda` usa `window.open(url, '_blank', 'noopener')`)
- Test: `<scratchpad>/prova_js/prova_grafici.js` (jsdom con `Chart` finto che registra la configurazione; fuori dal repository)

- [ ] **Step 1: prova** con 7 fette (valori distinti, link `/l/0`…`/l/6`): il clic sull'indice della fetta più grande apre il suo link;
  il clic su «Altro» non apre nulla; con `nuova_scheda: true` si chiama `window.open` e non cambia `location`.
- [ ] **Step 2:** sullo script attuale FAIL. **Step 3:** implementare. **Step 4:** PASS.
- [ ] **Step 5: commit** `fix(grafici.js): il clic sulla torta apre la fetta giusta; link in una scheda nuova a richiesta`

### Task 5: La chat e la pagina del grafico disegnano con `grafici.js`

**Files:**
- Modify: `addons/ai/templatetags/ai.py` (filtro `serie_artifact(a, dati=None) -> dict | None`: `{"tipo", "titolo", "etichette", "valori", "link", "nuova_scheda": True}`; `None` per le previsioni)
- Modify: `addons/ai/templates/ai/_artifact.html`, `addons/ai/templates/ai/artifact.html` (canvas `data-grafico="ai-serie-{{ a.pk }}"` in `.wd-canvas`, `json_script`, SVG in `<noscript>`; previsioni come oggi)
- Modify: `addons/ai/templates/ai/chat.html`, `ai/artifact.html` (script `theme/vendor/chart.umd.js` e `core/grafici.js`, `defer`)
- Modify: `addons/ai/static/ai/chat.js` (dopo l'evento `fine`: `window.adaboxGrafici && adaboxGrafici.tutti(messaggi)`)
- Modify: `addons/ai/static/ai/chat.css` (altezza del grafico in chat: 280 px)
- Modify: `addons/ai/__manifest__.py` (1.50.0, `min_core` "1.5")
- Test: `addons/ai/tests/test_grafici_cliccabili.py`

- [ ] **Step 1: test** `test_la_chat_disegna_il_grafico_cliccabile`: un artifact grafico con `dati["link"]` → l'HTML della conversazione ha
  `data-grafico="ai-serie-<pk>"`, il JSON con `"link"` e `"nuova_scheda": true`, `core/grafici.js` e `<noscript>`;
  `test_aggiorna_ridisegna_con_i_link`: POST HX a `ai:aggiorna_artifact` → canvas e JSON una volta sola, link presenti;
  `test_previsione_resta_svg`: artifact previsione → niente canvas, SVG presente;
  `test_pagina_del_grafico_cliccabile`: `ai:artifact` → canvas e JSON con i link dei dati di oggi.
- [ ] **Step 2:** FAIL. **Step 3:** implementare. **Step 4:** `addons/ai/tests` mirati PASS; prova jsdom della chat (pagina salvata da un test temporaneo) con `Chart` finto: dopo `fine` il canvas è disegnato.
- [ ] **Step 5: commit** `feat(ai): grafici della chat interattivi e cliccabili`

### Task 6: Documentazione, suite e consegna

**Files:** `docs/note-di-rilascio.md` (2026-11-19: Kernel 1.5.0, AI 1.50.0, Analisi 1.8.0, nessuna migrazione), README/documentazione delle misure se cita il drill-down.

- [ ] **Step 1:** note di rilascio. **Step 2:** suite completa in 4 parti come la CI, senza `--reuse-db`: atteso 0 fallimenti.
- [ ] **Step 3: commit** `docs: grafici cliccabili`. **Step 4:** con il consenso dell'utente: unione su main, `modulo aggiorna --tutti`, riavvio.
