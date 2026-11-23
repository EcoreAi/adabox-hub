# Tema per azienda

Data: 2026-11-23 · Dimensione: grande · Richiesta 6 del team Zen Park («Richieste al team di adabox-hub»): sulla stessa
istanza due aziende dello stesso titolare, Zen Park e IEM, ognuna con nome, logo, colori e icone suoi. Documento da
rivedere con loro prima di scrivere il codice: le domande sono in fondo.

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

- Nuovo campo **`Azienda.tema`** (facoltativo, verso `theme.Tema`), nella scheda dell'azienda sotto «Aspetto».
- Il tema della richiesta si sceglie in quest'ordine:
  1. il tema in anteprima, per lo staff che l'ha chiesta (come oggi);
  2. il tema dell'**azienda corrente** (`request.azienda`), se ne ha uno;
  3. nelle pagine pubbliche, il tema dell'**azienda del documento** (vedi 4);
  4. il tema del **dominio**, solo senza azienda (login, recupero password, errori; vedi 5);
  5. il tema attivo, come oggi; senza temi, l'aspetto di base.
- Il tema «attivo» resta: è il tema di chi non ne ha uno proprio. Un'azienda senza tema non cambia nulla.
- Cambiando azienda dal selettore cambiano subito fogli di stile, logo, nome e colore della barra.

### 2. Il nome del prodotto nel tema

- Nuovo campo **`Tema.marchio`** (vuoto = `THEME["brand"]`). Il context processor lo mette in `theme.brand`: i 191 punti
  dei template non si toccano.
- In Python una funzione sola, `theme.marchio(azienda=None)`, al posto di `settings.THEME.get("brand")` dove l'email
  parte per conto di un'azienda: `modelli_email` (campo `marchio` e oggetto), notifiche e menzioni del chatter (azienda
  del record), conferme delle prenotazioni del Calendario (che oggi non usano nemmeno il mittente dell'azienda della
  #9: si sistema insieme). Le email interne all'istanza (attività del giorno,
  esportazioni, report pianificati, due fattori, recupero password) restano con il nome dell'istanza.

### 3. Favicon, icone e manifest dal tema

- La favicon è il logo del tema, se ce l'ha; altrimenti `theme/partials/_favicon.svg` come oggi. Sparisce il
  `{% if request %}` che oggi serve in `_logo.html` per distinguere i due casi.
- Nuovo campo **`Tema.icona`** (un PNG quadrato di almeno 512 px, caricato dall'admin): le tre icone 180/192/512 si
  ricavano con Pillow. Senza icona: `theme/icona-<lato>.png` tra gli statici (TEMA_APP), poi il cubo disegnato.
- `theme_color` del manifest: `Tema.colore_barra`, come già per la barra del browser.
- **Cache**: i link a favicon, icone e manifest portano il tema e la sua versione (`?t=<pk>.<versione>`); le viste
  scelgono il tema da lì e non dalla sessione. Così restano in cache pubblica a lungo e non si mescolano tra aziende.

### 4. Pagine pubbliche con il tema dell'azienda del documento

- Una funzione `theme.per_azienda(request, azienda)`, chiamata dalla vista prima del render (es. con
  `ordine.azienda`). Imposta un attributo solo per il tema (`request.azienda_tema`), non `request.azienda`: le pagine
  pubbliche non cambiano comportamento.
- Le 11 pagine di `base_pubblica.html` la usano tutte: preventivo online, pagamento ed esito, guida e valutazione
  dell'Helpdesk, prenotazione del Calendario, pagina del fornitore negli Acquisti.

### 5. Il tema dal dominio (facoltativo)

- Nuovo campo **`Tema.domini`** (uno per riga, es. `iem.esempio.it`). Vale solo dove non c'è un'azienda: login,
  recupero password, pagine d'errore. Dopo il login vince l'azienda corrente.
- Lavoro di sistema a parte: DNS, certificato (Caddy), `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS`.
- Limite: i link nelle email usano `SITO_URL`, che è uno per istanza. Con due domini un cliente IEM riceverebbe link al
  dominio di Zen Park (funzionano, ma con il dominio sbagliato). Un `SITO_URL` per azienda è fuori da questo lavoro.

## L'app installata

Il browser installa **un'app per dominio**: nome e icona si fissano all'installazione e si aggiornano di rado. Con un
solo dominio, l'app installata prende il tema dell'azienda corrente al momento dell'installazione e non cambia quando si
passa all'altra azienda. Per avere due app con nomi e icone distinti servono due domini (punto 5). Il manifest avrà un
`id` fisso, così cambiare tema non crea un'app «nuova».

## Che cosa resta in TEMA_APP

`TEMA_APP` resta una per istanza: template diversi per azienda non ci sono. Le differenze tra i due rami vanno nel tema
(CSS con i token, logo, marchio, icona, colore). Gli header e il login sostituiti in `addons/zenpark/tema` possono
restare, ma devono leggere logo e nome da `theme.tema` e `theme.brand`, non scriverli nel template.

## Modelli e migrazioni

- `theme`: `Tema.marchio`, `Tema.icona` (+ tipo), `Tema.domini`.
- `core`: `Azienda.tema` (`SET_NULL`). `theme` non dipende da `core`, quindi niente cicli.
- Kernel minore nuovo; nessun dato da convertire: senza temi assegnati tutto resta com'è.

## Test

- Due aziende con temi diversi: cambiando azienda dal selettore cambiano fogli, logo, `theme.brand` e `theme_color`.
- Un'azienda senza tema prende il tema attivo; senza temi, l'aspetto di base.
- Il preventivo online di un ordine dell'azienda B esce con il tema di B anche per un anonimo, e la pagina si comporta
  come prima.
- L'anteprima dello staff vince su tutto.
- Favicon, icone e manifest con `?t=` restano quelli di quel tema anche con la sessione di un'altra azienda.
- Le email di un modello (`modelli_email`) dell'azienda B hanno il marchio di B; quelle interne il nome dell'istanza.
- Login su `iem.esempio.it` con il tema di IEM; dopo il login vince l'azienda corrente.

## Fuori

Template diversi per azienda (TEMA_APP per azienda), `SITO_URL` per azienda, temi per dipartimento o per persona,
stampe PDF (già per azienda con i modelli di stampa), email interne con il marchio dell'azienda.

## Domande per il team Zen Park

1. Basta un tema per azienda, o vi servono temi diversi anche per dipartimento o per persona?
2. App installata: va bene un nome e un'icona neutri con un solo dominio, o userete due domini?
3. Domini (punto 5): vi servono subito? Se sì, vi servono anche i link delle email sul dominio dell'azienda
   (`SITO_URL` per azienda, oggi fuori)?
4. Le differenze tra Zen Park e IEM stanno tutte in CSS, logo, nome, icona e colore, o vi servono template diversi?
5. Email interne (attività, esportazioni, report) con il nome dell'istanza: va bene?
