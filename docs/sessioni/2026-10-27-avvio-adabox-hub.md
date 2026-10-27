# Sessione 2026-10-27 — avvio di adabox-hub

Partecipanti: sviluppo2@ichnobyte.it con Claude (Claude Code, VS Code).
Repo: `/opt/adabox-hub`. Server condiviso con `/opt/adaerp` (Odoo 19, riferimento funzionale) e `/opt/django-template` (starter).

## Cosa è stato fatto

1. **Clone dello starter.** `/opt/django-template` clonato in `/opt/adabox-hub` seguendo il README dello starter (`git clone`, `rm -rf .git`, `git init` su `main`). La cartella `/opt` è di root: creata con `sudo install -d -o ubuntu -g ubuntu -m 771`.
2. **File Docker portati a mano**: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `deploy/nginx.conf` non sono committati nel template e il clone git non li porta. Rinominati: immagine `adabox_hub`, container `adabox_hub_web` e `adabox_hub_nginx`, porta host **8096** (8091 resta al template).
3. **Brand**: `THEME["brand"] = "Adabox Hub"`, `THEME["mark"] = "AH"`; titolo del README.
4. **Ambiente**: `.env` da `.env.example` con `SECRET_KEY` nuova (permessi 600), venv `.venv`, `requirements-dev.txt` installato, migrazioni applicate, `db.sqlite3` di sviluppo.
5. **Test**: due test dello starter avevano il brand "Progetto"/"PR" scritto a mano; ora leggono `settings.THEME` (`core/tests/test_pagine.py`, `theme/tests/test_admin.py`). Suite: 40 passed.
6. **Spec della fase 1** scritta e approvata: `docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md`.
7. **Piano di implementazione** scritto: `docs/superpowers/plans/2026-10-27-adabox-hub-fase1-kernel.md` (15 task, 56 passi).
8. **Primo commit** del repo con tutto quanto sopra (Task 0 del piano).

## La visione del prodotto (dalla discussione)

Non "Odoo dentro Django": un'applicazione **nuova e proprietaria**, costruita con Django sopra lo starter, che riproduce il modello di Odoo (piattaforma + app installabili) e le sue funzionalità, con installazione delle app dall'interfaccia come i plugin di WordPress. Si rivende per istanza: a ogni cliente un insieme diverso di app, e moduli custom in repo separati.

Nota di licenza: Odoo Community è LGPL-3, gli addon OCA sono AGPL/LGPL. Si riproducono funzionalità, flussi e UX; **non si copia** codice, template, CSS, icone o testi. I moduli custom di `/opt/adaerp` valgono come requisiti e casi di test già collaudati.

### Mappa Odoo → adabox-hub

| Odoo | adabox-hub (Django) |
|---|---|
| Moduli con manifest, depends, stati, pagina App | `addons/` con `__manifest__.py`, registro nel kernel, stati, pagina `/moduli/`, upload zip (fase 4) |
| ORM con `_inherit` | modelli di estensione OneToOne + sezioni registrate sul dettaglio del modello base; campi Properties JSON per i custom del cliente (fase 2) |
| Viste XML list/form/kanban/calendar/graph/pivot/search | classi `ModelView` in Python (stile `ModelAdmin`), rese dal kernel con il theme |
| Azioni e menu | manifest: menu per app, azioni = viste registrate |
| Gruppi, ACL, record rules | gruppi Django dal manifest, permessi per modello, filtri sul queryset per gruppo |
| Multi-azienda | `Azienda` nel kernel, `AziendaMixin`, selettore nella barra dell'app |
| Chatter, attività, allegati, sequenze, cron, parametri, report PDF | fase 2 del kernel |
| RPC `search_read/create/write/unlink` | API JSON generica per ogni `ModelView` con `api=True`, Django Ninja |
| Studio | campi Properties + override delle viste in DB (fase 6) |

### Scelte tecniche confermate

1. API Python in inglese come Django (`ModelView`, `list_display`), modelli, URL, testi e documentazione in italiano.
2. **Django Ninja** e non DRF: l'API la genera il kernel dalle `ModelView`, Ninja dà schemi Pydantic e Swagger senza altri pacchetti ed è più leggero; DRF resta valido se il team lo conosce meglio. L'API vive in un solo modulo (`core/api/modelli.py`): cambiare libreria non tocca le app.
3. Pagina Moduli nel frontend con il theme (`/moduli/`); l'admin Django mostra `Modulo` in sola lettura.
4. HTMX vendorizzato nel theme (server-side, niente SPA).
5. App di riferimento: `todo`.

Altre decisioni della spec: stato di installazione in `addons/installed.json` letto dai settings; installazione = backup, stato, migrazione in sottoprocesso, ricarica di gunicorn via pidfile (`SIGHUP`); Postgres in produzione; multi-azienda sì, multi-tenant no; `theme/` resta intatto e portabile.

### Fasi

1. Kernel minimo (questa spec e questo piano).
2. Kernel completo: chatter, attività, allegati, sequenze, kanban, calendario, grafico, report PDF, worker e cron, impostazioni, import/export, Properties.
3. Prime app: contatti, calendario, crm, helpdesk, progetti e timesheet.
4. Distribuzione: upload zip, script di pacchettizzazione, test di installazione vergine, firma dei pacchetti.
5. Gestionale: prodotti, vendite, magazzino, acquisti, fatturazione (SDI a parte), HR, spese.
6. Studio, documenti, discuss.

## Stato del repo a fine sessione

- Branch `main`, un commit, nessun remote.
- Suite: 40 test verdi (`pytest`).
- `addons/`, `core/registry/`, `core/viste/`, `core/api/` **non esistono ancora**: partono dal Task 1 del piano.
- Ambiente del server: `/opt` è di root (sudo per nuove cartelle); porte compose occupate 8090-8097, adabox-hub sulla 8096.

## Prossimi passi

1. Eseguire il piano dal Task 1 con il flusso subagent-driven (`superpowers:subagent-driven-development`), un commit per task.
2. Aggiungere il remote GitHub quando si decide dove ospitare il repo.
3. Spec della fase 2 a kernel finito.
