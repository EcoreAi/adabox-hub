# Ricerca in Preferiti e Aree di lavoro — piano

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** un campo di ricerca nei pannelli Preferiti e Aree di lavoro della chat, che filtra nella pagina.

**Architecture:** i template marcano pannello, campo, gruppi e voci con attributi `data-filtra*` e `data-cerca`; un
blocco di `chat.js` filtra le voci per parole (senza accenti né maiuscole), nasconde i gruppi vuoti, aggiorna i numeri
e rimette tutto com'era a campo vuoto.

**Tech Stack:** template Django, JavaScript senza librerie in `addons/ai/static/ai/chat.js`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-27-cerca-preferiti-aree-design.md`

## Global Constraints

- Nessuno script nella pagina: tutto in `chat.js`.
- Normalizzazione come `core/static/core/applicazioni.js`: `normalize('NFD')`, via i segni diacritici, minuscole; tutte
  le parole devono esserci.
- Testi: «Cerca nei preferiti…», «Cerca nelle aree…», «Nessun preferito trovato.», «Nessuna area trovata.».
- AI 1.61.2 → **1.62.0**; nota in `docs/note-di-rilascio.md` (sezione 2026-11-27).

## Review Focus

1. Parole con accenti o maiuscole («Città», «FORNITORI») → trovano lo stesso: prova jsdom (Task 2).
2. Campo svuotato (× del campo search, o cancellando) → tornano voci, numeri e gruppi chiusi dall'utente: prova jsdom (Task 2).
3. Titolo con virgolette o `<` → `data-cerca` resta un attributo valido: test di markup (Task 1).
4. Area aperta mentre si cerca → il suo albero caricato dopo non viene filtrato né rotto (nessun `data-cerca` dentro
   l'albero): test di markup sul frammento dell'albero (Task 1).
5. Nessuna voce → nessun campo (niente ricerca su un pannello vuoto): test di markup (Task 1).

---

### Task 1: markup dei pannelli

**Files:**
- Modify: `addons/ai/templates/ai/chat.html` (sezioni `preferite` e `progetti`)
- Modify: `addons/ai/templates/ai/_elenco_chat.html`, `addons/ai/templates/ai/_elenco_artifact.html`
- Test: `addons/ai/tests/test_cerca_pannelli.py` (nuovo)

**Interfaces:**
- Produces: `section[data-filtra]` › `input[data-filtra-campo]`, `[data-filtra-vuoto][hidden]`,
  `details[data-filtra-gruppo]` › `summary .ai-conta`, voci `li[data-cerca]`, righe `[data-filtra-nascondi]`.

- [ ] **Step 1: test che falliscono** — `test_preferiti_hanno_il_campo_e_le_voci_cercabili` (campo, vuoto nascosto,
  quattro gruppi con `data-filtra-gruppo`, `data-cerca` di una chat preferita in un'area contiene titolo e nome area, di
  un documento e di un grafico il titolo); `test_aree_hanno_il_campo_e_le_voci_cercabili` (campo, `data-cerca` = nome
  dell'area, «Nuova chat» di un'altra azienda con `data-filtra-nascondi`, gruppi delle aziende con `data-filtra-gruppo`);
  `test_senza_voci_niente_campo`; `test_titolo_con_virgolette_resta_un_attributo` (`&quot;` nel `data-cerca`);
  `test_l_albero_dell_area_non_ha_voci_cercabili`.
- [ ] **Step 2:** `.venv/bin/pytest -q -p no:cacheprovider addons/ai/tests/test_cerca_pannelli.py` → FAIL.
- [ ] **Step 3:** attributi e campi nei template; campo con classe `ai-cerca-chat` come la Cronologia, `type="search"`,
  `autocomplete="off"`, `aria-label`.
- [ ] **Step 4:** stesso comando → PASS; più `addons/ai/tests/test_aree_piu_aziende.py`.

### Task 2: filtro in chat.js, versione e nota

**Files:**
- Modify: `addons/ai/static/ai/chat.js` (dopo il blocco «colonna di sinistra: le sottocartelle…»)
- Modify: `addons/ai/__manifest__.py` (1.62.0), `docs/note-di-rilascio.md`
- Test: `addons/ai/tests/test_cerca_pannelli.py`; prova jsdom in scratchpad (fuori dal repository)

**Interfaces:**
- Consumes: gli attributi del Task 1.

- [ ] **Step 1: test che fallisce** — `test_lo_script_filtra_i_pannelli`: in `chat.js` ci sono `[data-filtra]`,
  `data-filtra-campo`, `normalize('NFD')`, `parole.every`, `dataset.cerca`, `dataset.totale`, `data-filtra-nascondi`.
- [ ] **Step 2:** → FAIL.
- [ ] **Step 3:** il filtro: per ogni `[data-filtra]`, a ogni `input`/`search` del campo: voci nascoste se non contengono
  tutte le parole; righe `data-filtra-nascondi` nascoste mentre si cerca; per gruppo numero dei risultati (il numero di
  prima in `dataset.totale`), gruppo nascosto se 0, aperto se >0; stato aperto/chiuso dei gruppi salvato alla prima
  lettera e rimesso a campo vuoto; messaggio vuoto se si cerca e non c'è nulla.
- [ ] **Step 4:** test → PASS; `core/tests/test_js_sintassi.py` → PASS.
- [ ] **Step 5:** prova jsdom sulla pagina vera salvata da un test temporaneo: accenti/maiuscole, più parole, gruppi,
  numeri, vuoto, ripristino (Review Focus 1–2).
- [ ] **Step 6:** manifest 1.62.0 e nota; commit.
