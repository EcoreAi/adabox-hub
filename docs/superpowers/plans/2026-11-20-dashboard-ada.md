# Dashboard fatte da Ada Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** con una frase Ada crea una pagina di Analisi con 2-8 indicatori e grafici, con una sola conferma.

**Architecture:** uno strumento di scrittura nuovo in `addons/grafici/ai.py` (`analisi_crea_dashboard`) che riusa
`_specifica` e `_controlla` di `analisi_salva_grafico` per ogni pezzo; l'anteprima calcola i pezzi e dice quali toglie;
la conferma crea pagina, grafici e disposizione. Le composizioni-traccia sono dati nello stesso file e finiscono nella
descrizione dello strumento, filtrate sulle misure installate.

**Spec:** `docs/superpowers/specs/2026-11-20-dashboard-ada-design.md`

## Global Constraints

- Pezzi: minimo 2, massimo 8 dopo gli scarti; tipi = `Grafico.TIPI` tranne `tabella`.
- Grafico senza dati o in errore → tolto con il motivo; KPI a zero → resta.
- Pagina sempre nuova; titolo già usato dall'utente → `ErroreStrumento`.
- Disposizione: KPI `w: 1` in testa, poi grafici e previsioni `w: 2`, ordine di Ada.
- Grafico su misura con `periodo_su` senza periodo dei pulsanti → `spec["periodo"] = "anno"`.
- Versione: Analisi 1.11.0, `min_core` invariato; nessuna migrazione.

## Review Focus

- Ada passa lo stesso pezzo due volte: si crea due volte (nessuna deduplica silenziosa) — accettato, non testato.
- Misura non installata o vista non accessibile in un pezzo: tolto con il motivo, non errore di tutta la dashboard (Task 1).
- L'utente conferma dopo che i dati sono cambiati: `crea_dashboard` ricalcola e riscarta, non usa l'anteprima (Task 1).
- Modello debole che passa `pezzi` come stringa JSON: errore chiaro, non eccezione (Task 1).
- Utente senza `grafici.add_grafico`: lo strumento non è offerto (permesso, Task 2).

---

### Task 1: pezzi, anteprima e creazione (`addons/grafici/ai.py`, test `addons/grafici/tests/test_dashboard_ada.py`)

**Produces:** `prepara_pezzi(contesto, pezzi: list[dict]) -> tuple[list[dict], list[str]]` (validi: `{"tipo", "spec",
"titolo", "dati", "descrizione"}`; tolti: «Titolo — motivo»); `anteprima_crea_dashboard(contesto, titolo, pezzi, icona="bar-chart")`;
`crea_dashboard(contesto, titolo, pezzi, icona="bar-chart") -> {"esito", "url", "pagina", "grafici"}`.

- [ ] test (fixture `scena` di `fatturazione.tests.test_fatturazione`, superutente):
  - `test_dashboard_con_un_colpo`: 2 KPI + 2 grafici sul fatturato → pagina nuova, 4 `Grafico` con `origine=CHAT`,
    `layout["widget"]` = KPI con `w: 1` prima, grafici con `w: 2`; il grafico «per cliente» ha `spec["periodo"] == "anno"`.
  - `test_grafico_vuoto_tolto_kpi_a_zero_resta`: KPI scaduto (0) + grafico scaduto per cliente (vuoto) + fatturato per
    cliente → anteprima con «tolto» per il grafico vuoto; creati 2 pezzi.
  - `test_pezzo_sbagliato_tolto_con_il_motivo`: misura inesistente → nei dettagli dell'anteprima, il resto creato.
  - `test_meno_di_due_pezzi_niente_dashboard`, `test_titolo_gia_usato`, `test_piu_di_otto_pezzi` → `ErroreStrumento`.
  - `test_pezzi_non_lista`: `pezzi="[...]"` → `ErroreStrumento`.
- [ ] FAIL → implementare (per pezzo: `_specifica(... pagina/artifact assenti)` + `_controlla`; vuoto = `not dati.get("serie")`
  per grafici, `not dati.get("storico")` per previsioni) → PASS → commit.

### Task 2: composizioni e registrazione

`COMPOSIZIONI: dict[str, list[dict]]` (Vendite, Fatturazione, Acquisti, Magazzino) con pezzi su misure aziendali;
`testo_composizioni() -> str` (solo pezzi con misure in `misure.tutte()`, composizione omessa se ne restano < 2);
sottoclasse di `Strumento` con `definizione()` che aggiunge `testo_composizioni()` alla descrizione; registrazione
`analisi_crea_dashboard` (`rischio="scrittura"`, `concorrente=False`, `permesso="grafici.add_grafico"`, schema `pezzi`
array di oggetti con le proprietà di `analisi_salva_grafico` senza `pagina`/`artifact`, `minItems` 2, `maxItems` 8).
- [ ] test `test_composizioni_solo_misure_installate` (con una misura tolta dal registro col `monkeypatch`),
  `test_strumento_registrato_e_conferma` (definizione con «Vendite» e lo schema; la proposta passa da `ai.proposte`
  come `analisi_salva_grafico`) → FAIL → PASS → commit.

### Task 3: note di rilascio, versione, suite completa in 4 parti; consegna con il consenso dell'utente.
