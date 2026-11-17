# Ada: misure aziendali, numeri affidabili e risposte rapide

Data: 2026-11-17 · Stato: proposta da approvare · Ramo: `misure-aziendali`

## Perché

Ada serve per le demo e per vendere: nessun cliente l'ha ancora comprata. In una demo un numero sbagliato o una
risposta da 30 secondi costa la trattativa più di qualunque funzione mancante. Le domande tipiche di una demo
riguardano vendite, previsioni, scorte, ordini, fatture e appuntamenti.

Cosa dicono le conversazioni di novembre (database dell'istanza, 96 turni di chat dal 1° al 17):

- **Lo stesso «fatturato 2026» ha avuto tre risposte**, a seconda del modello e della domanda: 983.034 € (ordini
  confermati), 729.218 € (fatture comprese le bozze), 707.364 € (fatture emesse, IVA inclusa). Il fatturato vero,
  l'imponibile delle fatture emesse meno le note di credito, è **579.831 €**; la dashboard della Fatturazione lo
  calcola già così (`fatturazione/dashboard.py`, `_netto`). Ada e dashboard oggi si contraddicono.
- **«I 5 clienti che hanno fatturato di più»**: 6 passi, 3 errori, perché `aggrega_record`, `grafico` e `tabella` non
  sanno ordinare per valore né prendere i primi N. Ada ha ripiegato sulle 100 fatture più alte e ha scelto i clienti da
  lì: il risultato è giusto per caso.
- **Tempi**: mediana 8,4 s, una risposta su dieci oltre 33 s. Senza strumenti 2,6 s, con due passi circa 10 s. Prima di
  leggere un dato Ada spende spesso due passi (`elenco_viste`, `descrivi_vista`) a scoprire dove sono i dati.

## Obiettivi

1. Per le misure delle aree da demo **la definizione la decide il codice, non il modello**: stessa domanda, stesso
   numero, con qualunque modello (Claude, Mistral, GLM, DeepSeek) e uguale a quello della dashboard.
2. Ogni numero di una misura si può **controllare con un clic**: sotto la risposta la definizione e il link alla lista
   filtrata dei record da cui viene.
3. Le domande da demo su una misura si chiudono in **1-2 passi del modello**. Obiettivo misurato sulle domande d'oro da
   demo con Claude Haiku 5.5: mediana ≤ 5 s, 90 % ≤ 12 s (oggi 8,4 s e 33,5 s su tutte le domande).
4. Il «top N» e l'ordinamento per valore funzionano negli strumenti generici, così anche le domande fuori dalle misure
   non inciampano.

## Non obiettivi (per questo progetto)

- Grafici interattivi, dashboard «wow», tabelle editabili, multitasking, sicurezza dei dati riservati: sono i progetti
  successivi già concordati.
- Misure definite dagli utenti dall'interfaccia. Le misure le scrive chi sviluppa le app.
- Scegliere una misura nel costruttore di Analisi (interfaccia): basta che un grafico salvato da Ada con una misura si
  ricalcoli giusto in Analisi.
- Risposte preparate senza modello per le domande da demo (scartate: la differenza si vede appena il cliente cambia
  una parola).
- Il giro «pollice giù → domanda d'oro»: senza clienti non ci sono pollici (oggi zero).

## Anti-obiettivi (fallimento anche se tecnicamente funziona)

- Ada e la dashboard danno numeri diversi per la stessa misura.
- Una misura che vede record che l'utente nella lista non vedrebbe (permessi, azienda corrente, regole sulle righe).
- Risposte più lente di oggi sulle domande che non usano misure (prompt più lungo che rallenta tutto).
- Una definizione nascosta: l'utente deve poter leggere sempre che cosa è stato sommato.

## Vincoli

- I dati si leggono solo attraverso le `ModelView` con i permessi di chi chiede (`core/viste/interroga.py`:
  `vista_per_nome`, `filtra`, `aggrega`): le misure si costruiscono sopra, non accanto.
- Multi-azienda: `aggrega` e `kpi` hanno già il consolidato (`aziende_di`); le misure lo devono ereditare.
- Prompt di sistema byte-stabile per la cache del prefisso (`ai/motore/prompt.py`): l'elenco delle misure entra lì solo
  se cambia soltanto quando cambiano i moduli installati.
- I moduli si installano e disinstallano: ogni app dichiara le proprie misure; senza l'app la misura non esiste.
- L'istanza gira su SQLite; dati demo di 13 mesi (`addons/dati_demo.json`).
- Funzione della licenza: le misure sono lettura e appartengono alla stessa funzione degli strumenti di lettura (non
  si vendono a parte).

## Approcci considerati

| | Approccio | Pro | Contro |
|---|---|---|---|
| **A** | **Misure aziendali definite nel codice** (scelto) | definizione fissa, uguale a dashboard e Analisi; 1-2 passi; numeri controllabili | lavoro medio; le misure vanno aggiornate quando cambia un'app |
| B | Solo correzioni agli strumenti (top N, suggerimenti nelle descrizioni, più domande d'oro) | costa poco | la definizione la sceglie ancora il modello, e cambia da un modello all'altro |
| C | Risposte preparate per le domande da demo | istantanee | fragili, sanno di trucco |

L'utente ha scelto A il 2026-11-17. A comprende le correzioni di B (punto 4 degli obiettivi).

## Il progetto

### 1. Le misure nel kernel

Nuovo registro `core/misure.py`. Ogni app dichiara le sue misure con la chiave `"misure": "<app>.misure"` del
manifest (come `"ai"` e `"dashboard"`): un modulo che chiama `registra(Misura(...))` all'avvio.

Una misura ha:

- `nome` (`fatturazione.fatturato`), `etichetta` («Fatturato»), `definizione` in una frase per l'utente («imponibile
  delle fatture emesse meno quello delle note di credito, per data della fattura»), `unita` (€, numero), `sinonimi`
  per il prompt («vendite», «ricavi»);
- `raggruppamenti` ammessi con un nome semplice (`cliente`, `mese`, `prodotto`...) e il campo della vista a cui
  corrispondono;
- `periodo_su`: il campo data su cui si applica il periodo (assente per le misure istantanee, come «sotto scorta»);
- il calcolo, di due tipi:
  - **aggregata**: una o più componenti `{vista, misura, filtri, segno}` sulle viste esistenti. Fatturato =
    `+ sum:imponibile` sulle fatture emesse di vendita, `− sum:imponibile` sulle note di credito emesse. Ogni
    componente passa da `aggrega` con i permessi; il registro somma le componenti gruppo per gruppo. Solo le
    aggregate si raggruppano, si disegnano, si prevedono e si salvano in Analisi;
  - **calcolata**: una funzione `(request, parametri) → {valore, righe}` per ciò che non è una somma su una vista
    (sotto scorta: `magazzino.pagine.situazione`). Ogni riga porta il suo link.

Funzione unica `core.misure.calcola(nome, request, periodo=..., per=..., primi=..., confronta=..., aziende=...)` →
`{valore, unita, definizione, periodo (dal, al, etichetta), gruppi [{gruppo, valore, url}], confronto {valore,
delta_percento, periodo}, url}`. `url` è la lista filtrata dei record (per le aggregate con più componenti: la lista
della componente principale con i filtri, più una nota sulle altre).

Periodi ammessi: `oggi`, `settimana`, `mese`, `trimestre`, `anno` (in corso), gli stessi con `_scorso`, `dal`/`al`
espliciti. Confronto: `periodo_prima` o `anno_prima` (stesso tratto dell'anno precedente: 1/1-17/11/2025 contro
1/1-17/11/2026, non l'anno intero).

### 2. Le misure di partenza

Quelle delle aree da demo. Dove una dashboard calcola già lo stesso numero, la dashboard passa a usare la misura (un
solo punto di verità):

| App | Misura | Definizione | Usata anche da |
|---|---|---|---|
| fatturazione | `fatturato` | imponibile fatture emesse di vendita (esclusi note di credito e autofatture) − imponibile note di credito emesse, per data | dashboard Fatturazione |
| fatturazione | `fatture_emesse` | numero di fatture emesse (note di credito escluse) | |
| fatturazione | `da_incassare` | scadenze aperte di fatture emesse: importo − incassato | dashboard Fatturazione |
| fatturazione | `scaduto` | come `da_incassare`, con scadenza prima di oggi | dashboard Fatturazione |
| fatturazione | `incassato` | incassi registrati (tipo «incasso»), per data | |
| vendite | `ordinato` | imponibile degli ordini confermati, per data dell'ordine | |
| vendite | `preventivi_aperti` | preventivi in bozza o inviati: numero e imponibile | |
| acquisti | `acquistato` | imponibile degli ordini di acquisto confermati, per data | |
| magazzino | `sotto_scorta` | prodotti con giacenza sotto la scorta minima o il punto di riordino (calcolata) | dashboard Magazzino |
| calendario | `appuntamenti` | eventi del calendario visibili all'utente, per data di inizio | |

**«Vendite» vuol dire fatturato** (sinonimo nel prompt), perché è il numero che il commercialista e la dashboard
riconoscono; se l'utente parla di ordini, Ada usa `ordinato`. La risposta dice sempre quale delle due ha usato.
Deciso dall'utente il 2026-11-17.

### 3. Gli strumenti di Ada

- **`misura`** (nuovo, lettura, concorrente): `nome`, `periodo` o `dal`/`al`, `per`, `primi`, `confronta`, `aziende`.
  Restituisce il risultato di `core.misure.calcola` con una nota per il modello («riporta valore e definizione; i link
  sono sotto la risposta»). Gli errori parlano la lingua dell'utente («la misura fatturato si raggruppa per cliente,
  mese, prodotto»).
- **`grafico`**, **`previsione`**, **`analisi_salva_grafico`**: accettano `misura_aziendale` (+ `per`/`periodo`) al
  posto di `vista`/`misura`/`filtri`. La specifica salvata tiene il nome della misura, così il grafico in Analisi e la
  pagina dell'artifact si ricalcolano con la definizione di oggi.
- **`aggrega_record`** e **`grafico`**: nuovi `ordina` (`valore` o `-valore`) e `primi` (N, con il resto in «Altro» nei
  grafici); **`tabella`**: `per` + `misura` per una tabella raggruppata. Sono i tre errori del 12 novembre.

### 4. Il prompt

Nel prompt di sistema, dopo le regole, un blocco «Misure aziendali» generato dal registro: una riga per misura
(`fatturazione.fatturato` — Fatturato: definizione; sinonimi; si raggruppa per ...). Cambia solo con i moduli
installati, quindi la cache del prefisso regge. Regole nuove:

- per le domande su una misura dell'elenco usa `misura` (o `grafico`/`previsione` con `misura_aziendale`), senza
  `elenco_viste` né `descrivi_vista`, e non ricostruirla con `aggrega_record`;
- riporta la definizione in mezza frase la prima volta («fatturato, cioè imponibile delle fatture emesse...»).

Le misure che l'utente non può leggere (permesso di vista mancante) non compaiono nel suo prompt? No: il prompt deve
restare uguale per tutti per la cache. Compaiono tutte quelle dei moduli installati, e lo strumento rifiuta con un
messaggio chiaro. [scelta mia]

### 5. Numeri controllabili

Nella provenienza sotto la risposta (`ai/provenienza.py`, `_provenienza.html`), un blocco «Numeri usati» calcolato dal
codice dai risultati di `misura` del turno: etichetta, valore, periodo, definizione, link «apri i record». Il modello
non lo scrive e non lo può alterare. La guardia sui numeri esistente resta: un numero della risposta che non compare
nei dati letti continua a essere segnalato.

### 6. Velocità

Oltre ai passi risparmiati dalle misure:

- i nuovi `ordina`/`primi` tolgono i giri di errori;
- `ai_eval` riporta per ogni domanda anche il numero di passi del modello (oggi riporta secondi e costo) e una riga di
  riepilogo con mediana e 90 % dei secondi;
- nessun cambio di modello nel codice: per le demo il profilo consigliato è Haiku 5.5 come «Veloce» (configurazione,
  scritta nel README).

### 7. Domande d'oro da demo

Una ventina di domande nuove in `addons/ai/valutazione/domande.json` sulle sei aree (fatturato dell'anno e del mese,
confronto con l'anno prima, primi 5 clienti, fatturato per mese in grafico, previsione a 3 mesi, scaduto, ordini
confermati del mese, preventivi aperti, prodotti sotto scorta, appuntamenti di domani...), con due controlli nuovi:

- `misura`: `{nome, periodo, ...}`; la valutazione calcola il valore vero con `core.misure.calcola` e controlla che la
  risposta lo contenga (formato italiano, arrotondamenti tollerati entro l'unità);
- `passi_massimi`: oltre, la domanda è segnata lenta.

`ai_eval --modello <id>` (se non c'è già) per far girare le stesse domande su ciascun modello configurato: il criterio
di successo è che tutti diano lo stesso numero.

## Criteri di successo

- Le domande d'oro da demo passano con Haiku 5.5, Mistral Medium 3.5 e GLM flash, con lo stesso numero per ciascuna.
- Fatturato del mese in dashboard = fatturato del mese di Ada, verificato da un test.
- Mediana ≤ 5 s e 90 % ≤ 12 s sulle domande d'oro da demo con Haiku 5.5, sull'istanza di sviluppo.
- Nessuna domanda d'oro esistente peggiora.

## Decisioni prese dopo la revisione [scelte mie]

- **Campi nascosti e dashboard.** La misura passa da `aggrega` con `controlla_nascosti`. Se il ruolo non vede
  `imponibile`, la scheda della dashboard mostra «non disponibile» invece del numero. Oggi lo vede perché
  `core.dashboard.queryset` non controlla i campi nascosti: era una falla, non un comportamento da conservare (vedi gli
  anti-obiettivi). Il test «dashboard = Ada» gira con un ruolo che vede tutto.
- **Periodo dei grafici salvati.** La specifica salva il periodo come l'utente l'ha detto. «Quest'anno» e «ultimi 12
  mesi» restano relativi, come i KPI di Analisi di oggi, e a gennaio passano all'anno nuovo. «2026» o «da marzo a
  giugno» diventano `dal`/`al` fissi. Il titolo segue: «Fatturato dell'anno in corso» oppure «Fatturato 2026».
- **Connettore verso le chat esterne.** Lo strumento `misura` entra anche nell'elenco di `connettore_ai/catalogo.py`,
  togliendo `aziende` come si fa già per `aggrega_record`, con il suo test. Senza, Claude e ChatGPT continuerebbero a
  ricostruire il fatturato a modo loro.
- **Modelli per i criteri di successo.** Haiku 5.5, Mistral Medium 3.5 e GLM flash hanno già risposto in chat
  sull'istanza di sviluppo questo mese, quindi hanno modello e chiave configurati. `ai_eval --modello` accetta l'`id_api`
  del modello. Se una chiave non funziona più il giorno della prova, quel modello si salta e si dice.
- **Appuntamenti.** Di default sono quelli dell'utente (organizzatore o partecipante), perché «quanti appuntamenti ho»
  vuol dire i miei. Con `di: "tutti"` diventano tutti quelli che vede. Serve un filtro sull'utente che chiede, che le
  componenti statiche `{vista, misura, filtri}` non esprimono: le componenti possono usare il segnaposto `"@utente"`
  nei filtri, sostituito al momento del calcolo.

## Lasciato a chi costruisce

- Struttura interna del registro, nomi delle classi, dove vive il codice di somma per gruppi delle componenti.
- Il raggruppamento `prodotto` del fatturato (servono le righe delle fatture con il segno delle note di credito): se
  complica troppo, si rimanda e si scrive tra i limiti.
- Il formato esatto del blocco «Numeri usati» nella provenienza, nello stile di quella attuale.
- Il link della lista filtrata per le misure con più componenti.
- Le domande d'oro esatte, entro le aree sopra.
