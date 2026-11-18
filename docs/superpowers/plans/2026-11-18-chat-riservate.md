# Chat riservate: solo modelli locali — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ada usa solo modelli locali nelle chat che hanno letto dati da fonti riservate (app intere, cartelle dei Documenti, chat segnate dall'utente), e il connettore verso le chat esterne non restituisce quei dati.

**Architecture:** Un modulo nuovo `addons/ai/riservatezza.py` sa quali fonti sono riservate e, dato uno strumento eseguito, se ha letto una fonte riservata. Quando succede la `Conversazione` diventa riservata per sempre. `riservatezza.filtra()` riduce ogni catena di modelli ai soli locali prima di ogni chiamata al gateway: turni, compattazione, titoli, verifica, riassunti dei documenti. Senza modello locale il turno si ferma con un messaggio e non parte nulla.

**Tech Stack:** Django 5.2, pytest. Moduli `ai` (1.47.0 → 1.48.0), `documenti` (1.2.0 → 1.3.0), `connettore_ai` (1.1.0 → 1.2.0).

**Spec:** le decisioni dell'utente del 2026-11-18, riportate qui sotto (non c'è un documento separato).

## Decisioni (spec)

1. Fonti riservate nel primo giro: **app intere, per azienda**; **cartelle dei Documenti**, comprese le sottocartelle; **singola chat**, segnata dall'utente. Le aree di lavoro (`ProgettoChat`) vengono in un giro successivo.
2. Una chat diventa riservata **in modo permanente** quando uno strumento legge una fonte riservata, o quando l'utente la segna. Non si torna indietro.
3. Da quel momento ogni chiamata a un modello per quella chat usa **solo modelli con `provider.locale=True`**. Il risultato riservato non arriva mai a un modello cloud, nemmeno tramite titolo, riassunto (compattazione) o verifica delle citazioni.
4. **Scelta A:** senza un modello locale attivo Ada **si ferma** e non invia nulla, con un messaggio chiaro.
5. Il connettore verso le chat esterne (`connettore_ai`) non restituisce dati delle fonti riservate.
6. In chat compare "Riservata · solo modelli locali"; lo riporta anche la provenienza sotto la risposta.

## Global Constraints

- Sviluppo nel worktree `wt-riservato`, ramo `chat-riservate`. Mai cambiare ramo in `/opt/adabox-hub`: l'istanza monta quella cartella.
- Il modulo `ai` non dipende da `documenti`: ogni accesso a `documenti` passa da `ai.archivio.attivo()` e da import dentro le funzioni.
- Testi per l'utente in italiano, frasi brevi, come il resto di Ada.
- Messaggio di blocco (copia esatta): `Questa chat contiene dati riservati: può rispondere solo un modello locale, e nessuno è attivo. Non ho inviato nulla.`
- Etichetta in chat e nella provenienza (copia esatta): `Riservata · solo modelli locali`.
- Motivo quando la segna l'utente: `segnata dall'utente`. Motivo da app: `app «<slug>»`. Motivo da cartella: `cartella «<percorso>»`.
- Impostazione per azienda `ai.app_riservate`: testo, slug separati da virgola, confronto senza maiuscole né spazi (stesso schema di `pii_escludi`).
- Test mirati con `--reuse-db` (impostazioni in `scratchpad/testcfg/impostazioni_test.py`); il controllo finale senza `--reuse-db`.

## Review Focus

1. **Risultato di uno strumento in errore** (vista inesistente, permesso negato): non rende riservata la chat. Test nel Task 2.
2. **Nessun modello locale nella catena del profilo, ma uno attivo nell'istanza**: si usa quello, non ci si ferma. Test nel Task 3.
3. **Chat riservata con un modello cloud scelto nel selettore**: risponde comunque un modello locale. Test nel Task 3.
4. **Sottocartella di una cartella riservata, anche spostata lì dopo**: è riservata, calcolata al momento e non in cache. Test nel Task 2.
5. **Chat riservata che interpella un esperto**: l'esperto nasce riservato, e un esperto che legge dati riservati rende riservata la chat che l'ha chiamato. Test nel Task 4.

---

### Task 1: Campi, migrazioni e impostazione

**Files:**
- Modify: `addons/ai/models.py` (`Conversazione`)
- Create: `addons/ai/migrations/0041_conversazione_riservata.py`
- Modify: `addons/ai/__manifest__.py` (versione `1.48.0`; voce `app_riservate` in `"settings"`, accanto a `pii_escludi`)
- Modify: `addons/documenti/models.py` (`Cartella`)
- Create: `addons/documenti/migrations/0003_cartella_riservata.py`
- Modify: `addons/documenti/views.py` (`CartellaView.form_layout`: `riservata` nel gruppo "Permessi")
- Modify: `addons/documenti/__manifest__.py` (versione `1.3.0`)
- Test: `addons/ai/tests/test_riservatezza.py` (nuovo)

**Interfaces:**
- Produces:
  - `Conversazione.riservata: BooleanField("riservata", default=False, editable=False)`
  - `Conversazione.riservata_motivo: CharField("motivo della riservatezza", max_length=200, blank=True, editable=False)`
  - `Cartella.riservata: BooleanField("riservata per l'assistente", default=False, help_text="l'assistente legge questa cartella e le sottocartelle solo con modelli locali")`
  - impostazione `ai.app_riservate`: `{"chiave": "app_riservate", "label": "App riservate: solo modelli locali", "tipo": "testo", "default": "", "per_azienda": True, "help": "slug delle app separati da virgola, es. personale, banca"}`

- [ ] **Step 1: Test** `test_campi_e_impostazione_di_partenza`: una `Conversazione` nuova ha `riservata is False` e `riservata_motivo == ""`; `parametri.leggi("ai.app_riservate", azienda) == ""`; una `Cartella` nuova ha `riservata is False`.
- [ ] **Step 2: Esegui e verifica che fallisca** (`AttributeError` o `KeyError`).
- [ ] **Step 3: Aggiungi campi, impostazione e layout**, poi genera le migrazioni con `ADDONS_FORCE=ai,documenti python manage.py makemigrations ai documenti -n <nome>`.
- [ ] **Step 4: Esegui e verifica che passi.**
- [ ] **Step 5: Commit** `feat(ai,documenti): campi e impostazione delle fonti riservate`

### Task 2: `riservatezza.py`, quali fonti sono riservate e cosa ha letto uno strumento

**Files:**
- Create: `addons/ai/riservatezza.py`
- Test: `addons/ai/tests/test_riservatezza.py`

**Interfaces:**
- Consumes: i campi del Task 1.
- Produces:
  - `app_riservate(azienda) -> set[str]`
  - `cartelle_riservate(azienda) -> dict[int, str]`: id della cartella → percorso della cartella riservata da cui discende (le figlie ereditano). Calcolata a ogni chiamata, senza cache. `{}` se `documenti` non è attivo.
  - `fonte_riservata(nome: str, argomenti: dict, contenuto: str, azienda, app_strumento: str = "") -> str`: motivo, oppure `""`.
  - `risultati_ammessi(risultati: list[dict], azienda) -> list[dict]`: gli elementi di `cerca_conoscenza` che non vengono da fonti riservate (per il connettore).
  - `segna(conversazione, motivo: str) -> None`: imposta `riservata=True`; `riservata_motivo` resta il primo motivo; salva solo quei due campi.

Regole di `fonte_riservata` (in quest'ordine, la prima che scatta dà il motivo):
1. argomento `vista` o `misura_aziendale`/`nome` di una misura (`core.misure.per_nome`): l'app è il prefisso della vista, oppure `Misura.app` e le app delle viste dei suoi `componenti`;
2. `app_strumento` (la `Strumento.app` dello strumento, es. `calendario`, `discuss`, `grafici`, `documenti`) in `app_riservate`;
3. `analisi_leggi_pagina` quando `app_riservate` non è vuoto: le pagine di Analisi possono mostrare dati di qualunque app, quindi la si tratta come riservata (scelta prudente del primo giro);
4. `leggi_documento` / `leggi_foglio`: il `Documento` `argomenti["id"]` è in una cartella di `cartelle_riservate`;
5. `cerca_conoscenza`: `contenuto` è JSON con `risultati`. Un elemento con prefisso di `vista` riservato, oppure `vista == "documenti.documenti"` con `id` di un documento in cartella riservata.

- [ ] **Step 1: Test** (uno per regola, più quelli della Review Focus):
  - `test_app_riservate_normalizza`: impostazione `" Personale, BANCA ,"` → `{"personale", "banca"}`.
  - `test_vista_di_app_riservata`: `fonte_riservata("cerca_record", {"vista": "personale.dipendenti"}, "[]", az) == "app «personale»"`; con `"vendite.ordini"` → `""`.
  - `test_misura_con_componente_riservato`: una misura di `fatturazione` con un componente su una vista di `banca`, con `banca` riservata → motivo `app «banca»`.
  - `test_strumento_di_app_riservata`: `fonte_riservata("calendario_agenda", {}, "{}", az, app_strumento="calendario")` con `calendario` riservata → `app «calendario»`.
  - `test_documento_in_sottocartella_riservata`: cartella `Personale` riservata, sottocartella `Buste paga`, documento lì → `leggi_documento` con quell'id → `cartella «Personale»`. Poi una cartella `Altro` spostata sotto `Personale` → anche i suoi documenti sono riservati, senza ricaricare nulla.
  - `test_cerca_conoscenza_risultati_misti`: un risultato da cartella riservata e uno no → motivo non vuoto; `risultati_ammessi` tiene solo il secondo.
  - `test_errore_non_rende_riservata`: chi chiama passa solo risultati senza errore. Il test verifica che `segna` non venga chiamata dall'aggancio del Task 3 per un risultato con `errore=True` (lo si scrive nel Task 3).
  - `test_segna_tiene_il_primo_motivo`: due `segna` con motivi diversi → resta il primo.
- [ ] **Step 2: Esegui e verifica che falliscano.**
- [ ] **Step 3: Implementa le funzioni.** Il percorso della cartella si ricava con `Cartella.percorso()`. Le cartelle riservate si calcolano con una sola query su `Cartella.objects.filter(azienda=azienda)` (id, padre_id, riservata, nome) e una visita dell'albero in memoria, con il limite di profondità 50 come in `documenti/accesso.py`.
- [ ] **Step 4: Esegui e verifica che passino.**
- [ ] **Step 5: Commit** `feat(ai): riconoscere le letture da fonti riservate`

### Task 3: Solo modelli locali nel ciclo della risposta

**Files:**
- Modify: `addons/ai/riservatezza.py` (`filtra`, `locali`)
- Modify: `addons/ai/motore/turni.py` (`esegui`: dopo il calcolo di `catena` alle righe 231-232; dopo `strumenti.esegui` alle righe 329-336)
- Test: `addons/ai/tests/test_riservatezza_turni.py` (nuovo)

**Interfaces:**
- Consumes: `fonte_riservata`, `segna` (Task 2); `catalogo.NessunModello`.
- Produces:
  - `MESSAGGIO_SENZA_LOCALE` (la copia esatta delle Global Constraints)
  - `locali(azienda) -> list[tuple[Modello, str]]`: modelli attivi con provider attivo e locale e `strumenti=True`, ordinati per pk, con la chiave `provider.chiave_per(azienda)`.
  - `filtra(catena, conversazione, azienda) -> list[tuple[Modello, str]]`: se la conversazione non è riservata, restituisce `catena` invariata. Altrimenti restituisce gli anelli locali di `catena`; se non ce ne sono, `locali(azienda)`; se è vuoto anche quello, solleva `catalogo.NessunModello(MESSAGGIO_SENZA_LOCALE)`.

Aggancio in `turni.esegui`:
- dopo `catena = limiti.ammessi(...)`: `catena = riservatezza.filtra(catena, conversazione, turno.azienda)`;
- dopo `risultati = strumenti.esegui(...)`: per ogni coppia `(c, r)` con `not r["errore"]`, se `riservatezza.fonte_riservata(c.nome, c.argomenti, r["contenuto"], turno.azienda, getattr(ammessi.get(c.nome), "app", ""))` dà un motivo, `riservatezza.segna(conversazione, motivo)`. Poi, se la conversazione è riservata, `catena = riservatezza.filtra(catena, conversazione, turno.azienda)`, **prima** del passo successivo.

Per i test segui lo schema di `addons/ai/tests/test_agenti.py` e `test_chat_basi.py`: provider `finto` con copioni. Serve un provider finto **non locale** (cloud) e uno **locale**, e si verifica quale modello risponde a ogni passo (`Turno.modello`, o gli `Inizio` registrati).

- [ ] **Step 1: Test**
  - `test_dopo_una_lettura_riservata_risponde_il_locale`: catena [cloud, locale]; il passo 1 (cloud) chiama `cerca_record` su `personale.*`, con `personale` riservata; il passo 2 è eseguito dal modello locale; la conversazione è riservata con motivo `app «personale»`.
  - `test_senza_locale_si_ferma_senza_inviare`: catena [cloud] e nessun locale attivo; dopo la lettura riservata il turno è in `ERRORE`, il testo contiene `MESSAGGIO_SENZA_LOCALE`, e il cloud non riceve una seconda chiamata.
  - `test_locale_fuori_dalla_catena`: catena [cloud] ma un modello locale attivo nell'istanza → il passo 2 lo usa (Review Focus 2).
  - `test_chat_riservata_ignora_il_modello_scelto`: chat già riservata, `conversazione.modello` = cloud, funzione `piu_modelli` attiva → risponde il locale (Review Focus 3).
  - `test_risultato_in_errore_non_rende_riservata`: `cerca_record` su vista riservata che restituisce errore → la chat resta non riservata (Review Focus 1).
- [ ] **Step 2: Esegui e verifica che falliscano.**
- [ ] **Step 3: Implementa** `locali`, `filtra` e i due agganci.
- [ ] **Step 4: Esegui** questi test e `addons/ai/tests/test_agenti.py`, `test_chat_basi.py`, `test_gateway.py`: tutti passano.
- [ ] **Step 5: Commit** `feat(ai): le chat riservate usano solo modelli locali`

### Task 4: Nessuna uscita dietro le quinte (titoli, compattazione, verifica, riassunti, esperti)

**Files:**
- Modify: `addons/ai/motore/titoli.py:26-29`, `addons/ai/motore/compattazione.py:85-89`, `addons/ai/verifica.py:168-170`, `addons/ai/conoscenza.py:453-456`, `addons/ai/strumenti/esperti.py:29` e il ritorno del turno interno
- Test: `addons/ai/tests/test_riservatezza_turni.py`

**Interfaces:**
- Consumes: `filtra`, `locali`, `cartelle_riservate`, `segna`.
- Produces: nessuna interfaccia nuova.

Comportamento:
- **titoli**: `catena = riservatezza.filtra(...)`; con `NessunModello` il titolo non si genera (resta quello di partenza), senza errore.
- **verifica**: come i titoli; senza locale la verifica delle citazioni si salta.
- **compattazione**: `filtra`; `NessunModello` risale al gestore del turno, che mostra il messaggio.
- **riassunto di un documento** (`conoscenza.riassumi(d, ...)`): se `d.cartella_id` è in `cartelle_riservate(d.azienda)`, catena ridotta ai locali (`[a for a in catena if a[0].provider.locale] or locali(d.azienda)`); se vuota il riassunto si salta.
- **esperti**: la conversazione interna nasce con `riservata`/`riservata_motivo` della chat chiamante; dopo il turno interno, se `interna.riservata`, `segna(contesto.conversazione, interna.riservata_motivo)`.

- [ ] **Step 1: Test**
  - `test_titolo_di_chat_riservata_solo_in_locale`: chat riservata, catena titoli [cloud] e nessun locale → `titoli.genera` non chiama il cloud e il titolo resta `Nuova chat`.
  - `test_compattazione_riservata_senza_locale_si_ferma`: chat riservata e lunga oltre la soglia → il turno finisce in `ERRORE` con `MESSAGGIO_SENZA_LOCALE`, e il cloud non viene chiamato.
  - `test_verifica_saltata_senza_locale`: `verifica.citazioni` su chat riservata senza locale non chiama il cloud.
  - `test_riassunto_documento_riservato`: documento in cartella riservata, nessun locale → nessuna chiamata, riassunto vuoto.
  - `test_esperto_eredita_e_propaga`: chat riservata → la conversazione interna dell'esperto è riservata; chat non riservata il cui esperto legge `personale.*` → al ritorno la chat chiamante è riservata (Review Focus 5).
- [ ] **Step 2: Esegui e verifica che falliscano.**
- [ ] **Step 3: Implementa i cinque agganci.**
- [ ] **Step 4: Esegui e verifica che passino.**
- [ ] **Step 5: Commit** `feat(ai): titoli, riassunti e verifica rispettano le chat riservate`

### Task 5: Interfaccia: segnare la chat, etichetta, provenienza

**Files:**
- Modify: `addons/ai/pagine.py` (vista `riservata`, accanto a `preferita` alla riga 440)
- Modify: `addons/ai/urls.py` (`chat/<int:pk>/riservata/`, nome `riservata`)
- Modify: `addons/ai/templates/ai/chat.html:100-117` (etichetta e pulsante nella riga del titolo)
- Modify: `addons/ai/provenienza.py` (`calcola`: chiave `riservata: bool` dalla conversazione del turno)
- Modify: `addons/ai/templates/ai/_provenienza.html` (chip con icona `#icon-lock` e la stessa etichetta)
- Test: `addons/ai/tests/test_riservatezza_pagine.py` (nuovo)

**Interfaces:**
- Consumes: `segna` (Task 2).
- Produces: URL `ai:riservata` (solo POST, solo le proprie chat via `_mie(request)`); `provenienza["riservata"]`.

Comportamento: il pulsante "Rendi riservata" compare solo se la chat non lo è già e non è in sola lettura. Il POST chiama `segna(c, "segnata dall'utente")` e torna a `ai:conversazione`. Non esiste l'operazione inversa. L'etichetta mostra il motivo nel `title`.

- [ ] **Step 1: Test**
  - `test_rendi_riservata`: POST → `riservata` vera con motivo `segnata dall'utente`; un GET dà 405; la chat di un altro utente dà 404.
  - `test_etichetta_in_chat`: la pagina della chat riservata contiene `Riservata · solo modelli locali` e non contiene il pulsante.
  - `test_provenienza_riservata`: un turno completato in chat riservata ha `provenienza["riservata"] is True`, e la chip compare in `_messaggi.html`.
- [ ] **Step 2: Esegui e verifica che falliscano.**
- [ ] **Step 3: Implementa vista, URL, template e provenienza.**
- [ ] **Step 4: Esegui e verifica che passino.**
- [ ] **Step 5: Commit** `feat(ai): rendere riservata una chat e vederlo in chat e nella provenienza`

### Task 6: Il connettore verso le chat esterne non restituisce dati riservati

**Files:**
- Modify: `addons/connettore_ai/catalogo.py` (`chiama`, righe 178-209; `_solo_app`, righe 124-132)
- Modify: `addons/connettore_ai/__manifest__.py` (versione `1.2.0`)
- Test: `addons/connettore_ai/tests/test_riservatezza.py` (nuovo)

**Interfaces:**
- Consumes: `fonte_riservata`, `risultati_ammessi`, `app_riservate` (Task 2).
- Produces: nessuna interfaccia nuova.

Comportamento:
- prima di eseguire, `fonte_riservata(nome, argomenti, "", collegamento.azienda, strumento.app)` non vuoto → la chiamata è rifiutata con il testo `Fonte riservata: si consulta solo dentro adabox, con modelli locali.` e registrata in `Chiamata` con `esito` di rifiuto e motivo;
- dopo l'esecuzione, i risultati di `cerca_conoscenza` passano da `risultati_ammessi`;
- `elenco_viste` e `app_disponibili` non mostrano le app riservate.

- [ ] **Step 1: Test**
  - `test_vista_riservata_rifiutata`: `chiama(coll, "cerca_record", {"vista": "personale.dipendenti"})` → errore con il testo esatto, `Chiamata` registrata.
  - `test_misura_riservata_rifiutata`: una misura di app riservata → rifiutata (chiude la lacuna di `_fuori_dalle_app` sulle misure).
  - `test_documento_riservato_rifiutato`: `leggi_documento` di un documento in cartella riservata → rifiutato.
  - `test_conoscenza_filtrata`: i risultati da cartella riservata spariscono, gli altri restano.
  - `test_app_riservata_non_elencata`: `app_disponibili` non contiene l'app riservata.
- [ ] **Step 2: Esegui e verifica che falliscano.**
- [ ] **Step 3: Implementa.**
- [ ] **Step 4: Esegui e verifica che passino**, insieme ai test già esistenti di `addons/connettore_ai/tests`.
- [ ] **Step 5: Commit** `feat(connettore_ai): niente dati delle fonti riservate verso le chat esterne`

### Task 7: Documentazione, controllo completo, installazione

**Files:**
- Modify: `README.md`: nella sezione "Assistente AI → Fiducia (AI-5)", un punto "Fonti riservate", con cosa si segna, cosa succede, il blocco senza modello locale e i limiti del primo giro (aree di lavoro escluse; Analisi trattata come riservata se c'è almeno un'app riservata).

- [ ] **Step 1: Scrivi il paragrafo del README.**
- [ ] **Step 2: Controllo finale senza `--reuse-db`**: `addons/ai/tests`, `addons/documenti/tests`, `addons/connettore_ai/tests`. Atteso: nessun fallimento.
- [ ] **Step 3: Commit** `docs: fonti riservate di Ada`
- [ ] **Step 4: Con il consenso dell'utente**: unione su main, `docker exec adabox_hub_web python manage.py modulo aggiorna --tutti` (fa il backup), riavvio di web, worker e stream.
- [ ] **Step 5: Prova sull'istanza**: impostare `personale` come app riservata e chiedere ad Ada un dato del personale. Senza modello locale attivo deve comparire il messaggio di blocco; con Qwen3 4B acceso (provider "Ollama locale" oggi spento) deve rispondere il locale. Misurare il tempo.
