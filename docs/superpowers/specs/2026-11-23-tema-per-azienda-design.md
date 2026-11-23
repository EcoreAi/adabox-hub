# Tema per azienda

Data: 2026-11-23 · Dimensione: grande · Richiesta 6 del team Zen Park («Richieste al team di adabox-hub»): sulla stessa
istanza due aziende dello stesso titolare, Zen Park e IEM, ognuna con nome, logo, colori e **template** suoi.

Risposte del team Zen Park (2026-11-23): un tema per azienda basta; per l'app installata un nome neutro, per ora;
nessun dominio finché sono in sviluppo (arriverà con lo stage); le differenze tra i due rami vanno in **template
diversi**, perché ognuno dei due moduli potrebbe essere venduto ad altre aziende; le email interne con il nome
dell'istanza vanno bene.

## Oggi

- `theme.Tema`: CSS (o foglio statico), logo, colore della barra. **Uno solo attivo** per l'istanza (vincolo
  `un_solo_tema_attivo`); lo staff può vederne un altro in anteprima (`SESSIONE_ANTEPRIMA`).
- Il nome del prodotto è `settings.THEME["brand"]`, dal `.env`: titolo di ogni pagina (`{{ theme.brand }}`, 191 punti
  nei template), manifest dell'app installata, 18 punti in Python (oggetto delle email, notifiche, report, calendario).
- `favicon`, `icona` e `manifest` non guardano la richiesta e hanno una cache lunga.
- Le pagine senza login (`theme/base_pubblica.html`: 11 pagine in Vendite, Pagamenti, Helpdesk, Calendario, Acquisti)
  non hanno un'azienda corrente, anche quando il documento che mostrano ce l'ha.
- `TEMA_APP` (un'app che sostituisce template e statici del tema) è una sola per l'istanza.

## Cosa cambia

### 1. Il tema dell'azienda

- Nuovo campo **`Azienda.tema`** (facoltativo, verso `theme.Tema`), nella scheda dell'azienda, sezione «Aspetto».
- Il tema della richiesta si sceglie in quest'ordine:
  1. il tema in anteprima, per lo staff che l'ha chiesta (come oggi);
  2. nelle pagine pubbliche, il tema dell'**azienda del documento** (vedi 4);
  3. il tema dell'**azienda corrente** (`request.azienda`), se ne ha uno;
  4. il tema attivo, come oggi (anche per login e recupero password, che non hanno un'azienda); senza temi, l'aspetto
     di base.
- Il tema «attivo» resta: è il tema di chi non ne ha uno proprio. Un'azienda senza tema non cambia nulla.
- Cambiando azienda dal selettore cambiano subito template, fogli di stile, logo, nome e colore della barra.

### 2. Il nome del prodotto nel tema

- Nuovo campo **`Tema.marchio`** (vuoto = `THEME["brand"]`). Il context processor lo mette in `theme.brand`: i 191 punti
  dei template non si toccano.
- In Python una funzione sola, `theme.marchio(azienda)`, al posto di `settings.THEME.get("brand")` dove l'email parte
  per conto di un'azienda: `modelli_email` (campo `marchio` e oggetto), notifiche e menzioni del chatter (azienda del
  record), conferme delle prenotazioni del Calendario (che oggi non usano nemmeno il mittente dell'azienda della #9: si
  sistema insieme). Le email interne all'istanza (attività del giorno, esportazioni, report pianificati, due fattori,
  recupero password) restano con il nome dell'istanza.

### 3. Template del tema

- Nuovo campo **`Tema.template`**: il pacchetto Python di un modulo attivo che porta i suoi template, es.
  `zenpark.tema` (cartella `addons/zenpark/tema/templates/`), nella stessa forma di `TEMA_APP`. Per le aziende con quel
  tema quei template vengono **prima** di tutti gli altri: header, logo, login, pagine pubbliche, qualunque template il
  modulo voglia sostituire. È il `TEMA_APP` di oggi, ma per tema invece che per istanza.
- Così la grafica di Zen Park viaggia con il modulo `zenpark` e quella di IEM con `iem`: se uno dei due si vende a
  un'altra azienda, quella crea un tema che punta a `iem.tema` (o lo crea l'hook di installazione del modulo).
- Si accettano solo pacchetti dentro un modulo attivo, con una cartella `templates`: i template sono codice, e
  dall'admin non se ne caricano.
- Gli statici del tema stanno negli statici del modulo (`addons/zenpark/static/zenpark/...`), che `collectstatic`
  raccoglie già perché il modulo è installato.
- Un loader dei template nuovo, primo della lista, cerca prima nel pacchetto del tema della richiesta (lo fissa un
  middleware dopo quello dell'azienda); la sua cache distingue i temi. Senza tema con template, o fuori da una
  richiesta (worker, email), tutto come oggi.
- `TEMA_APP` resta: vale per tutta l'istanza, e `Tema.template` viene prima di lui.

### Favicon, icone e manifest

- La **favicon** della scheda segue il tema dell'azienda: il logo del tema se ce l'ha, altrimenti
  `theme/partials/_favicon.svg` (anche dai template del tema). Il link porta il tema (`?t=<pk>.<versione>`) e la vista
  lo sceglie da lì, così la cache pubblica non mescola le aziende. Il `{% if request %}` in `_logo.html` non serve più.
- **Icone e manifest dell'app installata restano dell'istanza** (nome neutro, scelta del team): il browser installa
  un'app sola per dominio e non la cambierebbe passando da un'azienda all'altra. Se ne riparla con il dominio.

### 4. Pagine pubbliche con il tema dell'azienda del documento

- Una funzione `theme.per_azienda(request, azienda)`, chiamata dalla vista prima del render (es. con
  `ordine.azienda`). Imposta un attributo solo per il tema (`request.azienda_tema`), non `request.azienda`: le pagine
  pubbliche non cambiano comportamento. Vale anche per i template: il preventivo online di IEM usa i template di
  `iem.tema`.
- Le 11 pagine di `base_pubblica.html` la usano tutte: preventivo online, pagamento ed esito, guida e valutazione
  dell'Helpdesk, prenotazione del Calendario, pagina del fornitore negli Acquisti.

## Modelli e migrazioni

- `theme`: `Tema.marchio`, `Tema.template`.
- `core`: `Azienda.tema` (`SET_NULL`). `theme` non dipende da `core`, quindi niente cicli.
- Kernel minore nuovo; nessun dato da convertire: senza temi assegnati tutto resta com'è.

## Test

- Due aziende con temi diversi: cambiando azienda dal selettore cambiano fogli, logo, `theme.brand` e `theme_color`.
- Con un tema che ha `template = "<modulo>.tema"`, una pagina dell'azienda usa il template del modulo e una pagina
  dell'altra azienda quello standard, nella stessa istanza e con la cache dei template accesa.
- Un `Tema.template` fuori da un modulo attivo non si salva.
- Un'azienda senza tema prende il tema attivo; senza temi, l'aspetto di base.
- Il preventivo online di un ordine dell'azienda B esce con il tema (e i template) di B anche per un anonimo, e la
  pagina si comporta come prima.
- L'anteprima dello staff vince su tutto.
- La favicon con `?t=` resta quella di quel tema anche con la sessione di un'altra azienda.
- Le email di un modello (`modelli_email`) dell'azienda B hanno il marchio di B; quelle interne il nome dell'istanza.

## Fuori

Tema dal dominio e `SITO_URL` per azienda (con il dominio dello stage), icone e nome dell'app installata per azienda,
temi per dipartimento o per persona, stampe PDF (già per azienda con i modelli di stampa), email interne con il
marchio dell'azienda.
