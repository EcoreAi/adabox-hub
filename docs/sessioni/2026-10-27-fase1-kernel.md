# Sessione 2026-10-27 — fase 1 del kernel

Partecipanti: sviluppo2@ichnobyte.it con Claude (Claude Code, VS Code).
Piano eseguito: `docs/superpowers/plans/2026-10-27-adabox-hub-fase1-kernel.md`, task 1-14, un commit per task.
Remote: `git@github-adabox:EcoreAi/adabox-hub.git` (alias SSH del server con la chiave dell'account EcoreAi;
l'host `github.com` usa la deploy key di adaerp e non può scrivere qui).

## Stato a fine sessione

- Suite: tutti i test verdi, compreso l'end-to-end `addons/todo/tests/test_installazione.py` (`pytest -m "not slow"` lo salta).
- DB di sviluppo: migrato, `todo` installato con i dati demo, **nessun utente** (serve `createsuperuser`).
- Docker verificato: build, login 200 su :8096, SIGHUP via pidfile con riavvio dei worker.

## Scostamenti dal piano e dalla spec

1. Comando interno `modulo_applica` invece di `_modulo_applica`: Django non scopre i comandi che iniziano con `_`.
2. Le `ModelView` del kernel sono montate sotto `/core/` (come i moduli sotto `/<slug>/`): `/core/aziende/`, `/core/profili/`.
3. Migrazione `0003_azienda_iniziale` senza pk esplicito: su Postgres non farebbe avanzare la sequenza.
4. Il backup sqlite (API nativa) resta in attesa se la stessa connessione ha scritture non committate: succede solo nei
   test non transazionali, per questo `test_aggiorna` è `transaction=True`.
5. Messaggi di conferma neutri rispetto al genere ("Creazione completata: azienda «X»"); azioni di massa come bottoni
   con `formaction` (funzionano senza JS); eliminazione via HTMX con `HX-Redirect`.
6. La tabella resa da HTMX nasce con `is-revealed` (ui.js rivela solo le tabelle presenti al caricamento).
7. API: corpo JSON validato dalla `ModelForm` della vista, risposte `dict` (niente `create_schema`); Ninja 1.7 non ha il
   parametro `csrf`, il controllo lo fa `django_auth`.
8. Pagina Moduli: un modulo in `errore` non installato offre Installa (riprova); il comando scrive `== FINE ok|errore ==`
   prima di propagare l'errore e la pagina lo cerca nella coda del log.
9. Aggiunti dopo il piano, dalla spec: azienda predefinita in `/profilo/`; indicazione "dati presenti" per i moduli
   disinstallati senza `--elimina-dati` (dalle righe di `django_migrations`).

## Da fare

- Prova manuale nel browser (filtri dal vivo, modale, installa/disinstalla da `/moduli/` con `runserver`).
- Ogni `docker compose up` crea `staticfiles/` come root nella cartella del repo (comportamento ereditato dallo starter).
- Fase 2 (kernel completo: chatter, attività, allegati, sequenze, kanban, calendario, report PDF, worker e cron,
  impostazioni, import/export, Properties): serve una spec propria prima del piano.
