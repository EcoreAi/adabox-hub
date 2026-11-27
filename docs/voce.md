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
- **Modello**: con un profilo di compito *Parla con Ada (conversazione a voce)* in Assistente AI → Profili, i turni a
  voce usano la sua catena (conviene un modello veloce e regolare, es. Claude Haiku, e un tetto ai token di 1000-2000);
  senza, vale il profilo della chat con «Automatico». I turni a voce contano comunque come chat (licenza, cruscotto).
- **Dati senza fonti**: se la risposta contiene cifre (orari, importi, numeri) che non vengono dalla domanda, dal
  contesto o da uno strumento, e nel turno non è stato letto nessun dato, il motore chiede al modello di rifarla una
  volta (leggendo i dati o dicendo che non li ha); se resta senza fonti, la voce aggiunge «non ho trovato questi dati
  negli strumenti, verificali». La pagina non legge una risposta finché non sa se poggia su dati letti, così una
  risposta scartata non si sente. Sotto i sottotitoli: «Verificata · Calendario» o l'avviso.
- **Cifre nel testo, parole nella voce**: Ada scrive 13:30 e 1.250 € (così la guardia sui numeri le controlla), la
  lettura le pronuncia («13 e 30», «1250 euro»); le emoji non si leggono.
- **Strumenti a voce**: 18 su 39, quelli utili al telefono (agenda, record, totali, conoscenza, documenti,
  comunicazioni, proposte di modifica, ricorda, previsioni); fuori grafici, tabelle, Analisi, documenti lunghi,
  pianificazioni, agenti ed eliminazioni (`parla.STRUMENTI_VOCE`). Meno token per passo, circa il 40% di attesa in meno.
- **Frasi d'attesa**: quando parte il primo strumento che legge dati, Ada dice «Guardo il calendario.», «Controllo nei
  dati.», «Cerco nei documenti.»… (Kokoro le legge una volta, poi in cache; la pagina le scarica al primo tocco).
- **Modello consigliato** (misurato il 2026-11-16): Mistral Medium 3.5, europeo, 0,6-1,1 s alla prima parola o allo
  strumento, nessun dato inventato nelle prove; Mistral Small inventava appuntamenti, Large è 2-7 volte più lento.
- **Ada apre lei la conversazione** (`ai/apertura.py`): quando ha qualcosa da dire la frase è già scritta nei
  sottotitoli e al primo tocco la dice a voce, poi ascolta (toccando di nuovo la si interrompe). Prima di un tocco un
  browser non lascia suonare nulla, per questo non parla da sola. Dice una cosa sola, la più utile in quel momento:
  - *la prima volta nella giornata*: il saluto per l'ora («Buongiorno», «Buon pomeriggio», «Buonasera») e gli
    appuntamenti che restano oggi («Oggi hai 3 appuntamenti, il primo alle 10:00: «…». Vuoi sapere cosa hai in agenda
    per oggi?»); senza appuntamenti le notifiche non lette; senza niente «Come posso aiutarti?»;
  - *tornando dopo almeno 10 minuti*, nell'ordine: l'appuntamento che comincia entro un'ora («Tra 20 minuti, alle
    15:00, hai «…»»), la modifica preparata da Ada che aspetta ancora la conferma (si conferma nella chat: «Chiudi»
    porta lì), la conversazione a voce di prima da riprendere (almeno due domande; a un «sì» si continua in quella);
  - *tornando entro 10 minuti*, o se non c'è niente di nuovo: non dice nulla, ascolta e basta.

  Ogni cosa si dice una volta sola: il saluto una volta al giorno, ogni appuntamento, modifica e conversazione una
  volta. Un'apertura mai sentita (pagina aperta e richiusa senza toccare) non conta. La frase la compone il server dai
  dati, non il modello: è pronta subito, non costa, e orari e numeri non si possono inventare. Gli appuntamenti sono
  quelli dello strumento dell'agenda, gli stessi che Ada elenca se dici di sì. Con la voce spenta la frase resta
  scritta; dentro una conversazione già aperta o limitata a un'app non c'è. Le app riservate (calendario,
  comunicazioni) e le chat riservate non entrano nell'apertura. Le aperture restano due giorni, poi si cancellano.
  Per le demo: `/ai/parla/?da_capo=1` dimentica quelle già dette e Ada saluta come la prima volta.
- **Memoria della giornata**: una conversazione a voce nuova riceve come nota la frase d'apertura (così un «sì» fa ciò
  che Ada ha proposto) e le conversazioni a voce di oggi, al massimo tre, con l'ultima domanda e l'ultima risposta: «come
  dicevamo prima» funziona anche in una conversazione nuova. Le chat riservate non ci entrano.
- Ada chiama l'utente per nome; a Mistral vanno come parole da favorire «Ada», il marchio, l'azienda e nome e cognome
  dell'utente (senza, «Ada, quali…» diventava «Ha da quali…»).
- Serve che ci siano sia la dettatura sia la lettura; la conversazione resta una chat normale, nella cronologia.

Limiti di questa prima versione: con il Whisper locale la trascrizione impiega 6-8 secondi a frase (con la
trascrizione in cloud circa uno); non ci si interrompe ancora con la voce, solo toccando.

Il microfono funziona solo su pagine **https** (o `localhost`): è una regola dei browser.

## Dove va l'audio, dove va il testo

| | Servizio | Che cosa esce dal server |
|---|---|---|
| Dettatura | Whisper locale (Speaches) | niente |
| Dettatura | Mistral Voxtral o OVH Whisper (con il consenso) | **l'audio** di chi parla, al fornitore |
| Lettura | Kokoro, locale (Speaches) | niente |
| Lettura | Cartesia, Mistral, Azure, Gemini | il testo della risposta, **dati personali compresi**, al fornitore |

Per questo la lettura e la trascrizione con un fornitore cloud hanno ciascuna un consenso apposito per azienda,
spento di default.

## Trascrizione in cloud

Il Whisper locale impiega 6-8 secondi a frase sulla CPU del server; in cloud circa un secondo. Per usarla:

1. **Assistente AI → Voce → Nuovo**: *uso* «Trascrizione del parlato», *tipo* **Mistral (Voxtral)** (modello
   `voxtral-mini-latest`) oppure **OVH AI Endpoints (Whisper)** (`whisper-large-v3-turbo`), la chiave API. «Prova il
   servizio» manda un secondo di silenzio: dice se chiave e modello vanno, senza la voce di nessuno.
2. **Impostazioni → Assistente AI**, per l'azienda: *Trascrizione del parlato con un fornitore cloud*.

Vale per il microfono della chat e per «Parla con Ada». Se il fornitore non risponde si usa il Whisper locale (se c'è
l'URL di Speaches). La stessa chiave Mistral può servire anche per la lettura: è un secondo servizio, con uso «Lettura».

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
giorno: riascoltare una risposta non la fa pagare due volte.

## Costi della voce cloud

Un servizio vocale cloud può avere un **prezzo** (lo imposta il Global Admin, nella scheda del servizio):

- lettura: dollari per milione di caratteri letti;
- trascrizione: dollari per minuto di audio (i secondi li dice il fornitore; se non li dice si stimano dalla dimensione).

Con il prezzo, ogni chiamata vera al servizio (non quelle servite dalla cache) entra nei **Consumi**: una riga al giorno
per persona, azienda e servizio, con i caratteri o i secondi e il costo (`voce_lettura`, `voce_trascrizione`). Quel
costo conta nel **tetto di spesa mensile** dell'azienda come quello dei modelli: a tetto raggiunto anche la voce si
ferma. Senza prezzo (la chiave è del cliente) e per Kokoro in locale non si segna nulla.

La **quota della voce** sta nella licenza (`quota_voce`, dollari al mese per tutta l'istanza; dal portale di rivendita è
il campo «quota della voce cloud» del piano o dell'istanza, e vale con qualunque formula dell'assistente). Superata la
quota la voce **non si ferma**: il di più si fattura a parte. Lo dicono la pagina della licenza, la chat e «Parla con
Ada» (dall'80% della quota), e un'email agli amministratori dell'assistente all'80% e al superamento, una volta al
mese ciascuna. Il portale riceve con i consumi del mese quanta parte del costo è voce e calcola il di più da fatturare
(cambio e ricarico dell'assistente).

Il campo **«compresi al mese nel piano del fornitore»** (caratteri per la lettura, minuti per la trascrizione) riguarda
invece i costi di chi fornisce la voce: all'80% arriva un'email al Global Admin, prima che il fornitore applichi il suo
sovrapprezzo. La lista dei servizi mostra quanto se n'è usato nel mese.

Oltre ai costi c'è un limite di richieste per persona (200 ogni dieci minuti tra letture e trascrizioni), contro gli
abusi.
