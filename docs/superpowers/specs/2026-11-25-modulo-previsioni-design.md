# Modulo «Previsioni»

Data: 2026-11-25
Stato: progetto da approvare (deciso con l'utente in sessione, punto per punto; riletto da un revisore)

## Intento

Le previsioni diventano un'**opzione a pagamento della licenza di AdaBox**, venduta a tutti i clienti come le altre app
del catalogo. Chi la compra fa previsioni sui dati della propria azienda, a seconda dei moduli che ha: vendite,
magazzino e, nel tempo, tutto ciò su cui una previsione ha senso. Il magazzino è il caso più concreto (clienti come IEM
hanno problemi di scorte): sapere per tempo quando un articolo finisce e quando riordinarlo.

## Che cosa c'è oggi

- Il motore di previsione sta **dentro l'Assistente AI**: `addons/ai/specialisti.py` (`serie_storica`, `prevedi`,
  `calcola_previsione`, affidabilità con backtest) e lo strumento di Ada `previsione` in
  `addons/ai/strumenti/specialisti.py`. La licenza lo comprende o no con la funzione `specialisti` dell'assistente
  («Previsioni e classificazioni»), che comprende anche il decisore (`classifica`).
- I numeri li calcola **Timestral** (`mistralai/Timestral-123M`), un servizio HTTP sulla rete interna
  (`/v1/forecast`, quantili 0,1 · 0,5 · 0,9, fino a 512 serie per chiamata), indirizzo nell'impostazione
  `ai.url_forecast`. Sull'hub gira come container condiviso (`adabox-forecast-1`).
- In Analisi il grafico di tipo **Previsione** (`addons/grafici`, `Grafico.PREVISIONE`) chiama
  `ai.specialisti.calcola_previsione`. `grafici.motore.previsioni_disponibili()` controlla solo che il modulo AI sia
  attivo e l'URL impostato, **non la licenza**: un cliente senza la funzione vede comunque il tipo Previsione (difetto
  da correggere con questo lavoro).
- La previsione è **generica**: una serie per volta (una vista, una data, una misura, filtri) o una misura aziendale.
  Non esiste la previsione per gruppo (per prodotto, per cliente), né alcuna previsione pronta per modulo.
- Previsioni di regola, non statistiche, già presenti e fuori da questo lavoro: CRM › Previsione (pipeline pesata) e i
  ricavi futuri dei contratti in Ricorrenti.
- Magazzino: `Movimento` (carico, scarico, rettifica, trasferimento, con data e quantità), giacenze per magazzino,
  «previsto» = giacenza + in arrivo − impegnato (`magazzino/pagine.py`), soglie per magazzino e articolo
  `ScortaMagazzino.punto_riordino` («riordina sotto») e `scorta_obiettivo` («riporta a»), scorta minima del prodotto
  `Prodotto.scorta_minima`. I giorni di consegna dei fornitori non sono registrati da nessuna parte. I prelievi fatti
  a mano si salvano sempre come **rettifica** (`magazzino/views.py`, unico inserimento manuale); gli scarichi vengono
  solo da consegne, riparazioni e storni; le rettifiche degli inventari sono collegate all'inventario
  (`content_type` = Inventario) o hanno la causale «Inventario iniziale».
- Acquisti: `RegolaRiordino` per prodotto e azienda («riordina sotto», «riporta a», fornitore, «crea da sola le
  richieste»), la pagina «Da riordinare» e un lavoro alle 06:00 (`acquisti.riordino.automatico`) che per le regole
  automatiche prepara ordini ai fornitori **in bozza**, decisi dal buyer. Lavora a soglie sulla giacenza prevista, senza
  previsione del consumo. Senza regola vale la scorta minima del prodotto.
- Il motore chiede almeno 6 periodi di storia (`MIN_PERIODI`) e sotto 12 dà affidabilità bassa.

## Obiettivi

1. Un modulo **`previsioni`** a sé (app del catalogo, voce della licenza), che funziona **anche senza l'Assistente AI**.
2. **Previsioni pronte** per i moduli che il cliente ha, senza niente da scrivere:
   - **Vendite**: fatturato previsto per mese; quantità vendute per prodotto (i primi 10, prossimi 3 mesi); vendite per
     cliente (i primi 10).
   - **Magazzino**: per articolo e magazzino, consumo previsto con la fascia, **data di esaurimento**, **data di
     riordino**, quantità suggerita; l'elenco **«Articoli in esaurimento»**.
3. **Tre porte d'ingresso, un solo motore** (gli stessi numeri ovunque):
   - dentro i moduli, dove si lavora (scheda dell'articolo di magazzino, scheda del prodotto, schede delle app nella
     dashboard);
   - la pagina **Previsioni** del modulo: tutte le previsioni pronte dei moduli del cliente, più **«Nuova previsione»**
     per quelle su misura (che cosa prevedere, raggruppato per cosa, per quanti periodi, i primi quanti), salvabile in
     una dashboard;
   - la **chat con Ada**, se il cliente ha anche l'assistente: domande come «quali sono i prodotti più venduti? fai una
     previsione delle loro vendite per i prossimi 3 mesi», con lo stesso grafico, salvabile.
4. **Previsione per gruppo**: più serie in una chiamata (una per prodotto, cliente…), un grafico o una tabella.
5. Le previsioni si **ricalcolano ogni notte** e con il bottone **«Aggiorna»**; accanto a ognuna l'**affidabilità**
   (il backtest che il motore già fa).
6. Il tipo Previsione di Analisi e lo strumento di Ada esistono **solo con il modulo in licenza**.

## Non obiettivi (fuori da questa versione)

- **Ordini ai fornitori**: li preparerà un **agente del riordino** sviluppato a parte e venduto nel negozio degli agenti
  (`/awf/negozio/`, modulo `awf`). Questo modulo gli lascia i dati (l'elenco «Articoli in esaurimento», leggibile come
  le altre viste, quindi anche dagli agenti tramite Agate), non fa il suo lavoro.
- **Notifiche**: per ora basta vedere le previsioni nell'elenco e nella pagina. Passo successivo già deciso: un
  messaggio in **Comunicazioni** (Discuss) al **responsabile del riordino** del magazzino. Oggi `Magazzino` non ha un
  responsabile: servirà un campo nuovo, allora.
- **Previsione di cassa**: si calcola dalle scadenze di fatture e pagamenti, non dalla storia; è un lavoro diverso.
- **Giorni di consegna dei fornitori**: non si aggiungono; il riordino usa le soglie che esistono (vedi sotto).
- Rettifiche manuali delle previsioni (come in CRM), addestramento o messa a punto del modello.

## Anti-obiettivi (sarebbe un fallimento anche se funzionasse)

- Un numero di previsione scritto dal modello linguistico: i numeri vengono sempre dal servizio, la serie storica dal
  database con i permessi di chi guarda (regola già valida nell'assistente).
- Una previsione mostrata senza fascia d'incertezza o senza affidabilità, o un «finisce il 12 febbraio» presentato come
  certezza.
- Un cliente che vede previsioni senza averle comprate, o dati di un'altra azienda.
- Legare di nuovo il modulo all'assistente: senza Ada deve funzionare tutto tranne la porta della chat.

## Vincoli

- **Licenza di Timestral** (verificata il 2026-11-25, file LICENSE dei modelli su Hugging Face): pesi sotto «Modified
  MIT License» di Mistral AI; uso commerciale e ridistribuzione ammessi con l'avviso «2026 - Mistral AI» e il testo
  della licenza in ogni copia; **nessun diritto** per aziende o gruppi oltre **20 milioni di dollari di ricavi al
  mese** (serve una licenza commerciale di Mistral). Il pacchetto `timestral` è Apache-2.0. Conseguenze: l'avviso di
  attribuzione va mostrato (vedi «Attribuzione») e il file LICENSE va messo accanto ai pesi dove il modello si
  distribuisce; per i clienti oltre la soglia il modulo non si vende senza accordo con Mistral (regola commerciale,
  nessun controllo tecnico).
- Convenzioni del repository: modulo in `addons/previsioni` con manifest, servizi del kernel, viste ModelView, test in
  `addons/previsioni/tests/` e slug in `ADDONS_FORCE` di `pytest.ini` (CLAUDE.md, README). Il tema non importa il
  kernel. Note di rilascio in `docs/note-di-rilascio.md`.
- Multi-azienda: ogni previsione salvata ha l'azienda; si vede con i permessi delle viste da cui viene (un utente senza
  Magazzino non vede le previsioni del magazzino, anche con il modulo).
- Il servizio di previsione può mancare o non rispondere: le pagine devono restare utilizzabili (ultima previsione
  salvata con la sua data, oppure un messaggio chiaro).

## Approcci considerati

- **A. Modulo «Previsioni» a sé** — scelto dall'utente. App del catalogo con le sue pagine, venduta come le altre,
  funziona senza Ada; con Ada aggiunge la porta della chat. Più lavoro, prodotto chiaro da vendere.
- **B. Funzione dell'assistente (come oggi)**, con in più le previsioni pronte. Meno lavoro, ma solo chi compra Ada le
  avrebbe: contro l'intento (venderle a tutti i clienti).

## Decisioni prese con l'utente

1. Modulo a sé (A).
2. Si usa anche dalla chat, se c'è Ada; senza Ada ci sono la pagina del modulo e le previsioni dentro i moduli.
3. Magazzino: la previsione dice **quando un articolo finisce e quando riordinare**; l'ordine al fornitore no (agente a
   parte nel negozio).
4. Il giorno di riordino si calcola **con le soglie che ci sono già**, non con i giorni di consegna.
5. Per ora **niente notifiche**: elenco e pagina. Poi un messaggio in Comunicazioni al responsabile del riordino.
6. **Nessuna compatibilità con le previsioni di oggi**: AdaBox è ancora una demo, chi le ha attraverso l'assistente le
   perde con l'aggiornamento.
7. **Dove gira il servizio**: per ora solo sul server dell'hub (demo). Per i clienti due strade, entrambe da
   supportare: un servizio remoto su un server di ICHNOBYTE raggiunto con una **chiave API**, oppure un container
   accanto all'applicazione sul server del cliente.

## Il progetto

### 1. Il modulo e la licenza

- Slug `previsioni`, `application: True`, categoria «Direzione» (o quella che il catalogo usa per Analisi), menu:
  **Previsioni** (la pagina), **Articoli in esaurimento** (solo con Magazzino), permessi e gruppi come gli altri moduli
  (`Previsioni / Utente`, `Previsioni / Responsabile`).
- Si compra come gli altri moduli: compare in `/applicazioni/` e nel portale di rivendita, ed è attivo solo se è nella
  licenza (`core.licenza.ammesso`). Nessuna dipendenza obbligatoria (`depends: []`): le previsioni pronte di Vendite e
  Magazzino compaiono solo se quelle app sono attive per l'azienda.
- L'impostazione **«URL del servizio di previsione»** passa dall'assistente al modulo (`previsioni.url_forecast`, la
  imposta il Global Admin). Migrazione: se `ai.url_forecast` ha un valore e quella nuova è vuota, si copia.

### 2. Il motore

- `serie_storica`, `prevedi`, `calcola_previsione` e l'affidabilità **escono da `addons/ai/specialisti.py`** ed entrano
  nel modulo (per esempio `previsioni/motore.py`). Nell'assistente resta il decisore (`classifica`); la funzione
  `specialisti` dell'assistente diventa «Classificazioni».
- **Previsione per gruppo**: oltre alla serie singola, una spec con un raggruppamento (un campo della vista: prodotto,
  cliente…) e `primi` N (default 10): si scelgono i primi N gruppi per totale sulla storia, si costruisce una serie per
  gruppo e si mandano al servizio **in una chiamata** (fino a 512 serie; oltre, a blocchi). Il resto dei gruppi non si
  prevede (niente «Altro» nella prima versione: scelta lasciata al costruttore se serve).
- Le serie con troppa poca storia non si prevedono o escono con affidabilità «bassa» e il motivo (regola che il motore
  ha già: `STORIA_SOLIDA`).
- Una sola strada per tutti: la pagina, le schede dei moduli, il grafico di Analisi e lo strumento di Ada chiamano lo
  stesso motore.

### 3. Previsioni pronte, dichiarate dai moduli

- Un registro di previsioni pronte (hook del modulo, sullo stile di `hooks.fonte_ricerca`): ciascuna ha titolo, app,
  permesso, una funzione che costruisce la spec (o le serie) per l'azienda, e dove mostrarla (pagina Previsioni,
  scheda di un record, scheda dell'app).
- Nella prima versione le previsioni pronte di **Vendite** e **Magazzino** stanno nel modulo `previsioni` (così
  vendere il modulo non obbliga a cambiare versione a Vendite e Magazzino); i moduli futuri dichiareranno le proprie
  dallo stesso registro. Scelta del costruttore se tenerle lì o spostarle nei moduli.

### 4. Magazzino: esaurimento e riordino

Per ogni coppia articolo e magazzino con movimenti:

- **Livello** (mia scelta, per non contraddire le pagine «sotto scorta» di Magazzino e «Da riordinare» di Acquisti):
  una riga **per magazzino** per gli articoli che hanno una soglia di quel magazzino (`ScortaMagazzino`); per gli altri
  una riga **per l'azienda intera** (senza magazzino), sul totale dei magazzini.
- **Soglie, in quest'ordine** (mia scelta): per magazzino `ScortaMagazzino` («riordina sotto», «riporta a»); per il
  totale la `RegolaRiordino` di Acquisti se Acquisti è attivo, altrimenti `Prodotto.scorta_minima`.
- **Consumo** (mia scelta): la serie delle uscite = scarichi + **rettifiche negative che non vengono da un inventario**
  (i prelievi fatti a mano si salvano così; un'officina che preleva a mano risulterebbe altrimenti a consumo zero) +,
  per le righe di un magazzino, i trasferimenti in uscita verso altri magazzini. Gli storni si compensano con ciò che
  annullano. Nel totale dell'azienda i trasferimenti si annullano. Rettifiche positive e rettifiche d'inventario non
  contano. Previsione dei prossimi periodi, quantili 10 · 50 · 90.
- **Poca storia** (mia scelta): con meno di 12 mesi di movimenti la serie del magazzino è **settimanale** (6 settimane
  bastano per partire, con affidabilità bassa); da 12 mesi in su mensile. Nessuna importazione dello storico nella prima
  versione.
- **Partenza**: la giacenza «prevista» come la definisce già Magazzino (giacenza + in arrivo − impegnato).
- **Data di esaurimento**: il giorno in cui la giacenza, tolto il consumo previsto (mediana, ripartito sui giorni del
  mese), arriva a zero. Con la fascia: «finisce tra il … e il …» (consumo alto 90 → prima, basso 10 → dopo).
- **Data di riordino**: il giorno in cui la giacenza prevista scende sotto **«riordina sotto»** di quel magazzino
  (`ScortaMagazzino.punto_riordino`) o, se manca, sotto la **scorta minima** del prodotto. Già sotto → «riordina ora».
  Senza nessuna soglia: solo la data di esaurimento.
- **Quantità suggerita** (solo informazione): quella che riporta la giacenza a «riporta a» (`scorta_obiettivo`) alla
  data di riordino; senza «riporta a», il consumo previsto dei tre mesi successivi.
- Oltre l'orizzonte della previsione (per esempio 12 mesi) la data è «oltre …».
- I risultati si **salvano** in un modello del modulo (azienda, magazzino, prodotto, partenza, consumo previsto per
  mese con i quantili, data di esaurimento e fascia, data di riordino, quantità suggerita, affidabilità, calcolata il),
  esposto come vista **«Articoli in esaurimento»** (ModelView: lista ordinata per data di riordino, filtri per
  magazzino e per «entro N giorni», sola lettura). È la vista che l'agente del riordino leggerà.
- Nella **scheda dell'articolo** di Magazzino (o del prodotto) un riquadro con la riga per magazzino:

```
Previsione · Cavo FG16 3x2,5 · magazzino Cagliari
  Giacenza prevista 120 m · consumo previsto 45 m/mese (fascia 30–60)
  Finisce verso il 10 febbraio (tra il 25 gennaio e il 3 marzo)
  Riordina entro il 20 gennaio (sotto «riordina sotto» 60 m) · quantità suggerita 135 m
  Affidabilità media: 14 mesi di storia · calcolata stanotte alle 02:10 · [Aggiorna]
```

### 4 bis. Rapporto con Acquisti

Il modulo **non tocca** il riordino di Acquisti (pagina «Da riordinare» e lavoro delle 06:00, che continua a lavorare
a soglie). Usa le stesse soglie, così le date di riordino e le pagine esistenti dicono la stessa cosa. L'agente del
riordino del negozio potrà unire le due cose (previsione e ordini in bozza).

### 4 ter. Da quali dati vengono le previsioni di Vendite (mia scelta)

- **Fatturato per mese**: la misura `fatturazione.fatturato` (fatture meno note di credito) se Fatturazione è attivo;
  altrimenti `vendite.ordinato` (ordini confermati), con il nome «ordinato» e non «fatturato».
- **Quantità per prodotto**: dalle righe degli ordini di vendita confermati (`vendite.quantita_venduta`), nell'unità del
  prodotto; le righe in un'altra unità si convertono se c'è il fattore, altrimenti si escludono (e si dice quante).
- **Vendite per cliente**: come il fatturato (fatture se c'è Fatturazione, altrimenti ordini), per cliente.
- Un cliente che fattura altrove (per esempio IEM con Mago4) e usa solo Vendite ha le previsioni sugli ordini.

### 4 quater. Permessi (mia scelta)

- Le previsioni pronte salvate dal lavoro notturno si calcolano con l'accesso all'intera azienda. Così si mostrano
  **solo a chi vede tutta la vista di origine**: senza regole di riga (`RegolaRiga`) su quella vista e senza campi
  nascosti (`PermessoCampo`) tra quelli usati (data, misura, raggruppamento).
- Per chi ha restrizioni la previsione si **calcola al momento con i suoi permessi** (come fa Analisi per chi non è il
  proprietario del grafico), con una cache breve per utente; se costa troppo (molti articoli), per lui la pagina mostra
  la scelta di calcolarla.
- La vista «Articoli in esaurimento» applica le regole di riga di Magazzino come le altre viste.

### 5. La pagina «Previsioni»

- In cima le previsioni pronte delle app che l'utente vede, a schede o sezioni per app (Vendite, Magazzino), ciascuna
  con grafico o tabella, fascia, affidabilità, ora di calcolo.
- **«Nuova previsione»**: il costruttore del tipo Previsione di Analisi esteso con «raggruppa per» e «primi N»; si
  salva come grafico in una dashboard (Analisi) se l'utente ha Analisi, altrimenti resta nella pagina Previsioni
  dell'utente (scelta del costruttore come conservarla).

### 6. Dentro i moduli e in Analisi

- Schede di record: il riquadro del magazzino (sopra); per Vendite, nella scheda del prodotto, le vendite previste dei
  prossimi 3 mesi.
- Schede delle app nella dashboard di Analisi (`grafici/app/<slug>/`): le previsioni pronte di quell'app come widget
  disponibili nella libreria.
- Il tipo **Previsione** del costruttore di Analisi e i grafici salvati di quel tipo usano il motore del modulo e
  compaiono **solo con il modulo attivo e in licenza** (corregge il difetto descritto in «Che cosa c'è oggi»).

### 7. La chat

- Lo strumento `previsione` passa nel modulo (dichiarato con la chiave `ai` del manifest, come gli strumenti delle
  altre app): esiste solo se il modulo è in licenza e il servizio è configurato, e accetta anche «raggruppa per» e
  «primi N».
- Uno strumento di lettura delle previsioni pronte (per esempio «articoli in esaurimento entro N giorni») così Ada
  risponde senza ricalcolare.

### 8. Ricalcolo

- Un lavoro notturno (chiave `cron` del manifest, come `sharepoint`) ricalcola le previsioni pronte per ogni azienda
  con il modulo; le serie vanno al servizio a blocchi.
- «Aggiorna» nella pagina e nel riquadro ricalcola subito quella previsione (nel worker se è grande).
- Se il servizio non risponde: resta l'ultima previsione con la sua data e un avviso; il lavoro riprova la notte dopo.

### 9. Attribuzione

Dove si mostra una previsione di Timestral: «modello mistralai/Timestral-123M · licenza Modified MIT di Mistral AI»
(oggi c'è solo il nome del modello). Nella documentazione del modulo e del deploy: il file LICENSE accanto ai pesi.

### 10. Il servizio di previsione: dove gira

- Il modulo ha due impostazioni del Global Admin: **URL del servizio** e **chiave API** (facoltativa, salvata cifrata
  come le altre chiavi del kernel, mandata nell'intestazione `Authorization: Bearer …`). Con la stessa versione il
  modulo usa il container dell'hub (oggi, senza chiave), un servizio remoto con chiave, o un container sul server del
  cliente.
- Al servizio arrivano solo serie di numeri con identificativi opachi (mai nomi di prodotti, clienti o aziende): così
  la strada remota non porta dati riconoscibili fuori dal server del cliente.
- Strada consigliata per i clienti: il **servizio remoto** di ICHNOBYTE (niente hardware dal cliente, un solo servizio
  da mantenere; la copia del modello resta di ICHNOBYTE: che il limite di fatturato riguardi allora ICHNOBYTE e non il
  cliente va confermato da un legale). Il **container presso il cliente** per chi non vuole che esca nulla: lì la copia
  è del cliente e il limite dei 20 milioni vale per lui.

### 11. Senza compatibilità

Dopo l'aggiornamento, senza il modulo in licenza: niente tipo Previsione nel costruttore di Analisi e niente strumento
`previsione` di Ada; i grafici Previsione già salvati e i grafici Previsione delle chat mostrano «Serve il modulo
Previsioni» al posto dei dati. Nessun codice per mantenere le previsioni a chi le aveva con l'assistente.

## Passi successivi già previsti (non in questa versione)

0. Deploy, fuori da questo repository: la chiave API nel servizio di previsione (o davanti, nel proxy) e la sua
   esposizione in https per la strada remota; un servizio di previsione facoltativo in `deploy/compose.cliente.yml`,
   con i pesi e il file LICENSE, per la strada presso il cliente.
1. Notifica in Comunicazioni al responsabile del riordino del magazzino (campo nuovo su `Magazzino`).
2. Agente del riordino nel negozio `awf`, che legge «Articoli in esaurimento» e prepara gli ordini con le regole di
   Agate.
3. Previsioni pronte di altri moduli (Acquisti, Helpdesk, Ore…) e la previsione di cassa.

## Lasciato al costruttore

- Nomi di modelli, file e URL; forma esatta del registro delle previsioni pronte e del modello salvato.
- Come mostrare le previsioni pronte nella pagina (schede o sezioni) e il riquadro nelle schede dei record.
- Orizzonte di default del magazzino (proposta: 12 mesi) e limite di articoli per azienda nel lavoro notturno.
- Se raggruppare il «resto» in «Altro» nella previsione per gruppo.
- Dove conservare una «Nuova previsione» per chi non ha Analisi.
