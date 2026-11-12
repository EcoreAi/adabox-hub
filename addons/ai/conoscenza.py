"""La conoscenza dell'assistente: indice dei testi (record, note del chatter, documenti) e ricerca ibrida.

- Indice per azienda, permessi alla ricerca: un risultato si mostra solo se la ModelView del record d'origine lo
  fa vedere all'utente (anche le cartelle dei Documenti, che filtrano nella loro vista).
- Vettori di EmbeddingGemma 2 accorciati a 256 dimensioni (float32 nel database) dal servizio indicato in
  `ai.url_embeddings`; confronto in Python. Senza servizio resta la ricerca per parole chiave.
- L'indicizzazione è incrementale: ogni frammento ha un'impronta del testo, si ricalcola solo se cambia; i
  frammenti di record, note o documenti spariti si tolgono.
"""
import hashlib
import io
import json
import logging
import re
import time
import urllib.request
from array import array

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from .models import Frammento, IndiceDocumento

log = logging.getLogger("ai.conoscenza")

DIMENSIONI = 256
LUNGHEZZA = 1200                      # caratteri per frammento di documento
SOVRAPPOSIZIONE = 150
MAX_TESTO_RECORD = 2000
MAX_TESTO_DOCUMENTO = 400_000         # oltre, il documento si indicizza solo in parte
LOTTO = 64                            # testi per chiamata al servizio di embedding
TIMEOUT = 60
ESCLUSI = {"ai"}
# viste tecniche del kernel: coda dei lavori, email grezze, profili e definizioni dei campi (rumore o riservate)
MODELLI_ESCLUSI = {"core.registromodifica", "core.lavoro", "core.emailricevuta", "core.profiloutente", "core.campopersonalizzato"}
SENSIBILE = re.compile(r"password|chiave|token|segret|secret|cifrat|hash|iban", re.IGNORECASE)
PAROLA = re.compile(r"\w{3,}", re.UNICODE)
PAROLE_VUOTE = {"che", "per", "con", "del", "della", "delle", "dei", "degli", "dal", "dalla", "nel", "nella", "sul",
                "sulla", "una", "uno", "gli", "le", "non", "come", "cosa", "dice", "sono", "questo", "questa", "quali",
                "quale", "quanto", "tutti", "tutte", "anche", "più", "mio", "mia", "miei", "loro", "the", "and"}


# ---------- testo dai file ----------

TESTUALI = ("txt", "md", "csv", "tsv", "json", "xml", "html", "htm", "eml")
SUPPORTATI = (*TESTUALI, "pdf", "docx", "xlsx", "xlsm")


def estrai(nome, dati):
    """(pagine, esito) di un file. `pagine` è [(numero di pagina o None, testo)]: le pagine vere per i PDF, un solo
    pezzo senza numero per gli altri tipi. `esito`: "ok", "non_supportato" o "illeggibile" (file rotto o protetto)."""
    estensione = nome.lower().rsplit(".", 1)[-1] if "." in nome else ""
    if estensione not in SUPPORTATI:
        return [], "non_supportato"
    try:
        if estensione in TESTUALI:
            testo = dati.decode("utf-8", errors="replace")
            return [(None, re.sub(r"<[^>]+>", " ", testo) if estensione in ("html", "htm", "xml") else testo)], "ok"
        if estensione == "pdf":
            from pypdf import PdfReader
            return [(n, pagina.extract_text() or "") for n, pagina in enumerate(PdfReader(io.BytesIO(dati)).pages, start=1)], "ok"
        if estensione == "docx":
            import docx
            documento = docx.Document(io.BytesIO(dati))
            righe = [p.text for p in documento.paragraphs]
            for tabella in documento.tables:
                righe += [" | ".join(c.text for c in riga.cells) for riga in tabella.rows]
            return [(None, "\n".join(righe))], "ok"
        return [(None, "\n".join(" | ".join(map(str, riga)) for _, righe in fogli(dati) for riga in righe))], "ok"
    except Exception:                                  # file rotto o protetto: non si indicizza, non si blocca
        log.warning("testo non estratto da %s", nome, exc_info=True)
        return [], "illeggibile"


def testo_da_file(nome, dati, segna_pagine=False):
    """Il testo di un file (txt, md, csv, PDF, Word, Excel); "" se il tipo non è supportato o il file è illeggibile.
    Con `segna_pagine` ogni pagina di un PDF comincia con «[pagina N]»."""
    pagine, _ = estrai(nome, dati)
    return "\n\n".join(f"[pagina {n}]\n{t}" if segna_pagine and n else t for n, t in pagine)


def fogli(dati, massimo=5000):
    """[(nome del foglio, [[valori]])] di un file Excel, in sola lettura."""
    from openpyxl import load_workbook
    libro = load_workbook(io.BytesIO(dati), read_only=True, data_only=True)
    risultato = []
    for foglio in libro.worksheets:
        righe = []
        for riga in foglio.iter_rows(values_only=True):
            if any(v not in (None, "") for v in riga):
                righe.append(["" if v is None else v for v in riga])
            if len(righe) >= massimo:
                break
        risultato.append((foglio.title, righe))
    libro.close()
    return risultato


def pezzi(testo, lunghezza=LUNGHEZZA, sovrapposizione=SOVRAPPOSIZIONE):
    """Il testo in pezzi di circa `lunghezza` caratteri, tagliati a fine paragrafo o frase quando si può."""
    testo = re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", testo or "")).strip()
    risultato, inizio = [], 0
    while inizio < len(testo):
        fine = min(len(testo), inizio + lunghezza)
        if fine < len(testo):
            taglio = max(testo.rfind("\n\n", inizio + lunghezza // 2, fine), testo.rfind(". ", inizio + lunghezza // 2, fine))
            if taglio > inizio:
                fine = taglio + 1
        risultato.append(testo[inizio:fine].strip())
        if fine >= len(testo):
            break
        inizio = max(fine - sovrapposizione, inizio + 1)
    return [p for p in risultato if p]


# ---------- sorgenti ----------

def _impronta(testo):
    return hashlib.sha1(testo.encode()).hexdigest()


def _viste_indicizzabili():
    from core.viste import registry
    registry.autodiscover(["core", *settings.ADDONS_ATTIVI])
    for modulo in ["core", *settings.ADDONS_ATTIVI]:
        if modulo in ESCLUSI:
            continue
        for vista in registry.viste_di(modulo):
            if vista.opts.label_lower in MODELLI_ESCLUSI:
                continue
            campi = [f for f in vista.opts.concrete_fields
                     if isinstance(f, (models.CharField, models.TextField)) and not f.choices
                     and not SENSIBILE.search(f.name)]
            if campi and not (modulo == "documenti" and vista.model.__name__ == "Documento"):
                yield vista, campi


def frammenti_record():
    """(chiave, dati del frammento) per ogni record delle ModelView con campi di testo."""
    for vista, campi in _viste_indicizzabili():
        ct = ContentType.objects.get_for_model(vista.model)
        for obj in vista.model._default_manager.all().iterator(chunk_size=500):
            yield from frammenti_di_un_record(vista, campi, ct, obj)


def frammenti_di_un_record(vista, campi, ct, obj):
    """Un frammento per record (i campi di testo, fino a MAX_TESTO_RECORD); le viste con `conoscenza_sezioni`
    (es. le pagine della wiki) danno invece quel campo per intero, un frammento per sezione."""
    azienda_id = getattr(obj, f"{vista.company_field}_id", None) if vista.company_field else None
    if getattr(vista, "conoscenza_sezioni", None):
        yield from _frammenti_a_sezioni(vista, campi, ct, obj, azienda_id)
        return
    righe = [f"{vista.verbose_name}: {obj}"]
    for f in campi:
        valore = getattr(obj, f.attname)
        if valore and str(valore) != str(obj):
            righe.append(f"{f.verbose_name}: {valore}")
    yield {"fonte": Frammento.RECORD, "content_type": ct, "object_id": obj.pk, "chiave": "", "azienda_id": azienda_id,
           "titolo": f"{str(vista.verbose_name).capitalize()} «{obj}»"[:250], "testo": "\n".join(righe)[:MAX_TESTO_RECORD]}


def _frammenti_a_sezioni(vista, campi, ct, obj, azienda_id):
    """Il campo lungo diviso ai titoli markdown; ogni frammento porta il percorso (es. «Procedure › Resi › Rimborso»),
    perché un pezzo da solo si capisca, e l'ancora della sezione nella chiave («003#rimborso»), per la citazione.
    Le sezioni lunghe si spezzano ancora come i documenti."""
    from .markdown import sezioni
    campo = vista.conoscenza_sezioni
    percorso = vista.conoscenza_percorso(obj) if hasattr(vista, "conoscenza_percorso") else [str(obj)]
    altri = [f"{f.verbose_name}: {getattr(obj, f.attname)}" for f in campi
             if f.attname != campo and getattr(obj, f.attname) and str(getattr(obj, f.attname)) != str(obj)]
    n = 0
    for titoli, ancora, testo in sezioni(getattr(obj, campo, "") or ""):
        intestazione = " › ".join([*percorso, *titoli])
        corpo = "\n".join(altri) + "\n\n" + testo if n == 0 and altri else testo
        for i, pezzo in enumerate(pezzi(corpo) or [""]):
            yield {"fonte": Frammento.RECORD, "content_type": ct, "object_id": obj.pk, "azienda_id": azienda_id,
                   "chiave": f"{n:03d}#{ancora}"[:40], "titolo": (f"{str(vista.verbose_name).capitalize()} «{intestazione}»"
                                                                  + (f", parte {i + 1}" if i else ""))[:250],
                   "testo": f"{intestazione}\n\n{pezzo}".strip()}
            n += 1


def frammenti_note():
    """Note e messaggi del chatter (non i tracciamenti né gli eventi di sistema), legati al loro record."""
    from core.models import Messaggio
    for m in (Messaggio.objects.filter(tipo__in=[Messaggio.NOTA, Messaggio.MESSAGGIO]).exclude(corpo="")
              .select_related("content_type", "autore").iterator(chunk_size=500)):
        record = m.record
        if record is None:
            continue
        autore = (m.autore.get_full_name() or m.autore.username) if m.autore else (m.autore_email or "esterno")
        yield {"fonte": Frammento.NOTA, "content_type": m.content_type, "object_id": m.object_id,
               "chiave": str(m.pk), "azienda_id": getattr(record, "azienda_id", None),
               "titolo": f"{m.get_tipo_display()} di {autore} del {m.creato:%d/%m/%Y} su «{record}»"[:250],
               "testo": m.corpo[:MAX_TESTO_RECORD]}


def frammenti_documenti():
    if "documenti" not in settings.ADDONS_ATTIVI:
        return
    from documenti.models import Documento
    ct = ContentType.objects.get_for_model(Documento)
    vivi = set()
    for d in Documento.objects.filter(cestinato_il__isnull=True).iterator(chunk_size=200):
        vivi.add(d.pk)
        yield from frammenti_di_un_documento(d, ct)
    spariti = [pk for pk in IndiceDocumento.objects.values_list("documento_id", flat=True) if pk not in vivi]
    for i in range(0, len(spariti), 500):                    # a blocchi: niente query con migliaia di parametri
        IndiceDocumento.objects.filter(documento_id__in=spariti[i:i + 500]).delete()


MAX_FILE = 20 * 1024 * 1024


def frammenti_di_un_documento(d, ct, analisi=None):
    """I frammenti di un documento (con la pagina, per i PDF) e, se c'è ed è aggiornato, il suo riassunto. Annota
    com'è andata in IndiceDocumento: chi carica una scansione senza testo lo vede nella scheda del documento."""
    analisi = analisi or analizza(d)
    if analisi is None:
        return
    pagine, stato = analisi["pagine"], analisi["indice"]
    n = 0
    if d.descrizione:
        yield {"fonte": Frammento.DOCUMENTO, "content_type": ct, "object_id": d.pk, "chiave": "descrizione", "pagina": None,
               "azienda_id": d.azienda_id, "titolo": f"Documento «{d.nome}», descrizione"[:250], "testo": d.descrizione[:MAX_TESTO_RECORD]}
    for pagina, testo in pagine:
        for i, pezzo in enumerate(pezzi(testo)):
            chiave = f"p{pagina}.{i}" if pagina else str(i)
            dove = f", p. {pagina}" if pagina else (f", parte {i + 1}" if i else "")
            yield {"fonte": Frammento.DOCUMENTO, "content_type": ct, "object_id": d.pk, "chiave": chiave, "pagina": pagina,
                   "azienda_id": d.azienda_id, "titolo": f"Documento «{d.nome}»{dove}"[:250], "testo": pezzo}
            n += 1
    if stato.riassunto and stato.impronta_riassunto == stato.impronta:
        yield {"fonte": Frammento.DOCUMENTO, "content_type": ct, "object_id": d.pk, "chiave": "riassunto", "pagina": None,
               "azienda_id": d.azienda_id, "titolo": f"Documento «{d.nome}», riassunto"[:250], "testo": stato.riassunto}
    if stato.frammenti != n:
        IndiceDocumento.objects.filter(pk=stato.pk).update(frammenti=n)


def analizza(d):
    """Estrae il testo del documento e aggiorna il suo IndiceDocumento. {pagine, testo, indice}, o None se il documento
    non ha un file da leggere."""
    file = d.contenuto
    stato = {"nome": d.nome[:200], "azienda_id": d.azienda_id, "pagine": None, "caratteri": 0, "messaggio": ""}
    pagine, esito, parziale = [], "vuoto", False
    if file:
        try:
            with file.open("rb") as f:
                dati = f.read(MAX_FILE + 1)
        except (OSError, ValueError):
            dati, esito = None, "illeggibile"
        if dati is not None:
            parziale = len(dati) > MAX_FILE
            pagine, esito = estrai(d.nome, dati[:MAX_FILE])
    if esito == "ok":
        pagine, totale = _taglia(pagine)
        parziale = parziale or totale > MAX_TESTO_DOCUMENTO
        stato["caratteri"] = min(totale, MAX_TESTO_DOCUMENTO)
        stato["pagine"] = max((n for n, _ in pagine if n), default=None)
        if not any(t.strip() for _, t in pagine):
            esito = IndiceDocumento.SENZA_TESTO
            stato["messaggio"] = "Nessun testo nel file: probabilmente è una scansione. L'assistente non lo può leggere."
        else:
            esito = IndiceDocumento.PARZIALE if parziale else IndiceDocumento.INDICIZZATO
            if parziale:
                stato["messaggio"] = "Documento molto lungo: l'assistente ne conosce solo la prima parte."
    elif esito == "non_supportato":
        esito = IndiceDocumento.NON_SUPPORTATO
        stato["messaggio"] = "Tipo di file non letto dall'assistente (si leggono PDF, Word, Excel, testo, CSV, Markdown)."
    elif esito == "illeggibile":
        esito = IndiceDocumento.ILLEGGIBILE
        stato["messaggio"] = "File rotto o protetto da password: l'assistente non lo può leggere."
    else:
        esito = IndiceDocumento.VUOTO
    testo = "\n\n".join(t for _, t in pagine)
    stato.update(stato=esito, impronta=_impronta(testo) if testo.strip() else "")
    indice = IndiceDocumento.objects.filter(documento_id=d.pk).first()
    if indice is None:
        indice = IndiceDocumento.objects.create(documento_id=d.pk, **stato)
    elif any(getattr(indice, k) != v for k, v in stato.items()):      # il giro programmato non riscrive ciò che non cambia
        for k, v in stato.items():
            setattr(indice, k, v)
        indice.save()
    if not file:
        return None
    return {"pagine": pagine, "testo": testo, "indice": indice}


def _taglia(pagine):
    """Le pagine fino a MAX_TESTO_DOCUMENTO caratteri in tutto (oltre si taglia) e il totale prima del taglio."""
    risultato, usati, totale = [], 0, 0
    for n, t in pagine:
        totale += len(t)
        if usati < MAX_TESTO_DOCUMENTO:
            risultato.append((n, t[:MAX_TESTO_DOCUMENTO - usati]))
            usati += len(risultato[-1][1])
    return risultato, totale


SORGENTI = {Frammento.RECORD: frammenti_record, Frammento.NOTA: frammenti_note,
            Frammento.DOCUMENTO: frammenti_documenti}


# ---------- embedding ----------

def url_servizio():
    from core import parametri
    try:
        return (parametri.leggi("ai.url_embeddings") or "").strip().rstrip("/")
    except KeyError:                                   # impostazione non dichiarata (modulo non installato)
        return ""


def embedding(testi, tipo="document"):
    """Vettori normalizzati (liste di float) dal servizio; None se il servizio non c'è o non risponde."""
    url = url_servizio()
    if not url or not testi:
        return None
    richiesta = urllib.request.Request(f"{url}/v1/embeddings", headers={"Content-Type": "application/json"},
                                       data=json.dumps({"input": testi, "input_type": tipo,
                                                        "dimensions": DIMENSIONI}).encode())
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
            dati = json.load(risposta)
        return [v["embedding"] for v in sorted(dati["data"], key=lambda v: v["index"])]
    except Exception as e:
        log.warning("servizio di embedding non disponibile (%s): %s", url, e)
        return None


def _binario(vettore):
    return array("f", vettore).tobytes()


def _da_binario(dati):
    v = array("f")
    v.frombytes(bytes(dati))
    return v


# ---------- indicizzazione ----------

def _allinea(esistenti_qs, sorgente, conti):
    """Allinea i frammenti di `esistenti_qs` a quelli prodotti da `sorgente`: nuovi, cambiati (vettore da rifare),
    spariti."""
    esistenti = {(f.content_type_id, f.object_id, f.chiave): f for f in
                 esistenti_qs.only("pk", "content_type_id", "object_id", "chiave", "impronta", "azienda_id", "titolo")}
    visti = set()
    for dati in sorgente:
        chiave = (dati["content_type"].pk, dati["object_id"], dati["chiave"])
        visti.add(chiave)
        impronta = _impronta(dati["titolo"] + "\n" + dati["testo"])
        f = esistenti.get(chiave)
        if f is None:
            Frammento.objects.create(impronta=impronta, **dati)
            conti["nuovi"] += 1
        elif f.impronta != impronta or f.azienda_id != dati["azienda_id"]:
            Frammento.objects.filter(pk=f.pk).update(impronta=impronta, titolo=dati["titolo"], testo=dati["testo"],
                                                     azienda_id=dati["azienda_id"], pagina=dati.get("pagina"), vettore=None)
            conti["aggiornati"] += 1
    spariti = [f.pk for k, f in esistenti.items() if k not in visti]
    for i in range(0, len(spariti), 500):
        conti["tolti"] += Frammento.objects.filter(pk__in=spariti[i:i + 500]).delete()[0]


def _vettori(qs, conti, limite_secondi, inizio):
    while time.monotonic() - inizio < limite_secondi:             # vettori mancanti, a lotti
        da_fare = list(qs.filter(vettore__isnull=True).only("pk", "titolo", "testo")[:LOTTO])
        if not da_fare:
            break
        vettori = embedding([f"{f.titolo}\n{f.testo}" for f in da_fare])
        if vettori is None:
            break
        for f, v in zip(da_fare, vettori):
            Frammento.objects.filter(pk=f.pk).update(vettore=_binario(v))
        conti["vettori"] += len(da_fare)


def indicizza(fonti=None, limite_secondi=240):
    """Allinea l'indice alle sorgenti. Restituisce un riepilogo {nuovi, aggiornati, tolti, vettori}."""
    inizio = time.monotonic()
    conti = {"nuovi": 0, "aggiornati": 0, "tolti": 0, "vettori": 0}
    for fonte in fonti or list(SORGENTI):
        _allinea(Frammento.objects.filter(fonte=fonte), SORGENTI[fonte](), conti)
    _vettori(Frammento.objects.all(), conti, limite_secondi, inizio)
    return conti


def indicizza_documento(documento_id):
    """Un documento solo, subito dopo un caricamento, una versione nuova, uno spostamento, un cambio di nome o il
    cestino: in chat si trova in pochi secondi, senza aspettare il giro programmato. Con i riassunti accesi, prima
    di allineare i frammenti si rifà il riassunto se il testo è cambiato."""
    from documenti.models import Documento
    ct = ContentType.objects.get_for_model(Documento)
    conti = {"nuovi": 0, "aggiornati": 0, "tolti": 0, "vettori": 0}
    esistenti = Frammento.objects.filter(fonte=Frammento.DOCUMENTO, content_type=ct, object_id=documento_id)
    d = Documento.objects.filter(pk=documento_id, cestinato_il__isnull=True).first()
    analisi = None
    if d is None:
        IndiceDocumento.objects.filter(documento_id=documento_id).delete()
    else:
        analisi = analizza(d)
        if analisi is not None and riassunti_accesi():
            conti["riassunto"] = riassumi(d, analisi)
    _allinea(esistenti, frammenti_di_un_documento(d, ct, analisi) if analisi is not None else [], conti)
    _vettori(esistenti, conti, 120, time.monotonic())
    return json.dumps(conti)


# ---------- riassunti dei documenti ----------

RIASSUNTO_SISTEMA = (
    "Riassumi il documento di un'azienda perché un assistente capisca se gli serve per rispondere a una domanda. "
    "Scrivi in italiano, senza preamboli, al massimo 200 parole, con queste righe:\n"
    "Argomento: una frase.\nPunti chiave: 3-6 punti brevi (date, importi, scadenze, obblighi se ci sono).\n"
    "Nomi: persone, aziende, prodotti, luoghi citati.\nRiferimenti: altri documenti, contratti o norme citati (o «—»).\n"
    "Usa solo ciò che c'è nel testo: non inventare.")
RIASSUNTO_MAX_TESTO = 60_000          # caratteri del documento mandati al modello
RIASSUNTI_PER_GIRO = 10               # documenti messi in coda dal giro programmato, per non spendere a raffica


def riassunti_accesi():
    from core import parametri
    try:
        return bool(parametri.leggi("ai.riassunti_documenti"))
    except KeyError:
        return False


def riassumi(d, analisi):
    """Il riassunto del documento (profilo «riassunti»), se il testo è cambiato dall'ultimo tentativo. Un tentativo
    fallito non si ripete finché il testo non cambia. Restituisce "fatto", "già fatto", "senza testo" o l'errore."""
    from . import catalogo, limiti
    from .gateway import ErroreModello, Inizio, Testo, Uso, esegui as gateway
    from .models import Turno
    from .protezione import Protezione
    indice = analisi["indice"]
    if indice.stato not in (IndiceDocumento.INDICIZZATO, IndiceDocumento.PARZIALE):
        return "senza testo"
    if indice.impronta_riassunto == indice.impronta:
        return "già fatto"
    utente = d.caricato_da or d.proprietario
    lavoro = Turno.objects.create(utente=utente, azienda_id=d.azienda_id, compito="riassunto_documento")
    pezzi_testo, modello = [], None
    try:
        profilo = catalogo.profilo_per("riassunti", d.azienda)
        catena = limiti.ammessi(catalogo.catena(profilo, d.azienda), utente)
        domanda = f"Documento «{d.nome}»:\n\n{analisi['testo'][:RIASSUNTO_MAX_TESTO]}"
        for pezzo in gateway(catena, protezione=Protezione(None), sistema=RIASSUNTO_SISTEMA,
                             messaggi=[{"ruolo": "utente", "testo": domanda}], max_token=800, effort=profilo.effort):
            if isinstance(pezzo, Inizio):
                modello = lavoro.modello = pezzo.modello
            elif isinstance(pezzo, Testo):
                pezzi_testo.append(pezzo.testo)
            elif isinstance(pezzo, Uso) and modello is not None:
                lavoro.addebita(modello, pezzo.come_dict())
    except (ErroreModello, catalogo.NessunModello) as e:
        log.warning("documento %s non riassunto: %s", d.pk, e)
        lavoro.stato, lavoro.errore = Turno.ERRORE, str(e)
    else:
        lavoro.stato = Turno.COMPLETATO
    lavoro.testo, lavoro.finito = "".join(pezzi_testo).strip(), timezone.now()
    lavoro.save()
    riuscito = lavoro.stato == Turno.COMPLETATO and lavoro.testo
    indice.riassunto = lavoro.testo[:4000] if riuscito else ""
    indice.impronta_riassunto = indice.impronta
    indice.save(update_fields=["riassunto", "impronta_riassunto", "aggiornato"])
    return "fatto" if riuscito else (lavoro.errore[:200] or "risposta vuota")


def accoda_riassunti_arretrati():
    """Con i riassunti accesi, i documenti leggibili il cui riassunto manca o è vecchio vanno in coda, pochi per giro."""
    if not riassunti_accesi():
        return 0
    arretrati = list(IndiceDocumento.objects.filter(stato__in=[IndiceDocumento.INDICIZZATO, IndiceDocumento.PARZIALE])
                     .exclude(impronta_riassunto=models.F("impronta")).values_list("documento_id", flat=True)[:RIASSUNTI_PER_GIRO])
    for pk in arretrati:
        accoda_documento(pk)
    return len(arretrati)


def viste_a_sezioni():
    """{label del modello: vista} delle viste che indicizzano un campo lungo per sezioni (es. wiki.paginawiki)."""
    from core.viste import registry
    registry.autodiscover(["core", *settings.ADDONS_ATTIVI])
    return {v.opts.label_lower: v for m in ["core", *settings.ADDONS_ATTIVI] if m not in ESCLUSI
            for v in registry.viste_di(m) if getattr(v, "conoscenza_sezioni", None)}


def indicizza_record(content_type_id, object_id):
    """Un record a sezioni solo, subito dopo il salvataggio o l'eliminazione (come i documenti)."""
    ct = ContentType.objects.get_for_id(content_type_id)
    vista = viste_a_sezioni().get(f"{ct.app_label}.{ct.model}")
    conti = {"nuovi": 0, "aggiornati": 0, "tolti": 0, "vettori": 0}
    esistenti = Frammento.objects.filter(fonte=Frammento.RECORD, content_type=ct, object_id=object_id)
    obj = vista.model._default_manager.filter(pk=object_id).first() if vista is not None else None
    campi = next((c for v, c in _viste_indicizzabili() if v is vista), []) if obj is not None else []
    _allinea(esistenti, frammenti_di_un_record(vista, campi, ct, obj) if obj is not None else [], conti)
    _vettori(esistenti, conti, 120, time.monotonic())
    return json.dumps(conti)


indicizza_record.senza_transazione = True


def accoda_record(content_type_id, object_id):
    """In coda, una volta sola per record: più salvataggi di fila fanno un'indicizzazione."""
    from core import lavori
    from core.models import Lavoro
    argomenti = {"content_type_id": content_type_id, "object_id": object_id}
    if not Lavoro.objects.filter(funzione="ai.conoscenza.indicizza_record", argomenti=argomenti, stato=Lavoro.IN_CODA).exists():
        lavori.accoda("ai.conoscenza.indicizza_record", max_tentativi=2, **argomenti)


def accoda_documento(documento_id):
    """In coda per il worker, una volta sola per documento (più modifiche di fila = un'indicizzazione)."""
    from core import lavori
    from core.models import Lavoro
    funzione = "ai.conoscenza.indicizza_documento"
    if not Lavoro.objects.filter(funzione=funzione, argomenti={"documento_id": documento_id},
                                 stato=Lavoro.IN_CODA).exists():
        IndiceDocumento.objects.filter(documento_id=documento_id).update(stato=IndiceDocumento.IN_CODA)
        lavori.accoda(funzione, documento_id=documento_id, max_tentativi=2)


# ---------- quando gira l'indicizzazione programmata ----------

INTERVALLI = {"5m": 5, "10m": 10, "30m": 30, "1h": 60}
TOLLERANZA = 60                       # secondi: il controllo del worker non cade mai esattamente sul minuto


def intervallo():
    from core import parametri
    try:
        return parametri.leggi("ai.intervallo_indice") or "10m"
    except KeyError:
        return "10m"


def _ultima_esecuzione():
    from core.models import Lavoro
    return (Lavoro.objects.filter(funzione="ai.conoscenza.indicizza_cron", stato=Lavoro.FATTO)
            .exclude(risultato__startswith="saltata").order_by("-finito").values_list("finito", flat=True).first())


def dovuta(scelta, ultima, adesso):
    """Se l'indicizzazione programmata tocca adesso: ogni N minuti, di notte (una volta dopo le 2) o mai."""
    if scelta == "spento":
        return False
    if ultima is None:
        return True
    if scelta == "notte":
        locale = timezone.localtime(adesso)
        soglia = locale.replace(hour=2, minute=0, second=0, microsecond=0)
        return locale >= soglia and timezone.localtime(ultima) < soglia
    minuti = INTERVALLI.get(scelta, 10)
    return (adesso - ultima).total_seconds() >= minuti * 60 - TOLLERANZA


def indicizza_cron():
    """Chiamata dal worker ogni 5 minuti: indicizza solo quando lo dice l'impostazione «Indicizzazione programmata»."""
    from . import funzioni
    if not funzioni.attiva("conoscenza"):
        return "saltata: ricerca nei documenti non compresa nella licenza"
    scelta = intervallo()
    if not dovuta(scelta, _ultima_esecuzione(), timezone.now()):
        return f"saltata: impostazione «{scelta}»"
    conti = indicizza()
    if "documenti" in settings.ADDONS_ATTIVI:
        conti["riassunti_in_coda"] = accoda_riassunti_arretrati()
    return json.dumps(conti, ensure_ascii=False)


# chiedono gli embedding in rete: dentro una transazione terrebbero fermo il database per tutti, per tutto il tempo
indicizza_cron.senza_transazione = True
indicizza_documento.senza_transazione = True


# ---------- ricerca ----------

_SENZA_RISULTATI = {}     # app -> funzione(azienda, domanda): le domande di una chat limitata all'app senza risultati


def registra_senza_risultati(app, funzione):
    """Un'app vuole sapere che cosa si è cercato senza trovare nulla nelle chat limitate a lei (la wiki ne fa un
    elenco di pagine da scrivere)."""
    _SENZA_RISULTATI[app] = funzione


def senza_risultati(app, azienda, domanda):
    funzione = _SENZA_RISULTATI.get(app)
    if funzione is None or azienda is None:
        return
    try:
        funzione(azienda, domanda)
    except Exception:
        log.exception("domanda senza risultati non registrata per %s", app)



def parole(testo):
    return {p for p in (w.lower() for w in PAROLA.findall(testo or "")) if p not in PAROLE_VUOTE}


def _coseno(a, b):
    return sum(x * y for x, y in zip(a, b))                  # vettori già normalizzati


FINESTRA = 200                        # candidati controllati insieme per i permessi (una query per tipo di record)


def cerca(domanda, utente, azienda=None, fonti=None, app="", limite=8, visibile=None, documenti=None):
    """[(frammento, punteggio)] più pertinenti tra quelli che `visibile(frammento)` lascia vedere. Con `documenti`
    (id dell'app Documenti) si cerca solo in quei documenti.

    L'app e i permessi si applicano prima di tagliare la classifica: i candidati si scorrono in ordine di punteggio,
    a finestre, finché non ci sono `limite` risultati visibili. Se tanti frammenti di altre app o non visibili
    stanno sopra, i pertinenti visibili si trovano lo stesso."""
    termini = parole(domanda)
    qs = Frammento.objects.all()
    qs = qs.filter(models.Q(azienda_id=getattr(azienda, "pk", None)) | models.Q(azienda__isnull=True))
    if fonti:
        qs = qs.filter(fonte__in=fonti)
    if app:
        qs = qs.filter(content_type_id__in=_tipi_di(app))
    if documenti is not None:
        from documenti.models import Documento
        qs = qs.filter(fonte=Frammento.DOCUMENTO, content_type=ContentType.objects.get_for_model(Documento), object_id__in=list(documenti))
    vettore = embedding([domanda], "query")
    domanda_v = array("f", vettore[0]) if vettore else None
    candidati = []
    for f in qs.only("pk", "fonte", "content_type_id", "object_id", "titolo", "testo", "vettore", "chiave", "pagina").iterator(
            chunk_size=2000):
        testo_parole = parole(f.titolo + " " + f.testo)
        chiave = len(termini & testo_parole) / len(termini) if termini else 0.0
        if domanda_v is not None and f.vettore:
            punteggio = 0.8 * _coseno(domanda_v, _da_binario(f.vettore)) + 0.2 * chiave
        else:
            punteggio = chiave
        if punteggio > 0:
            candidati.append((punteggio, f))
    candidati.sort(key=lambda c: c[0], reverse=True)
    risultati, per_record = [], {}
    for inizio in range(0, len(candidati), FINESTRA):
        finestra = candidati[inizio:inizio + FINESTRA]
        if visibile is not None and hasattr(visibile, "prepara"):
            visibile.prepara([f for _, f in finestra])
        for punteggio, f in finestra:
            if visibile is not None and not visibile(f):
                continue
            record = (f.content_type_id, f.object_id)
            if per_record.get(record, 0) >= 2:               # al massimo due pezzi dello stesso documento o record
                continue
            per_record[record] = per_record.get(record, 0) + 1
            risultati.append((f, round(punteggio, 3)))
            if len(risultati) >= limite:
                return risultati
    return risultati


def _tipi_di(app):
    """Gli id dei ContentType dei modelli che appartengono all'app (quelli la cui vista è dell'app)."""
    from core.viste import registry
    registry.autodiscover(["core", *settings.ADDONS_ATTIVI])
    return [ContentType.objects.get_for_model(v.model).pk for v in registry.viste_di(app)
            if getattr(registry.per_modello(v.model), "modulo", None) == app]


def statistiche():
    totale = Frammento.objects.count()
    return {"frammenti": totale, "con_vettore": Frammento.objects.filter(vettore__isnull=False).count(),
            "servizio": url_servizio() or "non configurato"}

