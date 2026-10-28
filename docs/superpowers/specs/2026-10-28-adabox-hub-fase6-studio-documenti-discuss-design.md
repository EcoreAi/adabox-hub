# adabox-hub — fase 6: Studio, Documenti, Discuss

Data: 2026-10-28
Stato: approvato (l'utente ha chiesto di procedere; decisioni prese qui e motivate)
Precede: fasi 1-5

## Scopo

Le tre app trasversali della roadmap, che servono a tutte le altre:

- **Studio**: il cliente adatta le viste senza programmare (colonne, filtri, raggruppamenti, layout del form,
  etichette, campi nuovi), con storico e ripristino, ed esporta le personalizzazioni da un'istanza all'altra.
- **Documenti**: archivio di file per cartelle con permessi, tag, anteprima, condivisione con link pubblico a
  scadenza, richieste di documenti, cartelle collegate ai modelli che raccolgono gli allegati dei record.
- **Discuss**: messaggistica interna (canali e messaggi diretti), menzioni, posta in arrivo con le notifiche del
  chatter, contatore dei non letti in testata, email per chi non legge.

Riferimento funzionale: Odoo 19 (Studio, Documents, Discuss). Si riproducono funzionalità e flussi, non codice né
testi.

## Decisioni

1. **Tre app** (`studio`, `documenti`, `discuss`), nessuna dipendenza dalle app di business. Il kernel riceve solo
   i punti di aggancio generici (decisioni 2 e 9), utili anche ad altri moduli.
2. **Personalizzazione delle viste nel kernel come hook**: `core.viste.personalizza.registra(funzione)`;
   `funzione(vista, request)` restituisce un dizionario di attributi da sovrascrivere. All'inizio di ogni richiesta
   `VistaBase` sostituisce la vista con `vista.personalizzata(request)`, una copia superficiale con gli attributi
   sovrascritti. La `ModelView` resta un singleton immutabile: nessun effetto tra richieste o thread. Attributi
   ammessi: `list_display`, `list_filter`, `search_fields`, `list_group_by`, `list_sum`, `ordering`, `per_page`,
   `form_layout`, `kanban_fields` e `etichette` (nuovo: `{campo: etichetta}` usato da `etichetta()` e dal form).
3. **Studio salva una `Personalizzazione` per vista** (modulo + slug), valida per tutte le aziende:
   l'adattamento riguarda l'istanza, mentre i campi personalizzati per azienda esistono già. JSON validato al
   salvataggio contro i campi reali; a runtime si scartano i nomi che non esistono più, perché un aggiornamento
   del modulo può togliere un campo. Studio li segnala come "non più esistenti". I campi obbligatori senza
   default non si possono togliere dal form.
4. **Storico**: ogni salvataggio conserva la versione precedente (ultime 20, con autore e data); si ripristina una
   versione o si torna all'originale del modulo. **Esporta/importa** tutte le personalizzazioni in JSON, per
   passarle dall'istanza di prova alla produzione. L'importazione salta le viste che non esistono.
5. **Campi nuovi da Studio**: crea un `CampoPersonalizzato` del kernel per il modello e lo inserisce subito nel
   form, ed eventualmente nella lista. Nei layout si possono collocare i singoli `prop_<nome>`, oltre al blocco
   `@proprieta`: il kernel lo supporta in form, dettaglio e lista.
6. **Editor di Studio**: una pagina per vista con le schede Lista, Form, Kanban e Campi. Gli elenchi si
   ordinano trascinando, con JavaScript nativo (HTML5 drag and drop) e i bottoni su/giù come alternativa da
   tastiera. Il form invia un JSON in un campo nascosto. Solo superuser e gruppo "Studio / Amministratore".
7. **Documenti**:
   - `Cartella` ad albero, per azienda, con gruppi in lettura e in scrittura (vuoti = tutti gli utenti dell'app)
     e un modello collegato opzionale.
   - `Documento`: file privato oppure riferimento a un allegato del kernel; tag, proprietario, record collegato,
     blocco, cestino.
   - `Tag`, `Condivisione` e `Richiesta`.
   - I file passano dallo storage privato del kernel (X-Accel in produzione). L'anteprima mostra immagini e PDF
     inline e un'icona per gli altri tipi.
8. **Collegamento con gli allegati**: una cartella collegata a un modello (es. "Fatture" ↔ `fatturazione.Fattura`)
   riceve un `Documento` per ogni allegato caricato sui record di quel modello (segnale `post_save` su
   `core.Allegato`). Il documento punta all'allegato senza copiare il file; i permessi sono quelli della
   cartella. Sul dettaglio dei record c'è la sezione "Documenti".
9. **Condivisione pubblica**: link con token casuale, scadenza obbligatoria e opzione di caricamento. È una pagina
   senza login con solo i documenti condivisi, con limite di frequenza (django-axes non si applica: limitatore
   per IP in cache) e ogni accesso registrato. Una **richiesta di documento** a un utente crea un'attività
   pianificata del kernel; il caricamento dalla richiesta la chiude.
10. **Discuss**:
    - `Canale` di tipo pubblico, privato o diretto (due o più utenti), con `Iscrizione` (ultimo messaggio letto,
      notifiche: tutto / solo menzioni / niente);
    - `Messaggio` con testo leggero (escape, a capo, link, **grassetto**, `@utente`), allegati del kernel, modifica
      ed eliminazione dei propri messaggi;
    - niente websocket, perché lo stack è gunicorn sincrono: la conversazione aperta interroga il server ogni 3
      secondi con HTMX (solo i messaggi dopo l'ultimo id) e il contatore in testata ogni 30 secondi.
11. **Posta in arrivo** (`Notifica`): menzioni in Discuss e nel chatter, messaggi diretti, messaggi del chatter sui
    record seguiti (il kernel già li manda per email ai follower). La notifica porta al record o al canale. Una
    pianificazione ogni 10 minuti manda per email le menzioni e i messaggi diretti non letti da più di 15 minuti,
    una volta sola per notifica.
12. **Testata**: nuovo hook del kernel `hooks.voce_testata(template, order, permission)` per gli elementi della
    barra in alto, usato da Discuss per l'icona con il contatore. La chat AI resta com'è: Discuss è
    messaggistica tra persone.

## Le app in breve

| App | Modelli | Funzioni principali |
|---|---|---|
| studio | Personalizzazione | editor di lista/form/kanban/etichette, campi nuovi, storico, esporta/importa |
| documenti | Cartella, Tag, Documento, Condivisione, Richiesta | albero, caricamento multiplo, anteprima, tag, sposta, cestino, zip, link pubblici, richieste, cartelle per modello |
| discuss | Canale, Iscrizione, Messaggio, Notifica | canali e messaggi diretti, non letti, menzioni, posta in arrivo, email di riepilogo |

Ogni app: manifest, gruppi, dashboard, demo, test, collaudo.

## Fuori scope

- **Studio**: nuovi modelli o app, report, automazioni, viste in DB per le pagine non `ModelView`.
- **Documenti**: firma, OCR, versioni dei file, editing online.
- **Discuss**: chiamate audio e video, websocket, thread nei messaggi, reazioni, bot, canali verso l'esterno
  (livechat).
