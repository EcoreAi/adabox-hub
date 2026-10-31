# Agate

Collega l'assistente AI di adabox-hub ad **Agate**, il livello di controllo per gli agenti AI.

- **Le modifiche dell'assistente passano dalle regole di Agate.** Quando un utente conferma una
  proposta dell'assistente (crea, modifica, elimina, bottone, azione...), prima di eseguirla adabox
  chiede ad Agate (`POST /v1/evaluate`, strumento `adabox.<nome>`). Agate risponde:
  - *consentita*: si esegue come sempre;
  - *da approvare*: la proposta resta in attesa con il link alla console di Agate, e si esegue da
    sola quando una persona approva (webhook firmato, oppure controllo ogni minuto);
  - *bloccata*: si chiude con il motivo delle regole;
  - *con un limite*: non si esegue, si chiede all'assistente di rifarla entro il limite.

  Tutto resta nel registro di Agate, con chi ha confermato.
- **I modelli possono passare dal proxy di Agate.** Un provider «Agate» compatibile OpenAI usa i
  nomi logici dei modelli scelti dall'azienda in Agate: le chiavi dei fornitori restano in Agate,
  i dati personali vengono mascherati lì, i costi si contano lì.

Modalità: **spento**; **osservazione** (Agate valuta e registra, adabox esegue comunque: per vedere
cosa cambierebbe prima di accendere); **attivo** (decide Agate; se Agate non risponde non si esegue
nulla).

## Installazione

```bash
python manage.py modulo installa agate --si      # dipende da "ai"
```

Il punto di aggancio è `ai.proposte.registra_guardia`: il modulo registra la sua guardia all'avvio.
Senza collegamento, o in modalità spento, l'assistente funziona come prima.

## Collegare Agate

1. In Agate: una chiave con gli scope `evaluate` e `llm` (pagina Chiavi della console) e, se si
   vogliono gli esiti subito, un webhook verso `https://<adabox>/agate/webhook/` con l'evento
   `approval.decided`.
2. In adabox, **Agate → Collegamento**: gateway, console, chiave, segreto del webhook, modalità.
   «Salva e prova» controlla la chiave leggendo i modelli.
3. Gli strumenti dell'assistente in Agate:

   ```bash
   python manage.py agate_strumenti --output strumenti.json             # qui
   manage.py agate_add_internal_tools <tenant> production strumenti.json   # in Agate (T127)
   ```

   Nascono disattivati: chi gestisce Agate li rivede, li attiva e scrive le regole (soglie,
   approvazioni). Gli strumenti `irreversible` (invii, emissioni, movimenti) in Agate chiedono
   sempre una persona, salvo una regola esplicita.
4. Facoltativo, **Usa Agate per i modelli**: crea il provider e i modelli; poi nei Profili
   dell'assistente si mette «Agate» nella catena dei compiti.

## Cosa non fa

- Non decide approvazioni: si decidono nella console di Agate.
- Non manda ad Agate le letture dell'assistente (non cambiano nulla).
- Non manda chiavi o password: gli argomenti delle proposte sono quelli che l'assistente ha
  preparato; Agate maschera i dati personali prima di salvarli e di mostrarli a chi approva.

## Limiti

- Gli strumenti registrati in Agate vanno riesportati quando cambiano (aggiornamenti dei moduli):
  in Agate una definizione cambiata torna disattivata.
- Una proposta in attesa scade in adabox dopo un giorno (regola dell'assistente): se l'approvazione
  in Agate arriva dopo, la proposta non si esegue e va rifatta.
- Il provider «Agate» non usa le funzioni proprie di Claude (ragionamento, cache del prefisso):
  passa dal formato OpenAI del proxy.
