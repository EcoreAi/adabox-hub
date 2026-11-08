# Istanza di prova per chi integra

Un'istanza come quella di un cliente, ma con dati dimostrativi, per chi deve collegare un altro software ad adabox.

## Allestirla

1. Si crea una nuova istanza come per un cliente (vedi il README), con il suo database e il suo dominio.
2. Nel suo `.env` si aggiunge `SANDBOX=True`.
3. Si lancia `python manage.py sandbox prepara --email chi@integra.it`.
   - Il comando genera i dati demo, crea l'utente «integrazione» con il ruolo di responsabile su tutti i moduli e un token API valido 90 giorni (`--giorni` per cambiarlo).
   - Il token si vede solo in quel momento: va mandato a chi integra.
4. `python manage.py sandbox azzera` rimette i dati demo da capo; il token resta valido.

Il comando rifiuta di girare se `SANDBOX` non è attivo: i dati demo non devono mai finire in un'istanza con dati veri.

## Cosa cambia in sandbox

- Ogni pagina mostra la striscia «Ambiente di prova».
- Le email non partono: finiscono nel log del servizio.
- Le fatture elettroniche vanno sempre al simulatore dello SDI, qualunque canale sia impostato.
- I webhook in uscita partono davvero, perché servono a provare gli endpoint di chi integra.
- L'assistente AI funziona come in produzione e ha gli stessi costi.

## Cosa dare a chi integra

- l'indirizzo della documentazione: `/api/v1/docs`, con lo schema in `/api/v1/openapi.json`;
- il client Python: `/api/v1/sdk/python/`, un solo file che usa solo la libreria standard;
- il token, insieme al limite di richieste (`API_LIMITE`, di default 120 al minuto).
