# Immagini in chat: cloud con conferma o modello locale

Dentro un'immagine i dati personali non si mascherano. Per questo, in **/impostazioni/ → Immagini allegate verso i
modelli cloud**, ogni azienda ha tre scelte:

| Scelta | Che cosa succede |
|---|---|
| **Mai** | le immagini non vanno ai modelli cloud |
| **Con la conferma dell'utente** (predefinita) | allegando un'immagine compare un riquadro: «Invia comunque» o «Togli le immagini». Chi conferma e quando resta nella storia della chat (e nel log). La conferma vale per quelle immagini: se ne sceglie altre, si chiede di nuovo |
| **Sempre** | le immagini vanno al modello cloud senza domande |

Il 2026-11-06 le aziende che avevano acceso il vecchio interruttore sono passate a «Sempre», le altre a «Con la
conferma dell'utente».

## Con un modello locale che legge le immagini

Se c'è un modello **locale** con «legge le immagini» e l'immagine non può andare al cloud (scelta «Mai», oppure
«Conferma» senza conferma), succede questo:

1. il modello locale descrive l'immagine sui nostri server (testi compresi);
2. la descrizione prende il posto del file nella domanda, e resta nella conversazione;
3. il modello della chat, anche cloud, riceve solo quel testo, mascherato come il resto, e continua con i suoi
   strumenti e i dati del gestionale.

Con un modello locale il riquadro di conferma non compare: l'immagine non esce mai. Ada dice che la descrizione viene da
un modello piccolo, che può sbagliare i dettagli.

## Installazione (Ollama su CPU)

Nel `docker-compose.yml` dell'hub è il servizio `ollama`, nel profilo `visione`.

```bash
docker compose --profile visione up -d ollama
docker exec adabox_hub_ollama ollama pull qwen3.5:0.8b
```

Poi in **Assistente AI → Provider e chiavi**: tipo *Compatibile OpenAI*, URL `http://adabox_hub_ollama:11434/v1`, spunta
*locale*, senza chiave. In **Modelli**: `qwen3.5:0.8b` di quel provider, con *legge le immagini*. Non serve metterlo
nella catena della chat.

## Modelli provati il 2026-11-06 (8 core, senza GPU)

| Modello | Esito |
|---|---|
| `qwen3.5:0.8b` (1,3 GB) | **in uso**: descrizione corretta nel complesso, qualche parola letta male; 40-60 secondi per immagine, circa 600 MB di memoria |
| `gemma4:e2b` | non parte con Ollama 0.40.15 (errore noto: «Gemma4Assistant requires ctx_other») |
| `gemma4:e2b-it-qat` | si carica ma cade mentre legge l'immagine, dopo 5 minuti |

Da riprovare Gemma 4 E2B con le prossime versioni di Ollama. Il ragionamento di Qwen va spento (`reasoning_effort:
none`, lo fa il codice per i modelli locali): acceso, il modello usa tutti i token per ragionare e non risponde.

Un modello di embedding (per esempio EmbeddingGemma) non va bene: trasforma testo e immagini in numeri per la ricerca,
non scrive descrizioni.
