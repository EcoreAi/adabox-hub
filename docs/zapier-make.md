# Zapier, Make e n8n

Adabox si collega alle piattaforme di automazione con due cose che ha già, più gli abbonamenti ai webhook via API
(modulo **Connettori** dalla 1.5):

- **azioni e ricerche**: l'API `/api/v1/` (un endpoint per ogni vista: elenco, lettura, creazione, modifica, bottoni);
- **eventi istantanei**: i webhook firmati, che la piattaforma apre e chiude da sola (schema «REST hook»).

Da fare fuori da questo repository: l'app su Zapier (Platform) e l'app personalizzata su Make vanno create e pubblicate
con un account sviluppatore di ciascuna. Qui sotto c'è ciò che serve per costruirle; finora gli endpoint sono provati
solo con i test del modulo, non con Zapier o Make veri.

## Accesso

Un **token API** creato dal profilo dell'utente (`/profilo/`), mandato come `Authorization: Bearer <token>`. Deve valere
per il modulo `connettori` (oltre a quelli da leggere e scrivere) e non essere in sola lettura; l'utente deve poter
aggiungere ed eliminare webhook. Con più aziende, `X-Azienda: <id>` sceglie quale.

- Prova del collegamento: `GET /api/v1/me/` (utente, aziende, app visibili).

## Eventi istantanei

| Passo | Chiamata |
|---|---|
| Eventi disponibili (per il menu a tendina) | `GET /connettori/api/eventi/` → `{"eventi": [{"evento": "contatti.contatto.creato", "nome": "Contatto creato", "lista": "/api/v1/contatti/contatti/"}]}` |
| Abbonamento (il flusso si accende) | `POST /connettori/api/abbonamenti/` con `{"url": "<indirizzo della piattaforma>", "eventi": ["contatti.contatto.creato"], "nome": "…"}` → `201 {"id": 12, "eventi": […], "segreto": "…"}` |
| Disdetta (il flusso si spegne) | `DELETE /connettori/api/abbonamenti/12/` |
| Esempi per la prova del flusso | `GET` dell'indirizzo in `lista`, es. `/api/v1/contatti/contatti/?per_page=3` → `results` |

Gli eventi sono `<modulo>.<modello>.creato|aggiornato|eliminato`, solo per i record che chi ha creato il token può
vedere. L'indirizzo deve essere `https`. Ogni avviso è un `POST` JSON:

```json
{"id": "…", "evento": "contatti.contatto.creato", "azienda": 1, "creato": "2026-11-21T10:00:00+01:00", "dati": {"id": 7, "nome": "Rossi Srl"}}
```

`dati` ha gli stessi campi dell'API; per `eliminato` solo `{"id": …}`. L'intestazione `X-Adabox-Firma: t=<istante>,v1=<hmac>`
è l'HMAC-SHA256 di `<istante>.<corpo>` con il `segreto` restituito all'abbonamento: verificarla è facoltativo ma consigliato.
Una risposta diversa da 2xx si ritenta fino a 5 volte; una risposta **410** chiude subito l'abbonamento.

## Zapier

- Autenticazione «API Key»: campi indirizzo dell'istanza e token; test su `/api/v1/me/`.
- Trigger «REST Hook»: Subscribe = abbonamento con `bundle.targetUrl`, salvando `id`; Unsubscribe = disdetta con
  `bundle.subscribeData.id`; Perform = `[bundle.cleanedRequest.dati]`; Perform List = l'elenco dell'evento.
- Azioni: `POST /api/v1/<modulo>/<vista>/` (crea), `PATCH …/<id>/` (modifica), `POST …/<id>/azioni/<nome>/` (bottone).

## Make

- Connessione con chiave API (indirizzo e token), verificata su `/api/v1/me/`.
- Webhook «dedicato»: attach = abbonamento, detach = disdetta; il modulo «instant trigger» restituisce `dati`.
- Moduli di azione e ricerca sugli stessi endpoint dell'API.

## n8n

Non serve un'app: nodo «Webhook» (l'indirizzo si scrive a mano in Connettori → Webhook, o con l'abbonamento via API) e
nodo «HTTP Request» con il token per le azioni.
