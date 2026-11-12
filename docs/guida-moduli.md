# Sviluppare un modulo per adabox-hub

Un modulo è un'app Django in `addons/<slug>/` con un `__manifest__.py`. Il kernel gli dà pagine, permessi, API, webhook, chatter e accesso da Ada, e il modulo si vende e si installa da solo o accanto agli altri.

## Da zero alla consegna

```bash
python manage.py modulo nuovo bolle --nome "Bolle" --modello Bolla   # crea il modulo, già funzionante
python manage.py modulo installa bolle                               # lo attiva nella tua istanza
# scrivi modelli e logica; dopo ogni modifica ai modelli: makemigrations bolle
python manage.py modulo controlla bolle                              # le regole, lette dal codice
python manage.py modulo collauda bolle                               # installazione, migrazioni, test, disinstallazione
python manage.py modulo compatibilita bolle                          # accanto a ogni altro modulo e a tutti insieme
python manage.py modulo impacchetta bolle --firma ~/chiavi/moduli.pem   # il pacchetto da consegnare
```

Se il modulo dipende da altri: `modulo nuovo bolle --dipende contatti`.

## Le regole

1. **Ogni dato ha un'azienda.** Il modello eredita `AziendaMixin` e la vista dichiara `company_field = "azienda"`. Un modello figlio, come una riga di documento, senza azienda propria si filtra in `get_queryset` sull'azienda del padre.
2. **Senza azienda corrente non si vede nulla.** `request.azienda` può essere `None`: si restituisce `qs.none()`, mai tutto.
3. **Si legge da `queryset(request, Modello)`** di `core.dashboard`, non da `Modello.objects`, nelle pagine scritte a mano. Applica azienda e permessi come la lista. Vale per ogni `pk` che arriva dall'URL.
4. **Ogni dato passa da una `ModelView`.** Da lì nascono pagine, permessi, API e accesso di Ada. Ciò che ne resta fuori, Ada non lo vede.
5. **Gli altri moduli si dichiarano.** In `depends` se servono sempre; altrimenti con `apps.is_installed("crm")` e l'import dentro la funzione, così il modulo funziona anche senza.
6. **I segreti sono cifrati** con `core.cifratura`, si scrivono in un modulo e non si rileggono nelle pagine.
7. **Le chiamate verso indirizzi decisi da un utente passano da `core.rete`**, che blocca la rete interna. La rete sta fuori dalle transazioni: lavoro in background con `core.lavori` e `senza_transazione = True`.
8. **Una pagina senza login è una scelta**, e un endpoint senza CSRF deve verificare una firma.
9. **Gli indirizzi alla radice sono un'eccezione.** `urlpatterns_radice` in `urls.py` serve solo quando il percorso lo fissa uno standard (`/.well-known/…`): lì i middleware dei moduli non arrivano, e la vista risponde 404 da sé quando il modulo è spento.

Una pagina di amministrazione dell'istanza che mostra tutte le aziende di proposito lo dichiara con `tra_aziende = True`.

## Ada

Con una `ModelView` non serve altro: Ada elenca, cerca, legge e aggrega i dati, e propone creazioni e modifiche che l'utente deve confermare. Vede solo ciò che l'utente vede.

- **`ai_descrizione` è da scrivere davvero.** Di ogni vista Ada riceve solo il nome e questa frase, e con molti moduli installati sceglie da lì. Nella prova su un'istanza con 93 viste, «quante bolle abbiamo?» finiva sui ricevimenti di Magazzino finché la vista non ha detto di contenere le bolle. Esempio: `ai_descrizione = "Le bolle di accompagnamento lette con l'OCR: numero, fornitore, data, totale. Gli utenti dicono bolla o DDT."`
- `list_display` e `search_fields` decidono cosa trova.
- I bottoni sono azioni per Ada: `ai = False` li nasconde (download, stampe), `rischio = "irreversibile"` li segnala.

Per un'operazione specifica si aggiunge uno strumento, caricato solo se il modulo `ai` è installato. Nel manifest `"ai": "bolle.ai"` e in `bolle/ai.py`:

```python
from ai.strumenti import Strumento, registra


def rileggi(contesto, id):
    ...  # contesto.utente e contesto.azienda: i permessi si controllano sempre
    return {"esito": "ok"}


registra(Strumento("bolle_rileggi", "Rilegge una bolla con l'OCR.",
                   {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
                   rileggi, permesso="bolle.change_bolla"))
```

## Mandare i dati a un altro software

Con `api = True` sulla vista e il modulo Connettori installato, un webhook sull'evento `bolle.bolla.creato` avvisa il software del cliente con un messaggio firmato. Dall'altra parte c'è anche l'API: `/api/v1/bolle/bolle/`, con token.

## Portare in adabox un progetto Django esistente

1. Crea il modulo con `modulo nuovo` e copia dentro modelli e logica, separando la logica dalle viste.
2. Aggiungi `AziendaMixin` a tutti i modelli. Sui dati esistenti serve una migrazione con un valore di azienda, in due passi: campo facoltativo, riempimento, campo obbligatorio.
3. Sostituisci `User` con il modello utente del progetto e i permessi su misura con i gruppi del manifest.
4. Sostituisci liste e form CRUD con una `ModelView`. Le pagine davvero speciali restano in `urls.py` e usano `core/base_app.html` come template.
5. Sostituisci Celery o simili con `core.lavori` e le voci `cron` del manifest; i segreti in chiaro con `core.cifratura`.
6. Sposta l'importazione dei dati in un comando separato, da provare su una copia. `modulo impacchetta` non porta i dati.
7. Chiudi con `controlla`, `collauda` e `compatibilita`.

## Moduli di un solo cliente

`modulo nuovo` crea moduli su misura: nel manifest c'è `"su_misura": True`. Per un modulo da catalogo, valido per tutti i clienti: `modulo nuovo crm2 --standard`.

Un modulo su misura non va nel repository di adabox. Tienilo in un repository suo e collegalo per sviluppare:

```bash
ln -s ~/progetti/cliente-x/bolle addons/bolle
```

`addons/installed.json` non è versionato, quindi l'installazione resta locale.

Si consegna dal portale, che deve vedere il modulo in `addons/`:

```bash
python manage.py rivendita_pubblica bolle --per "Rossi Srl"    # oppure il codice dell'istanza, se il nome non è unico
```

Il modulo compare solo nella licenza di quell'istanza, e arriva entro un'ora o con «Sincronizza ora». Agli altri clienti non appare nel catalogo, non si può mettere in un piano e il pacchetto non si scarica. Per darlo a un secondo cliente si aggiunge ai suoi moduli in più, dalla sua istanza sul portale.

## Limiti del kit

- `controlla` legge il codice senza eseguirlo: non vede ciò che passa da funzioni di altri file e dà qualche falso avviso. Non sostituisce i test né la revisione.
- `compatibilita` apre le pagine dei menu su un'istanza con pochi dati e accesso da superuser: trova conflitti di installazione ed errori di pagina, non errori di logica.
