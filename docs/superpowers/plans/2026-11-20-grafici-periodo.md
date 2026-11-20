# Periodo sul grafico Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** pulsanti Mese · Trimestre · Anno · Anno scorso (e Confronta) sui grafici con una data, in chat e in Analisi.

**Architecture:** il kernel (`core/misure.py`) dice se un grafico ha un periodo, traduce il periodo nei filtri del
calcolo e prepara la serie dell'anno prima allineata per chiave. Chat (`ai.artifact`) e Analisi (`grafici.motore`)
usano le stesse funzioni; due viste POST salvano la scelta nella specifica e rimandano la figura/card (HTMX, come ↻).
`core/grafici.js` disegna la seconda serie.

**Spec:** `docs/superpowers/specs/2026-11-20-grafici-periodo-design.md`

## Global Constraints

- Periodi dei pulsanti: `mese`, `trimestre`, `anno`, `anno_scorso` (nomi di `misure.PERIODI`); per le viste anche `""` = Sempre.
- Solo il proprietario cambia il periodo; la scelta resta nella specifica (`periodo`, `confronta`).
- I link ai record seguono il periodo (chat e Analisi).
- Confronto: etichetta «Anno prima»; mai sulle torte; mai senza periodo.
- Versioni: kernel 1.6.0, AI 1.53.0 e Analisi 1.9.0 con `min_core` "1.6". Nessuna migrazione.

## Review Focus

- Misura con `dal`/`al` fissi: nessun pulsante evidenziato; un tocco passa al periodo relativo (Task 1).
- Vista con periodo e un filtro già sulla stessa data: vale l'intersezione, il link la porta (Task 1, 2).
- Confronto su `data:mese`: gennaio 2025 accanto a gennaio 2026 (chiavi spostate di 12 mesi) (Task 1).
- Grafico condiviso: chi non è il proprietario non vede i pulsanti e la POST risponde 404 (Task 3, 4).
- Torta con `confronta` salvato: nessuna seconda serie (Task 2).

---

### Task 1: Kernel — periodo e confronto (`core/misure.py`, test in `core/tests/test_misure.py`)

**Produces:** `PULSANTI_PERIODO`; `periodo_grafico(spec) -> dict | None` (`{"scelto", "sempre", "confronta", "pulsanti"}`);
`spec_per_calcolo(spec) -> dict`; `spec_anno_prima(spec) -> dict | None`; `temporale(spec) -> bool`;
`con_confronto(dati, prima, temporale) -> dati` (aggiunge `confronto: {"etichetta", "valori"}` allineato per `chiavi`).

- [ ] test `test_periodo_del_grafico_solo_dove_c_e_una_data`, `test_periodo_di_una_vista_filtra_la_data_del_raggruppamento`,
  `test_anno_prima_sposta_il_periodo`, `test_confronto_allineato_per_chiave_e_per_mese` → FAIL → implementare → PASS → commit.

### Task 2: Chat e Analisi calcolano con il periodo e il confronto

`ai.artifact.calcola` (ramo grafico: `spec_per_calcolo` per vista e link, `chiavi` nei dati, confronto se `confronta` e
non torta); `grafici.motore.dati_di` e `serie_di` (stesso; `link_lista` con `spec_per_calcolo`; `confronto` nella serie);
filtro `serie_artifact` passa `confronto`.
- [ ] test in `addons/ai/tests/test_grafici_periodo.py` e `addons/grafici/tests/test_misure.py` → FAIL → PASS → commit.

### Task 3: Chat — pulsanti e vista POST

`ai:periodo_artifact` (POST `periodo`, `confronta`; proprietario; valida; salva spec; `ricalcola`; risponde `_artifact.html`).
Template condiviso `core/templates/core/_periodo_grafico.html` (form HTMX: un bottone per periodo, Sempre per le viste,
Confronta come interruttore). Filtro `periodo_artifact(a)` in `ai.templatetags.ai`.
- [ ] test pagina e POST → FAIL → PASS → commit.

### Task 4: Analisi — pulsanti nella card e vista POST

`grafici:grafico_periodo` (POST, proprietario, salva spec, `widget_salvato(forza=True)`, risponde `_widget.html`);
`w["periodo"]` in `widget_salvato`; include del template condiviso nella testata della card.
- [ ] test → FAIL → PASS → commit.

### Task 5: `grafici.js` — seconda serie

Barre e linee con `serie.confronto`: dataset in più, colore chiaro, legenda visibile; torta ignora `confronto`.
- [ ] prova jsdom (`scratchpad/prova_js/prova_confronto.js`) → FAIL → PASS → commit.

### Task 6: note di rilascio, versioni, suite completa, consegna con il consenso dell'utente.
