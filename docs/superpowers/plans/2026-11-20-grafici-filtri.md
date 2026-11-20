# Filtri sul grafico Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** «Filtra» sopra i grafici (chat e Analisi): un valore per filtro, etichette con ×, ricalcolo sul posto.
**Spec:** `docs/superpowers/specs/2026-11-20-grafici-filtri-design.md`

## Global Constraints
- Specifica: `scelti = {campo: {"chiave": str|int|bool, "etichetta": str}}`; misure: `campo` = nome del raggruppamento;
  viste: nome del campo dell'elenco.
- Massimo 30 valori per filtro nel pannello, dal più grande.
- Versioni: kernel 1.7.0, AI 1.54.0, Analisi 1.10.0 (`min_core` "1.7"), Vendite +0.1.0 (raggruppamento commerciale).

## Review Focus
- Filtro + periodo + confronto insieme: l'anno prima usa lo stesso filtro.
- Filtro su un campo che l'elenco non filtra (es. misura con componente su un'altra vista): numeri filtrati, link vuoti.
- Valore scelto che non c'è più nei dati: il grafico resta vuoto e l'etichetta si può togliere.
- Grafico condiviso: chi non è il proprietario vede il filtro accanto al titolo ma non può cambiarlo (404).

### Task 1: kernel — `misure.calcola(..., scelti)`, `filtri_grafico(spec, request)`, `valori_filtro(spec, campo, request)`,
`scegli_filtro(spec, campo, chiave, etichetta)`, `spec_per_calcolo` con `scelti` per le viste, `etichetta_filtri(spec)`.
Test in `core/tests/test_misure.py`.
### Task 2: chat — viste `ai:filtri_artifact` (GET, pannello) e `ai:filtro_artifact` (POST), etichette nel template del
periodo, testo accanto al titolo. Test in `addons/ai/tests/test_grafici_filtri.py`.
### Task 3: Analisi — `grafici:grafico_filtri` / `grafici:grafico_filtro`, stessa resa nella card; descrizione con i filtri.
### Task 4: `vendite.ordinato` raggruppabile per commerciale; note di rilascio, versioni, suite, revisione, consegna.
