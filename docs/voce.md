# Voce nella chat di Ada

Quattro funzioni:

- **Microfono**: l'utente detta, il testo arriva nel campo da rileggere prima di inviare (massimo 2 minuti).
- **Ascolta**: sotto ogni risposta, la legge ad alta voce. Tabelle e codice non si leggono: la voce dice che ci sono.
- **Risposta vocale**: l'icona dell'altoparlante nella casella, accanto al microfono; legge ogni nuova risposta. La scelta resta nel browser.
- **Parla con Ada** (`/ai/parla/`, l'icona delle onde accanto al microfono): una conversazione a voce a schermo intero,
  pensata per il telefono. Sul telefono la chat si apre già così (la prima volta nella sessione e dopo mezz'ora
  lontano); «Apri nella chat» o la X riportano alla chat scritta.

## Parla con Ada

- **Tocchi e parli**: la pagina capisce da sola quando hai finito (silenzio dopo la voce, *secondi di silenzio per
  chiudere la frase*, 1,3 di default). Se non parli entro 8 secondi si ferma. Sotto i 150 ms di voce non manda nulla:
  Whisper sul silenzio si inventa frasi.
- **Risposte brevi**: la domanda va al motore della chat con una nota «modalità voce» (poche frasi parlate, niente
  tabelle né elenchi lunghi, numeri come si dicono, conferma a voce prima di creare o modificare). Senza ricerca sul
  web, per rispondere prima.
- **La voce parte mentre la risposta si scrive**: il browser chiede l'audio una frase alla volta (la prima corta, due
  pezzi preparati in anticipo). Il server legge solo il testo della risposta del turno, indicato per posizione: non
  si può usare il servizio di lettura per altri testi. Codice e tabelle non si leggono; dopo 30 secondi di voce Ada si
  ferma e il resto è nella chat.
- **Turni**: finita la risposta riascolta per qualche secondo (*secondi di ascolto dopo la risposta*, 6 di default;
  0 = si tocca ogni volta). **Toccando mentre pensa o parla la interrompi**: la risposta si ferma anche sul server e
  nel turno dopo il modello sa fin dove l'avevi sentita.
- Lo schermo resta acceso mentre la conversazione è attiva; da ferma il microfono si spegne.
- Serve che ci siano sia la dettatura sia la lettura; la conversazione resta una chat normale, nella cronologia.

Limiti di questa prima versione: la trascrizione è quella locale (6-8 secondi a frase sulla CPU di oggi); non ci si
interrompe ancora con la voce, solo toccando.

Il microfono funziona solo su pagine **https** (o `localhost`): è una regola dei browser.

## Dove va l'audio, dove va il testo

| | Servizio | Che cosa esce dal server |
|---|---|---|
| Dettatura | Whisper, sempre locale (Speaches) | niente |
| Lettura | Kokoro, locale (Speaches) | niente |
| Lettura | Cartesia, Mistral, Azure, Gemini | il testo della risposta, **dati personali compresi**, al fornitore |

Per questo la lettura con un fornitore cloud ha un consenso apposito per azienda, spento di default.

## Installazione del servizio locale (Speaches)

Speaches contiene faster-whisper (dettatura) e Kokoro (lettura), con API compatibile OpenAI. Nel `docker-compose.yml`
dell'hub è il servizio `speaches`, nel profilo `voce`: non parte se non lo si chiede.

```bash
# modelli: cartella scrivibile dal container (gira come uid 1000)
mkdir -p volumes/speaches
# avvio
docker compose --profile voce up -d speaches
# download dei modelli, una volta (il servizio gira con HF_HUB_OFFLINE=1: per scaricare, toglilo e riavvia)
docker exec adabox_hub_speaches curl -s -X POST http://localhost:8000/v1/models/Systran/faster-whisper-small
docker exec adabox_hub_speaches curl -s -X POST http://localhost:8000/v1/models/speaches-ai/Kokoro-82M-v1.0-ONNX
```

Sul server di sviluppo i modelli sono stati copiati da `/opt/adabox/volumes/speaches` (2,4 GB).

Speaches non ha autenticazione: non va pubblicato. Per le istanze dei clienti conviene un solo Speaches condiviso,
raggiunto sulla rete Docker come gli altri servizi AI (vedi `deploy/compose.servizi-adabox.yml`).

**Modello Whisper**: `Systran/faster-whisper-small` (predefinito) trascrive bene l'italiano e risponde in pochi secondi
su CPU. `faster-whisper-large-v3-turbo` su questo server (8 core, senza GPU) fa cadere il servizio: non usarlo senza GPU
o più memoria.

**Tempi su CPU (8 core)**: dettatura di una frase 6-8 secondi; Kokoro circa 4 secondi per 180 caratteri. La prima parte
di ogni risposta è corta (160 caratteri) per far partire la voce subito; le altre si preparano mentre si ascolta.

## Configurazione

1. **/impostazioni/** (sezione Assistente AI)
   - *URL del servizio vocale locale*: `http://adabox_hub_speaches:8000`
   - *Modello Whisper per la dettatura*: lascia quello predefinito
   - per ogni azienda: *Voce nella chat* (spenta di default) e, solo se serve, *Lettura delle risposte con un fornitore cloud*
   - per ogni azienda, per «Parla con Ada»: *Sul telefono la chat si apre con «Parla con Ada»* (accesa), *secondi di
     silenzio per chiudere la frase* (1,3), *secondi di ascolto dopo la risposta* (6)
2. **Assistente AI → Voce**: aggiungi il servizio di lettura e usa «Prova il servizio» (legge una frase in italiano e una
   in inglese). Con l'azienda vuota vale per tutte; un servizio di un'azienda ha la precedenza. Si usa il primo attivo
   ammesso: Kokoro se c'è l'URL locale, un cloud solo con il consenso dell'azienda.

| Servizio | Serve | Modello consigliato | Voce italiana / inglese consigliata |
|---|---|---|---|
| Kokoro | URL locale | `speaches-ai/Kokoro-82M-v1.0-ONNX` | `if_sara` (o `im_nicola`) / `af_heart` |
| Cartesia | chiave, ID delle due voci dalla libreria Cartesia | `sonic-3.6` | da scegliere |
| Mistral | chiave | `voxtral-mini-tts-3-0` | `voice_482` (Lorenzo) / `gb_jane_neutral` |
| Azure AI Speech | chiave e regione (es. `westeurope`) | — | `it-IT-IsabellaNeural` / `en-US-JennyNeural` |
| Google Gemini TTS | chiave | `gemini-3.1-flash-tts-preview` | `Kore` (multilingua) |

Modelli e voci si cambiano dal servizio senza toccare il codice. I nomi dei modelli cloud cambiano spesso: se la prova
non riesce, controlla il nome sulla documentazione del fornitore.

La lingua della lettura si sceglie dal testo della risposta (italiano o inglese). L'audio di ogni parte resta in cache un
giorno: riascoltare una risposta non la fa pagare due volte. I costi dei fornitori di voce non entrano nel tetto di
spesa dell'assistente.
