# Grafici cliccabili: dal numero ai record

Data: 2026-11-19 · Dimensione: piccola modifica (design breve)

## Perché

Nelle demo di Ada chi guarda un grafico deve poter cliccare una barra, un punto o una fetta e vedere i record che
formano quel numero. È la prova che il numero non è inventato. Fa parte del potenziamento di Ada per le demo
(«grafici e dashboard interattivi»); questo è il primo pezzo.

## Com'è oggi

- **Analisi** (`addons/grafici`) disegna i grafici salvati con Chart.js (`core/static/core/grafici.js`) e ha già il
  clic: `grafici.motore.link_lista` costruisce l'elenco filtrato sul gruppo a partire dalla «chiave» di ogni punto.
- I grafici sulle **misure aziendali** (fatturato per mese, da incassare per cliente…) non sono cliccabili da nessuna
  parte. `core.misure.calcola` prepara già un link giusto per ogni gruppo (con il periodo e i filtri della misura:
  bozze escluse, note di credito…), ma `misure.serie` lo scarta.
- In **chat** il grafico è un SVG disegnato dal server (`core/svg.py`, `ai.artifact.svg_di`): nessun clic, e il
  valore compare solo come suggerimento nativo, in ritardo. Le tabelle in chat hanno già il link per riga.

## Obiettivi

1. In chat i grafici (barre, linee, torta) si disegnano con lo stesso script di Analisi: valore subito al passaggio
   del mouse, stesso aspetto in chat, nella pagina del grafico e in Analisi.
2. Ogni punto che corrisponde a un insieme preciso di record è cliccabile e apre l'elenco filtrato su quei record:
   per i grafici sulle viste (campo o data) e per quelli sulle misure aziendali.
3. Le misure aziendali diventano cliccabili anche in Analisi.

## Fuori da questo lavoro

- Periodo e filtri sul grafico, dashboard fatte da Ada, tabelle modificabili: pezzi successivi.
- Tipi di grafico nuovi in chat (restano barre, linee, torta; le previsioni restano come sono, senza clic).
- Parla con Ada (non mostra grafici). Il PDF e il CSV dei grafici restano uguali.

## Da evitare

- **Un link che mostra record diversi dal numero è peggio di nessun link.** Se il filtro non si può esprimere
  nell'elenco (fetta «Altro», campo che l'elenco non filtra, misura calcolata «situazione di oggi», previsione), quel
  punto non è cliccabile e non mostra la manina. È la regola che Analisi e le misure applicano già.
- Nessun codice del modello eseguito nel browser: lo script riceve solo etichette, valori e link calcolati dal server.

## Approcci considerati

- **A. Link dentro l'SVG di oggi**: ogni barra, punto o fetta diventa un `<a>`. Lavoro minimo, aspetto invariato; restano
  il valore in ritardo e due stili diversi tra chat e Analisi.
- **B. In chat lo stesso grafico di Analisi** (Chart.js con `grafici.js`): già cliccabile, valore immediato, un solo
  aspetto, e il passo dopo (periodo e filtri) si costruisce sopra. Costa di più: va avviato anche sui grafici che
  arrivano a fine risposta e su quelli aggiornati con ↻.

**Scelto B** dall'utente il 2026-11-19.

## Decisioni

- **Dove porta il clic** (scelta mia): dalla chat e dalla pagina del grafico l'elenco si apre in una scheda nuova, così
  la conversazione resta lì. In Analisi il clic resta come oggi, nella stessa scheda.
- **Un solo costruttore dei link**, nel kernel, usato da chat e Analisi: il modulo AI non deve dipendere da Analisi.
  Per le misure si usa il link per gruppo di `misure.calcola`, che conosce i filtri della misura.
- **I link si calcolano insieme ai dati** e si salvano con l'istantanea; ↻ li rifà. I grafici già esistenti in chat,
  salvati senza le chiavi, restano non cliccabili finché non si aggiornano: non si ricalcola nulla da soli.
- **L'SVG del server resta** come ripiego senza JavaScript (`<noscript>`, come in `core/templates/core/vista/grafico.html`)
  e per il PDF.
- L'elenco aperto mostra ciò che può vedere chi clicca: in un grafico condiviso il conteggio può differire da quello
  del proprietario. È lo stesso comportamento di Analisi; non lo cambio.

## Lasciato a chi costruisce

- Dove spostare `link_lista` nel kernel e come chiamarlo; come far passare a `grafici.js` «apri in una scheda nuova»
  (un attributo sul canvas o un campo della serie).
- Altezza del grafico in chat (oggi l'SVG è 720×320) e in pagina; dove avviare `grafici.js` dopo l'arrivo della
  risposta (`chat.js`, evento `fine`) e dopo ↻ (`htmx:afterSettle` lo fa già).
- Test: link per i grafici sulle viste e sulle misure (compresi i casi senza link), pagina della chat con il canvas e
  i dati, prova dello script con jsdom (vedi la nota della memoria sulla prova senza browser).
