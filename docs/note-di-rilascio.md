# Note di rilascio

Ciò che chi aggiorna un'istanza deve sapere: cambi di comportamento, azioni da fare, migrazioni. Il dettaglio è nei
commit; qui solo ciò che si vede o che chiede un intervento.

## 2026-11-26

- **App delle altre aziende nella barra in alto** (Kernel, nessuna migrazione).
  - Chi lavora in più aziende trova in fondo alla barra, prima di «Altre», le app che avrebbe in barra nelle altre sue
    aziende e non in quella corrente (es. le app riservate a un'azienda), con il nome dell'azienda di arrivo in piccolo.
    Un clic rende corrente quell'azienda e apre l'app, con il messaggio «Azienda corrente: …»; il cambio resta un POST.
    Aperte in una nuova scheda (o senza script) rispondono la pagina «Passa a …» di sempre. Sul telefono stanno nel
    menu e la ricerca le trova; Invio sulla prima trovata fa lo stesso clic. Le app nascoste dalla scelta della barra e
    le schede della Dashboard non compaiono. Chi ha una sola azienda vede l'header di prima.
  - **Un tema con un suo `_header.html`** include `theme/partials/_altre_aziende.html` (in fondo alle voci) e
    `theme/partials/_cambia_azienda.html` (una volta): senza, le voci non ci sono. Il meccanismo del cambio
    (`data-cambia-azienda="<pk>"` su un link, `theme/cambia_azienda.js`) vale per ogni pagina: `docs/guida-moduli.md`.
  - Dopo l'aggiornamento: `collectstatic` (script nuovo `theme/cambia_azienda.js`).
- **Chat: le aree di lavoro di tutte le aziende, con il cambio di azienda** — AI 1.60.0 (nessuna migrazione).
  - Chi lavora in più aziende trova nella colonna «Aree di lavoro» le aree di tutte le sue aziende, raggruppate per
    azienda: prima la corrente (aperta), poi le altre per nome (chiuse), ognuna con la sua area personale. Un clic su
    un'area di un'altra azienda rende corrente quell'azienda e apre l'area. Un'area resta della sua azienda.
  - Lo stesso clic vale per le chat di un'altra azienda in Cronologia, nella ricerca e nei Preferiti (chat e documenti),
    che mostrano in piccolo il nome dell'azienda di ogni chat; il nome dell'azienda compare anche accanto al nome
    dell'area, nella pagina dell'area e sopra la casella.
  - **Correzione**: una chat (o un'area) di un'altra azienda aperta da un link, un segnalibro o una notifica non si apre
    più con l'azienda corrente sbagliata: risponde «Questa chat è dell'azienda X» con il bottone «Passa a X». Scrivere,
    rigenerare, modificare un messaggio, spostare la chat o parlare con Ada in una chat di un'altra azienda (per
    esempio da una scheda rimasta aperta dopo un cambio) è rifiutato con «Questa chat è dell'azienda X: passa a X per
    continuare», invece di far rispondere Ada con i dati dell'altra azienda. Le chat vecchie senza area restano come
    prima. Chi ha una sola azienda non vede differenze.
  - Dopo l'aggiornamento: `collectstatic` (`ai/chat.css` cambiato).
- **Aziende dei nuovi utenti** — Kernel (senza migrazioni, versione invariata).
  - Con più di un'azienda attiva il modulo «Nuovo utente» parte senza aziende spuntate e senza sceglierne almeno una non
    salva («Scegli almeno un'azienda.»). Con una sola azienda attiva resta com'era: spuntata, nessun obbligo.
  - Nuova impostazione `AZIENDE_NUOVI_UTENTI` (`tutte`, default, o `nessuna`) per gli utenti creati fuori dal modulo
    (admin, API, codice): con `nessuna` e più aziende attive non hanno aziende finché qualcuno non le assegna; i
    superutenti le hanno sempre tutte.
- **«Le mie previsioni»** — Previsioni 1.1.0 (migrazione `previsioni.0006`).
  - Nella pagina Previsioni, dopo Vendite e Magazzino, c'è l'elenco delle previsioni che hai fatto: quelle chieste ad Ada
    in chat e quelle di Analisi, dalla più recente, con titolo, origine, argomento (l'app da cui viene la serie), tipo
    (andamento o classifica), data ed etichetta. Ogni fonte c'è solo se Assistente AI o Analisi sono accesi per
    l'azienda; le previsioni di Analisi non hanno un'azienda, quindi si vedono in tutte le aziende dell'utente.
  - Cerca (titolo, etichetta, argomento) e filtri per argomento, tipo, origine ed etichetta; «Rinomina» cambia il
    titolo anche in chat e in Analisi; «Etichetta» è un nome libero scelto dall'utente per ritrovarle.
  - Nuova tabella delle etichette, senza chiavi verso Assistente AI e Analisi.
- **Previsioni a schede** — Previsioni 1.1.1: la pagina ha una scheda per sezione (Vendite, Magazzino, Le mie previsioni) al
  posto di un'unica pagina lunga; «Aggiorna» torna alla stessa scheda e la nota sul bottone «Nuova previsione» compare solo
  quando il bottone manca.

## 2026-11-25

- **Modulo Previsioni, in licenza** — Previsioni 1.0.0 (migrazioni `previsioni.0001`-`0005`), AI 1.59.0, Analisi 1.16.0,
  Kernel 1.14.1 (AI, Analisi e Kernel senza migrazioni).
  - Il motore di previsione passa da `addons/ai/specialisti.py` al modulo `previsioni` (nessuna dipendenza). Si
    prevede solo con il modulo installato, acceso, in licenza (e, se è riservato ad alcune aziende, per quelle) e con
    l'URL del servizio configurato.
  - **Chi usava le previsioni attraverso l'assistente le perde finché non ha il modulo**: lo strumento «previsione»
    di Ada ora è del modulo, e i grafici di Analisi di tipo Previsione già salvati mostrano «Serve il modulo
    Previsioni.».
  - L'URL del servizio passa da `ai.url_forecast` a `previsioni.url_servizio`: la migrazione `previsioni.0002` lo copia
    da sola (se quello del modulo è vuoto). Si cambia in Impostazioni, sezione Previsioni. La chiave API facoltativa,
    conservata cifrata, si imposta nella pagina «Servizio di previsione» (menu del profilo), che apre solo il Global
    Admin.
  - Ada: lo strumento «previsione» ha «raggruppa per» e «primi N» (tabella dei primi N gruppi, in una sola chiamata al
    servizio). Anche in Analisi il tipo Previsione ha «Raggruppa per» e «Primi» e si vede come tabella.
  - Magazzino: ogni notte alle 02:00 (pianificazione «Previsioni della notte») e con «Aggiorna» (lavoro in background)
    si calcola, per articolo e magazzino, la data di esaurimento con la fascia 10-90 %, la data di riordino dalle
    soglie che già ci sono (scorta del magazzino, poi la regola di riordino di Acquisti, poi la scorta minima del
    prodotto) e la quantità suggerita. Si vedono nella vista «Articoli in esaurimento» e in un riquadro nella scheda
    del prodotto, con il permesso delle previsioni e quello delle giacenze di Magazzino (`magazzino.view_movimento`).
    Se il calcolo non riesce restano le ultime previsioni, con «Previsioni non aggiornate dal …» (o «Previsioni non
    calcolate» se non ce ne sono ancora) e il motivo.
  - Vendite: previsioni pronte (ricavi per mese, dalle fatture con Fatturazione, altrimenti dagli ordini confermati;
    primi 10 prodotti, nell'unità del prodotto; primi 10 clienti), salvate ogni notte. Chi ha regole di riga, campi
    nascosti o filtri di riga dei moduli le vede calcolate al momento con i propri permessi.
  - Tempi del servizio: le chiamate fatte mentre una pagina aspetta (calcolo al momento delle previsioni pronte, riga
    del prodotto, Analisi, Ada) si fermano dopo 25 secondi, sotto i 60 dopo cui gunicorn chiude il worker; quelle dei
    lavori in background (la notte, «Aggiorna») aspettano fino a 120 secondi. Un calcolo al momento non riuscito si
    riprova dopo un minuto.
  - La pagina «Previsioni» (una sezione per app) e i widget della dashboard. Accanto a ogni previsione (pagina,
    scheda del prodotto, Analisi, chat) c'è l'indicazione «modello … · licenza Modified MIT di Mistral AI».
  - `core.misure.storia(..., scelti=None)` accetta l'elenco dei gruppi da prevedere (correzione del Kernel).
  - **Licenza dei pesi di Timestral**: sono sotto «Modified MIT License» di Mistral AI. L'uso commerciale è ammesso
    tenendo l'avviso «2026 - Mistral AI» e il testo della licenza in ogni copia, ma non per aziende (o gruppi) oltre
    20 milioni di dollari di ricavi al mese, a cui serve una licenza commerciale di Mistral. Da fare: mettere il file
    LICENSE accanto ai pesi nel servizio di previsione (il repository non ne distribuisce: `deploy/` contiene solo un
    esempio di rete verso il servizio).
  - Dopo l'aggiornamento: `modulo installa previsioni` (con la licenza che lo comprende), poi `collectstatic`, quindi
    impostare l'URL del servizio se non è stato copiato. Un'istanza senza licenza del modulo non ha più le previsioni.

## 2026-11-24

- **Cercare tra le applicazioni** (nessuna migrazione).
  - In cima alla pagina Applicazioni una ricerca per parole (nome, categoria, descrizione, funzioni; con più parole
    servono tutte) e i filtri per stato (Attive, Non attive, Da acquistare) e per categoria, su tutte le sezioni.
    Prima si cercava solo tra le app da acquistare. I filtri restano nell'indirizzo della pagina.

- **«Le mie dashboard»** — Analisi 1.15.0 (nessuna migrazione).
  - Le pagine che una persona crea non sono più una scheda ciascuna (fino a sei, poi in «Altre schede»): stanno tutte
    nel menu a tendina «Le mie dashboard», subito dopo Dashboard e Statistiche, nel loro ordine. Quelle condivise da
    altri hanno una sezione loro, «Condivise con te», con il nome di chi le ha condivise. Aperta una di queste pagine,
    la voce del menu è evidenziata. In «Altre schede» restano le app.

- **Il nome del prodotto senza la versione** (nessuna migrazione).
  - Il nome predefinito è «Adabox», non più «Adabox v3»: nell'intestazione, con la barra piena di voci, «v3» andava a
    capo. La versione sta in piccolo nel piè di pagina e nella pagina di accesso (`THEME_VERSION`, predefinita «v3»,
    al posto di «0.1.0»). Cambia anche il nome in email, PDF, inviti di calendario e nell'app installata; chi vuole
    il nome di prima imposta `THEME_BRAND="Adabox v3"`. Le istanze con un loro `THEME_BRAND` non cambiano.
  - Nell'intestazione il nome non va più a capo né si stringe (un nome molto lungo si tronca con i puntini): con la
    barra piena si stringe prima la ricerca, poi si tronca il nome della persona. Un tema con un suo `_header.html`
    mette la classe `ui-logo-nome` sul nome per avere il troncamento.

## 2026-11-23

- **App di una sola azienda** — Kernel 1.14.0 (migrazione `core.0044`: aziende di un modulo).
  - Nella scheda di un'app, sezione **Aziende** (con almeno due aziende attive): «per tutte», come prima, o «solo per
    queste». Con un'altra azienda corrente l'app sparisce da barra, launcher, ricerca e viste di Ada, e le sue pagine
    propongono di passare all'azienda giusta (anche ai superuser).
  - Chi chiama `modules.app_visibili(user)` senza azienda prende quella corrente, che il middleware dell'azienda mette
    sull'utente; fuori da una richiesta (worker) non si limita nulla.

- **Discuss e Flotta dichiarano Contatti tra le dipendenze** — Discuss 1.13.2, Flotta 1.0.1 (nessuna migrazione).
  - Hanno un collegamento a `contatti.Contatto` (domande dal portale, fornitore del contratto del veicolo): su
    un'istanza senza Contatti l'avvio cadeva. Ora aggiornarli installa prima Contatti, se manca (e se la licenza lo
    comprende).

- **Tema per azienda** — Kernel 1.13.0 (migrazioni `theme.0003`: nome del prodotto e template del tema; `core.0043`:
  tema dell'azienda).
  - Nella scheda dell'azienda, sezione **Aspetto**, si sceglie il tema; vuoto, il tema attivo come prima.
  - Nel tema, **Nome del prodotto** (titolo delle pagine, email spedite per conto dell'azienda) e **Template** (il
    pacchetto di un modulo attivo, es. `zenpark.tema`: i suoi template vengono prima degli altri, solo per le aziende
    con quel tema).
  - Le pagine pubbliche (preventivo online, pagamenti, prenotazioni, Helpdesk, pagina del fornitore) usano il tema
    dell'azienda del documento. La favicon segue il tema; icone e nome dell'app installata restano dell'istanza.
  - Le conferme, gli annullamenti e i promemoria delle prenotazioni del Calendario partono dal mittente dell'azienda.
  - Un modulo che porta la sua grafica crea il suo tema dall'hook `post_install` con `theme.tema_del_modulo(...)`
    (template, foglio CSS e logo dai suoi statici); `theme.modulo_del_tema(azienda)` dice di quale modulo sono i
    template del tema di un'azienda.
  - Configurazione dei template: `APP_DIRS` lascia il posto a un elenco di loader, il primo è quello del tema
    (`theme.template_tema.Loader`), con il suo middleware dopo quello dell'azienda corrente. Un'istanza con un
    `settings.py` proprio deve riportare le due modifiche.

- **Estrazioni con output strutturato e viste che ne sostituiscono altre per Ada** — Kernel 1.12.0, AI 1.58.0
  (nessuna migrazione).
  - `ai.gateway.esegui(..., formato={"nome": ..., "schema": {...}})`: la risposta è JSON valido per lo schema
    (`output_config.format` per Anthropic, `response_format` per gli endpoint compatibili OpenAI e Mistral). È il modo
    di estrarre dati da un documento: un `tool_choice` obbligato su Opus e Sonnet 5.5 darebbe errore 400.
  - `ai_al_posto_di = ["vendite.ordini"]` su una `ModelView` che ne estende un'altra: Ada vede solo quella e i link
    aprono le sue pagine. Pagine, ricerca globale e API della vista sostituita non cambiano.

- **Mittente delle email per azienda** — Kernel 1.11.0 (migrazione `core.0042`: due campi dell'azienda).
  - Nella scheda dell'azienda, sezione **Email ai clienti**: nome e indirizzo del mittente. Le email spedite per conto
    dell'azienda partono da lì: i testi dei moduli (`modelli_email`: preventivo e risposte di Vendite, inviti del
    portale, Helpdesk, canoni) e le notifiche del chatter dei suoi record. Vuoti, resta `DEFAULT_FROM_EMAIL`; con il
    solo nome, quel nome sull'indirizzo dell'istanza.
  - Il dominio del nuovo indirizzo va autorizzato sul server di posta (SPF e DKIM), o le email finiscono nello spam.
  - Restano sul mittente dell'istanza le email interne (attività, esportazioni, report, recupero password).
  - `modelli_email.messaggio_da` accetta `from_email=` per un mittente diverso.

- **Librerie dei moduli e gruppo «documenti» nell'immagine** — Kernel 1.10.0 (nessuna migrazione). **Va ricostruita
  l'immagine** (`docker compose build`, o `deploy/Dockerfile.cliente` per i clienti).
  - L'immagine comprende il gruppo «documenti» per la scansione e la lettura di documenti: OpenCV, numpy, PDFium,
    codici a barre (zxing-cpp), `.xls` (xlwt), file Apple Numbers (numbers-parser), Tesseract con l'italiano. Circa
    500 MB in più; con `--build-arg DOCUMENTI=no` resta come prima.
  - Nuova voce del manifest `dipendenze` (`{"python": [...], "sistema": [...]}`): un modulo che chiede librerie assenti
    dall'immagine non si installa e non si aggiorna, con un messaggio che dice che cosa manca. Nessun effetto sui
    moduli che non la usano.

- **Dove si apre l'app installata** — Kernel 1.9.0 (migrazione `core.0041`: campo `apertura_app` del profilo).
  - Nel profilo, **Quando apri l'app**: In tasca (come prima), Parla con Ada o Chat con Ada. Vale per l'app installata
    sul telefono o sul computer; «In tasca» aperta a mano resta com'è. Se la pagina scelta non c'è (modulo AI non
    installato) o la persona non la può usare, l'app si apre su In tasca.
  - Tenendo premuta l'icona dell'app compaiono le scorciatoie Parla con Ada, Chat con Ada e In tasca, oltre a Da
    approvare e Le mie attività. Le app già installate prendono le scorciatoie nuove quando il browser aggiorna il
    manifest.

## 2026-11-20

- **Pagina Statistiche in due colonne** — Analisi 1.14.0, Vendite 1.11.1 (nessuna migrazione).
  - A sinistra le tue pagine in tessere (con «Nuova pagina» come ultima tessera) e le schede delle app come chip con
    il numero di grafici; sotto la **Libreria** in righe basse con ricerca, filtro Tutti · Indicatori · Grafici ·
    Previsioni e le prime 12 righe («Mostra tutti»). A destra Grafici delle app, Condivise con te e l'invito a
    chiedere ad Ada una dashboard. Sotto i 920 px una colonna sola.
  - Vendite: tolto il sinonimo «fatturato per prodotto» dal Venduto (viene dagli ordini, non dalle fatture).

- **Venduto per prodotto** — Vendite 1.11.0, AI 1.57.0, Analisi 1.13.0 (nessuna migrazione).
  - Due misure nuove: **Venduto** (importo) e **Quantità venduta**, dalle righe degli ordini confermati che contano
    nel totale (le opzionali solo se scelte); per prodotto, cliente, commerciale, mese, anno. Il totale del venduto
    coincide con l'ordinato. «I 10 prodotti più venduti» ora ha una risposta, con grafico cliccabile.
  - Nuova lista in sola lettura **Righe vendute** (/vendite/righe_vendute/): è quella che si apre dal clic sui grafici.
  - Ada: se un dato non si può calcolare lo dice subito, senza aprire i record uno per uno e senza classifiche o
    totali costruiti su una parte dei record.
  - La dashboard «Vendite» suggerita ad Ada comprende il venduto per prodotto.

- **Chat di Ada: link nella stessa finestra e Ferma al posto di Invia** — Kernel 1.8.0, AI 1.56.0.
  - Il link «Apri →» delle proposte confermate si apre nella stessa finestra; la pagina aperta mostra
    **← Torna alla chat** (solo per le proprie chat). Funziona anche il tasto Indietro del browser.
  - Mentre Ada risponde, il pulsante d'invio diventa **Ferma** (quadrato), nello stesso punto: sparisce la barra
    larga sotto i puntini.

- **Dashboard fatte da Ada** — Analisi 1.12.0, AI 1.56.0 (nessuna migrazione).
  - «Fammi una dashboard delle vendite»: Ada propone in una sola conferma una pagina nuova di Analisi con 2-8 pezzi
    (indicatori in testa, poi grafici e previsioni), calcolati prima di proporli. I grafici senza dati o sbagliati
    sono tolti e la conferma lo dice; un indicatore a zero resta. I grafici sulle misure partono da **Anno**.
  - Ada parte da quattro composizioni (Panoramica dell'azienda, Vendite, Fatturazione e incassi, Acquisti e scorte),
    solo con le misure dei moduli installati, e le adatta alla richiesta; per richieste diverse sceglie lei i pezzi.
  - Crea sempre una pagina nuova: per aggiungere a una pagina esistente resta il salvataggio di un grafico alla volta.
  - Nella scheda di conferma ogni pezzo ha una **casella**: togli la spunta a quelli che non vuoi e confermi gli altri.
    Se ne restano meno di 2 la scheda lo dice e resta da confermare.
  - La dashboard e «salva in Analisi» funzionano anche nelle chat limitate a un'app (pulsante **App**): Analisi
    raccoglie i numeri di tutte le app, quindi nella chat del CRM la dashboard può avere anche fatturato e scaduto.
  - I grafici sulle misure per cliente o fornitore mostrano i primi 10 più «Altro». Una dashboard con un pezzo di
    un'app riservata passa ai modelli locali come ogni altra lettura riservata.

- **Filtri sul grafico** — Kernel 1.7.0, AI 1.54.0, Analisi 1.10.0, Vendite 1.10.0 (nessuna migrazione; AI e Analisi
  chiedono il kernel 1.7).
  - Accanto ai pulsanti del periodo, **Filtra**: un menu per filtro con i valori presenti nei dati, dal più grande.
    La scelta compare come etichetta con la ×, il grafico si ricalcola lì dov'è e i clic sui record portano il filtro.
    Vale nei grafici della chat e sulle card di Analisi; solo per chi possiede il grafico. Il confronto con l'anno
    prima usa lo stesso filtro.
  - Misure aziendali: si filtrano per i loro raggruppamenti (fatturato: cliente; ordinato: cliente e, nuovo,
    **commerciale**). Grafici sugli elenchi: per i filtri dell'elenco che non sono date.
  - I filtri scelti si leggono accanto al titolo, anche nei grafici condivisi e nella pagina «Apri in grande».

- **Periodo sul grafico** — Kernel 1.6.0, AI 1.53.0, Analisi 1.9.0 (nessuna migrazione; AI e Analisi chiedono il
  kernel 1.6).
  - Sopra i grafici della chat e sulle card dei grafici salvati in Analisi: **Mese · Trimestre · Anno · Anno scorso**.
    Al tocco il grafico si ricalcola lì dov'è, e i clic sui record seguono il periodo. La scelta resta salvata; i
    pulsanti li vede solo chi possiede il grafico.
  - **Confronta** aggiunge lo stesso periodo un anno prima, accanto a ogni punto (non sulle torte). Il clic sulla
    serie dell'anno prima non apre nulla.
  - Solo dove c'è una data certa: misure aziendali con un periodo (fatturato, ordinato, acquistato…) e grafici
    raggruppati per data (questi hanno anche «Sempre»). Gli altri grafici non hanno i pulsanti.

## 2026-11-19

- **Grafici: l'elenco si apre nella stessa pagina** — Kernel 1.5.2, AI 1.52.0 (nessuna migrazione). Il clic su un
  punto di un grafico (chat, Analisi, dashboard, Chiedi ad Ada) e l'icona «Apri con i dati di oggi» aprono nella stessa
  pagina, non più in una scheda nuova: con Indietro si torna al grafico. Annulla la scheda nuova introdotta oggi.

- **Grafici: elenco sempre in una scheda nuova; niente grafici scritti come testo** — Kernel 1.5.1, AI 1.51.0
  (nessuna migrazione).
  - Il clic su un punto di un grafico apre l'elenco in una scheda nuova anche in Analisi, nelle dashboard e nel
    costruttore, come in chat: il grafico resta dov'era.
  - Se il modello scrive il grafico come testo (`<graph>{…}</graph>`, un blocco JSON o mermaid) invece di usare lo
    strumento, Ada gli chiede una volta di rifarlo con lo strumento grafico; se insiste, il markup si toglie e restano
    i numeri. Visto con Mistral Medium 3.5.

- **Grafici cliccabili** — Kernel 1.5.0, AI 1.50.0, Analisi 1.8.0 (nessuna migrazione; AI e Analisi chiedono il kernel 1.5).
  - In chat e nella pagina del grafico barre, linee e torta sono quelli di Analisi: il valore compare subito passando
    col mouse, e il clic su una barra, un punto o una fetta apre l'elenco dei record di quel gruppo in una scheda nuova.
    I grafici già presenti nelle chat diventano cliccabili dopo ↻. Le previsioni restano come prima.
  - I grafici sulle misure aziendali (fatturato per mese, da incassare per cliente…) sono cliccabili anche in Analisi,
    con i filtri della misura: il clic su un cliente del fatturato mostra le sue fatture emesse del periodo.
  - **Corretto**: in Analisi il clic su un grafico del fatturato per cliente apriva anche le bozze; nelle torte con più
    di 5 fette il clic poteva aprire la fetta sbagliata. Dove un link mostrerebbe altri record (fetta «Altro», campo
    che l'elenco non filtra) il punto non è cliccabile.

- **AI 1.49.0 — «Parla con Ada» apre lei la conversazione** (una migrazione: `modulo aggiorna ai`).
  - La prima volta nella giornata Ada saluta e parte dall'agenda («Oggi hai 3 appuntamenti, il primo alle 10:00… Vuoi
    sapere cosa hai in agenda per oggi?»); tornando dopo un po' ricorda l'appuntamento che comincia entro un'ora, la
    modifica rimasta in attesa di conferma o propone di riprendere la conversazione di prima; tornando dopo pochi
    minuti non dice nulla. Ogni cosa una volta sola.
  - La frase è scritta appena si apre la pagina e Ada la dice **al primo tocco** (prima un browser non lascia suonare
    nulla), poi ascolta. La compone il server dai dati, non il modello.
  - Una conversazione a voce nuova sa di che cosa si è parlato a voce nella giornata («come dicevamo prima»).
  - Per le demo: `/ai/parla/?da_capo=1` fa ripartire il saluto del giorno. Dettagli in `docs/voce.md`.

## 2026-11-17

- **Cerca ovunque trova grafici, pagine e menu** — Kernel 1.4.0, Analisi 1.7.0, AI 1.47.0 (nessuna migrazione).
  - «grafico vendite quest'anno» trova i grafici salvati e le pagine di Analisi che l'utente vede, e le voci di menu,
    anche con i sinonimi delle misure («vendite» trova «Fatturato»). Se nessun grafico corrisponde, «Chiedi ad Ada»
    apre una chat nuova con la domanda già scritta.
  - Grafici salvati: l'icona ↻ accanto al titolo ricalcola subito, con l'ora dei dati («dati delle 12:35»); prima
    era solo nel menu ⋯. In chat grafici e tabelle si aggiornano lì dove sono (↻), senza aprire un'altra scheda.
- **Misure aziendali** — Kernel 1.3.0, AI 1.46.0, Analisi 1.6.0, Fatturazione 1.7.0, Vendite 1.9.0, Acquisti 1.6.0,
  Magazzino 1.15.0, Calendario 1.2.0, Connettore AI 1.1.0 (nessuna migrazione; i moduli con le misure chiedono il
  kernel 1.3).
  - Fatturato, fatture emesse, da incassare, scaduto, incassato, ordinato, preventivi aperti, acquistato, prodotti sotto
    scorta e appuntamenti hanno una definizione fissa. Ada, dashboard, Analisi e chat esterne danno lo stesso numero.
    **Cambia il numero che Ada dava per il fatturato**: prima dipendeva dal modello (ordini confermati, fatture con
    le bozze, totale IVA inclusa), ora è sempre l'imponibile delle fatture emesse meno le note di credito.
  - Sotto la risposta il chip «numeri usati» con la definizione e il link ai record.
  - I «primi 5 clienti» e simili funzionano anche negli strumenti generici (`ordina`, `primi`), senza i tentativi
    a vuoto di prima.
  - Le dashboard della Fatturazione e del Magazzino usano le stesse misure: un ruolo che non vede l'imponibile ora
    legge «non disponibile» invece del numero.
  - `ai_eval`: numero esatto delle misure, passi, tempi e `--modello`; 18 domande d'oro nuove sulle aree da demo.
  - Chat: con «Larga» e «Piena» la risposta, i grafici e le tabelle si allargano con la colonna (prima restavano
    stretti a sinistra); in «Piena» il testo si ferma a circa 120 battute, i grafici a 420 px di altezza. Ada non
    lascia più nel testo segnaposto come `![grafico](artifact:44)`.

## 2026-11-16

- **AI 1.45.0 — affidabilità delle previsioni e chat più larga** (nessuna migrazione).
  - Sotto ogni previsione il chip «Affidabilità: alta / media / bassa», calcolato dal codice da tre misure: quanta
    storia c'è (solida da 24 periodi), quanto è largo l'intervallo 10-90 %, e l'errore sugli ultimi periodi già noti
    (la stessa previsione rifatta senza di loro). La card dice i motivi; Ada lo dice anche a parole.
  - La colonna della chat si allarga: Normale (760 px), Larga (1100 px), Piena, oppure trascinando la maniglia sul
    bordo (doppio clic: normale; frecce da tastiera). Il browser ricorda la scelta; il testo resta a una larghezza
    comoda, tabelle e grafici usano lo spazio. Sul telefono non cambia nulla.
- **AI 1.44.0 — risposte più affidabili** (nessuna migrazione).
  - Guardia sui numeri più precisa: non segnala più date a parole («16 novembre»), misure («15 pollici», «500 W»),
    aliquote IVA, valori dichiarati approssimati vicini al dato vero, e conta come fonti i dati letti prima nella stessa
    chat. Sui turni veri: da 40 a 16 numeri segnalati; restano quelli davvero senza fonte (calcoli a mente, conoscenza
    generale).
  - La guardia «dati senza fonti» vale anche per le attività pianificate (oltre che a voce), e confronta i valori e non
    il testo («48.250,50» = 48250.5 nei dati).
  - Istruzioni di Ada: niente calcoli a mente su righe e totali; la conoscenza generale si dichiara («da verificare»);
    a voce, ciò che si può fare solo in chat si dice.
  - Domande d'oro da 7 a 19, con trappole (cliente e contratto inesistenti, fatturato di domani, eliminazione in blocco,
    conoscenza generale): `manage.py ai_eval`.
- **AI 1.43.0, Calendario 1.1.3 — ciò che non si tace.** Uno strumento può chiedere che una frase non manchi nella
  risposta (`da_ricordare`: testo e numero chiave): se il numero non compare, il motore la aggiunge. L'agenda la usa
  per gli appuntamenti già passati («Ne sono già passati 6 nel periodo: vuoi sentirli?»), che a voce il modello taceva
  anche con l'istruzione. L'agenda dà anche la sintesi dei numeri già scritta.
- **AI 1.42.0 — «Parla con Ada» più rapida** (nessuna migrazione). A voce 18 strumenti invece di 39 (meno token, meno
  attesa) e frasi d'attesa quando parte uno strumento. Consigliato nel profilo «Parla con Ada»: Mistral Medium 3.5.
- **AI 1.41.0 — «Parla con Ada» non legge dati inventati** (nessuna migrazione). Guardia «dati senza fonti» sulle
  risposte a voce: cifre che non vengono da nessuno strumento → la risposta si rifà una volta, poi un avviso a voce;
  sotto i sottotitoli le fonti o l'avviso. Cifre nel testo e parole solo nella voce; niente emoji lette. Nuova domanda
  d'oro sugli appuntamenti (`manage.py ai_eval`): un modello che risponde senza leggere il calendario non la passa.
- **Calendario 1.1.1** — l'agenda dell'assistente dice per ogni appuntamento se è passato, in corso o da venire.
- **AI 1.40.0 — «Parla con Ada» più veloce e più precisa** (migrazione `ai.0040`). Nuovo compito dei profili *Parla con
  Ada*: se c'è, i turni a voce usano il suo modello (es. uno veloce e regolare) e il suo tetto ai token; senza, resta la
  chat con «Automatico». Ada saluta per nome; Mistral riceve come parole da favorire il nome dell'assistente,
  dell'azienda e dell'utente.
- **AI 1.39.0 — trascrizione del parlato in cloud** (migrazione `ai.0039`). Nei servizi di «Voce» c'è il campo *uso*:
  con «Trascrizione del parlato» e tipo Mistral (Voxtral) o OVH (Whisper) la dettatura e «Parla con Ada» trascrivono in
  circa un secondo invece dei 6-8 del Whisper locale. Serve il consenso dell'azienda *Trascrizione del parlato con un
  fornitore cloud* (l'audio esce dal server); se il fornitore non risponde si usa il Whisper locale. I servizi già
  configurati restano di lettura.
- **AI 1.38.0 — «Parla con Ada»** (nessuna migrazione). Conversazione a voce a schermo intero (`/ai/parla/`): fine
  della frase automatica, risposte brevi, voce che parte mentre la risposta si scrive, riascolto dopo la risposta,
  interruzione con un tocco. **Sul telefono la chat si apre già così** quando la voce è accesa (dettatura e lettura);
  si spegne per azienda in Impostazioni → Assistente AI. Dettagli in `docs/voce.md`.

## 2026-11-15

- **Nuovo modulo SharePoint 1.0.0** (dipende da Documenti, migrazione `sharepoint.0001`). Una cartella dei Documenti
  allineata con una cartella di SharePoint, nel verso scelto, ogni 15 minuti; si prova senza credenziali con la
  SharePoint finta. Per un collegamento vero serve un'app in Microsoft Entra ID con `Sites.Selected` o
  `Sites.ReadWrite.All` (vedi README, «SharePoint»).

## 2026-11-12

**Da sapere prima di aggiornare**

- **AI 1.37.0 — «Fai dimenticare ad Ada»** (migrazione `ai.0038`). Nella scheda di un documento, per chi ha il permesso
  (gruppo «AI / Amministratore»): il documento esce dall'assistente e dalle chat di tutti gli utenti che lo avevano
  letto (le risposte di quei turni diventano una nota). Registro in Assistente AI → «Documenti dimenticati».
- **Kernel — file con lettere accentate.** Con nginx (X-Accel) un documento o un allegato con lettere accentate nel
  nome (es. «Che_cosa_è.pdf») dava 404 all'anteprima e al download: il percorso ora esce codificato. Serve
  l'immagine nuova.
- **AI — protezione dei dati personali.** Il nome dell'azienda, il marchio e le loro parole non si mascherano più,
  e un «nome utente» si maschera solo se è lo username di un utente: prima «che cos'è adabox?» arrivava al modello
  come «che cos'è [USERNAME_1]?» e Ada non cercava nei documenti.
- **AI 1.36.0 — conoscenza: pagine, stato dei documenti, citazioni verificate** (migrazione `ai.0037`).
  - La ricerca dell'assistente applica permessi e app della chat prima di tagliare la classifica: in «Chiedi alla
    wiki» o con molti record non visibili prima poteva rispondere «non trovo nulla» anche se la pagina c'era.
  - I PDF si indicizzano per pagina: al primo giro dopo l'aggiornamento i loro frammenti si rifanno (e si ricalcolano
    i vettori). La citazione apre l'anteprima alla pagina giusta.
  - Nella scheda di ogni documento la sezione «Per l'assistente» dice se Ada lo legge; le scansioni senza testo e i
    file protetti sono in Assistente AI → «Indice dei documenti».
  - Sotto le risposte che citano documenti, note o pagine compare «N su M citazioni verificate». Per le frasi dubbie
    parte una chiamata al profilo «Classificazione» (nei Consumi con il compito «verifica_citazioni»); si spegne
    nelle impostazioni.
  - Nuova impostazione, spenta: «Riassunto di ogni documento nell'indice». Accesa, ogni documento caricato o cambiato
    costa una chiamata al profilo «Riassunti» (compito «riassunto_documento»); senza protezione dei dati personali
    il testo va al modello così com'è.
- **Kernel 1.2.0.** I moduli possono dichiarare indirizzi alla radice dell'istanza (`urlpatterns_radice`), per i
  percorsi fissati da uno standard. Serve al nuovo modulo «Chat AI esterne», che sulle istanze con il kernel 1.1 non si
  installa: va aggiornata prima l'immagine (`deploy/flotta.py aggiorna`). Gli altri moduli non cambiano.
- **AI 1.35.0 — eliminando una chat i suoi costi restano.** I turni di una conversazione eliminata (a mano o dalla
  conservazione del modulo Privacy) non spariscono più dai Consumi: restano come righe di costo, senza più niente
  della conversazione (risposta, errore, passi, fonti). Prima cancellare le chat abbassava la spesa del mese, e con
  lei il tetto. Per lo stesso motivo le righe dei Consumi non si eliminano più, nemmeno dal Global Admin (migrazione
  `ai.0035`).
- **Discuss 1.13.1 — lavori di servizio.** Le risposte della chat del sito e dell'assistente del portale compaiono
  nei Consumi con il compito «servizio» invece di «riassunti»: chi filtra o raggruppa per compito le trova lì.
  Richiede AI 1.35.0.
- **Rivendita 1.5.0 — «canoni al mese».** Il numero della dashboard ora comprende le suite e il prezzo per utente:
  prima sommava solo piano e moduli in più, quindi può salire senza che sia cambiato nulla.

**Novità**

- **Rivendita 1.5.0 e AI 1.35.0 — le formule dell'assistente.** Nel piano, e se serve sull'istanza, si sceglie come
  si vende l'assistente: «chiave del cliente» (come finora), «inclusa nel canone» con una quota mensile per utente e
  per istanza, oppure «a consumo» con un ricarico e un tetto facoltativo. Il piano ha anche un prezzo per utente al
  mese. I termini arrivano all'istanza nella licenza firmata; chi non usa il portale li mette con
  `ai_licenza --formula … --quota-utente … --quota-istanza …`. Nessun cambiamento per chi resta su «chiave del cliente»
  (migrazioni `rivendita.0006`, `ai.0035`).
- **AI 1.35.0 — provider «fornito con il piano».** Il Global Admin segna così il provider che usa la chiave di chi
  vende. Il costo dei suoi modelli si conta a parte («Sul piano» nei Consumi) e vale per la quota: a quota finita quei
  modelli escono dalla catena fino al primo del mese, e la chat continua sui modelli con una chiave dell'azienda o
  locali, se ci sono. Provider, modelli e prezzi li cambia solo il Global Admin, e la chiave dell'azienda lì non vale.
  La chat avvisa dall'80% della quota; la pagina Licenza mostra formula, consumo del mese e consumo per utente, e
  segnala se la formula c'è ma nessun provider è segnato.
- **Rivendita 1.5.0 — Consumi AI.** Ogni ora le istanze con una formula diversa da «chiave del cliente» riferiscono al
  portale il riepilogo del mese in corso e del precedente (costi, turni, numero di persone: nessun nome). La pagina
  «Consumi AI» mostra, con «a consumo», l'importo da fatturare (costo sul piano × cambio × ricarico) e, con «inclusa»,
  il consumo rispetto alla quota. Il cambio dollaro → euro è un'impostazione del modulo: parte da 1,00 e va aggiornato
  a mano. I numeri li dichiara l'istanza: per quelle non ospitate il riscontro resta la fattura del fornitore.
- **AI 1.35.0 — OpenAI e Gemini tra i provider** (migrazione `ai.0036`). Due tipi nuovi accanto ad Anthropic e
  Mistral: basta la chiave, i modelli si scelgono dal catalogo del fornitore. I provider già configurati come
  «compatibile OpenAI» continuano a funzionare; passandoli al tipo nuovo, con OpenAI si usano anche i modelli che
  ragionano (rifiutano `max_tokens`) e con Gemini le chiamate agli strumenti dei modelli dalla serie 3 (rivogliono la
  firma del ragionamento, che prima andava persa: bastava il secondo passo per avere un errore 400). Provati con
  risposte simulate, non con i due servizi veri.
- **Chat AI esterne 1.0.0 (`connettore_ai`)**: adabox come connettore dentro Claude, ChatGPT, Gemini e Le Chat
  (migrazione `connettore_ai.0001`). Ogni persona collega la chat che usa già e da lì legge ciò che in adabox può
  vedere, con il suo abbonamento: sola lettura, permessi di ogni momento, registro delle chiamate, mascheramento dei
  dati personali se l'azienda lo accende. Spento finché un'azienda non lo accende in Impostazioni; serve un'istanza
  pubblica in https con `SITO_URL` corretto. Alla radice dell'istanza compaiono `/mcp` e due indirizzi sotto
  `/.well-known/`: il proxy deve passarli all'app. Provato con client simulati, non ancora con i quattro veri.

## 2026-11-11

**Da sapere prima di aggiornare**

- **Documenti 1.2.0 — gli spazi personali diventano privati.** L'impostazione «I responsabili dei documenti vedono gli
  spazi personali» passa a spenta di default: gli spazi personali li vede solo il proprietario, anche nell'elenco dei
  documenti dei responsabili e nella ricerca dell'assistente. Le aziende che l'avevano esplicitamente accesa non
  cambiano. Chi vuole il comportamento di prima la riaccende in Impostazioni → Documenti. Corretto anche un difetto:
  prima l'elenco dei documenti mostrava ai responsabili gli spazi personali anche con l'impostazione spenta.
- **Posta e calendario — invio dal chatter.** Le caselle collegate prima di questa versione non hanno il permesso di
  inviare: gli utenti che vogliono rispondere ai clienti dalla propria casella devono ricollegarla (la pagina lo
  dice). Fino ad allora i messaggi partono dall'indirizzo di sistema, come prima.

**Novità**

- **Connettori 1.4.0 — Odoo**, contatti e opportunità, con «ogni utente con la sua chiave»: ognuno collega il suo
  account da «I miei account esterni» e in adabox vede solo ciò che Odoo mostra a lui (migrazione `connettori.0005`).
  Le aziende si agganciano per partita IVA, anche negli altri connettori. Provato su un Odoo 19 vero.
  Con «le modifiche fatte in adabox tornano lì» contatti e opportunità salvati in adabox si scrivono in Odoo con la
  chiave di chi li salva (migrazione `connettori.0006`).
  Con «anche il calendario» arrivano anche gli appuntamenti di Odoo, in sola lettura (migrazione `connettori.0007`).
  Con «anche gli ordini di vendita» arrivano gli ordini di Odoo con righe e prodotti, in sola lettura: consegne e
  fatture restano a Odoo (migrazione `connettori.0008`). Nuovo nel kernel `core.esterni`: i documenti gestiti da un
  altro sistema non si modificano e non generano fatture né consegne.
- **Discuss 1.13.0 e Portale 1.2.0 — assistente nel portale clienti.** Nello sportello del sito si attiva «risponde
  anche nel portale clienti»: i clienti autenticati trovano la sezione «Assistente», che risponde con la conoscenza
  dello sportello, la guida pubblicata e il riepilogo dei loro documenti (gli stessi della home del portale). Non ha
  strumenti né accesso al database; quando non sa propone una richiesta di assistenza. Le domande sono visibili allo
  staff in Discuss → Domande dal portale (migrazione `discuss.0015`). Spento finché non si attiva.
- **AI 1.34.0 — ricerca mirata.** Si può chiedere all'assistente di cercare solo nei propri documenti o solo nella
  cartella dell'area di lavoro; le pagine della wiki sono indicizzate per intero, divise per sezioni.
- **Wiki 1.1.0 — «Chiedi alla wiki»** e domande senza risposta per i responsabili (migrazione `wiki.0002`).
- **Discuss 1.12.0 — la wiki come fonte dell'assistente del sito**: nello sportello si scelgono gli spazi pubblici
  (migrazione `discuss.0014`). Nessun cambiamento finché non se ne sceglie uno.
- **Connettori 1.3.0 — Salesforce e Zoho CRM** sullo stesso motore di HubSpot (migrazione `connettori.0004`). Provati
  solo contro sistemi simulati: prima di venderli, una prova con un'organizzazione vera (docs/collegamenti-esterni.md).
- **Nuovo modulo Posta e calendario**: casella e calendario Google o Microsoft per utente, da installare dove serve.
