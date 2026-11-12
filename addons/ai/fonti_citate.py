"""La fonte di una citazione, da leggere accanto alla chat con il passaggio citato evidenziato.

Si parte dal link cliccato in una risposta e si cercano, tra i risultati di cerca_conoscenza e leggi_documento di quel
turno, i frammenti con quell'indirizzo: solo ciò che gli strumenti hanno restituito davvero. Poi:
- per un documento dell'app Documenti, il testo intero (diviso per pagine nei PDF) con i frammenti citati evidenziati;
- per un record, una pagina della wiki o una nota, i suoi frammenti nell'ordine dell'indice, con quelli citati
  evidenziati.
I permessi si ricontrollano con chi guarda adesso (in una chat condivisa può essere un collega): se non vede la fonte,
non c'è niente da mostrare."""
import json
import re

from django.contrib.contenttypes.models import ContentType

from .models import Evento, Frammento
from .verifica import _base, _frammento_di

MAX_BLOCCHI = 200
PAGINA = re.compile(r"^\[pagina (\d+)\]$")


def _normalizza(testo):
    """Come conoscenza.pezzi prepara il testo: così i frammenti si ritrovano dentro il testo intero."""
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", testo or "")).strip()


def _citati(turno, url):
    """[(voce del risultato, frammento o None)] dei risultati del turno con quell'indirizzo (esatto, o lo stesso
    record se l'indirizzo cliccato non ha ancora né pagina)."""
    nomi, esatti, stesso_record = {}, [], []
    for ev in Evento.objects.filter(turno=turno, tipo__in=[Evento.ASSISTENTE, Evento.STRUMENTO]).order_by("pk"):
        if ev.tipo == Evento.ASSISTENTE:
            nomi.update({b.get("id"): b["nome"] for b in ev.dati.get("blocchi", []) if b.get("tipo") == "strumento"})
            continue
        for r in ev.dati.get("risultati", []):
            nome = nomi.get(r.get("id"))
            if r.get("errore") or nome not in ("cerca_conoscenza", "leggi_documento"):
                continue
            try:
                dati = json.loads(r.get("contenuto") or "")
            except (TypeError, ValueError):
                continue
            if not isinstance(dati, dict):
                continue
            voci = dati.get("risultati", []) if nome == "cerca_conoscenza" else [{**dati, "vista": "documenti.documenti"}]
            for voce in voci:
                indirizzo = voce.get("url") or ""
                if indirizzo == url:
                    esatti.append(voce)
                elif _base(indirizzo) == _base(url):
                    stesso_record.append(voce)
    scelti = esatti or (stesso_record if _base(url) == url else [])
    return [(v, _frammento_di(v) if "estratto" in v else None) for v in scelti]


def _documento_id(voce):
    if voce.get("vista") == "documenti.documenti" and voce.get("id") is not None:
        return voce["id"]
    m = re.search(r"/documenti/documenti/(\d+)/", voce.get("url") or "")
    return int(m.group(1)) if m else None


def _segmenti(testo, evidenze):
    """[(testo, evidenziato)] marcando ogni occorrenza dei testi in `evidenze` (intervalli uniti se si sovrappongono)."""
    intervalli = []
    for e in evidenze:
        e = (e or "").strip()
        if len(e) < 3:
            continue
        inizio = testo.find(e)
        if inizio < 0:                       # piccole differenze di spazi: si prova con l'inizio del pezzo
            inizio = testo.find(e[:120])
            fine = inizio + len(e) if inizio >= 0 else -1
        else:
            fine = inizio + len(e)
        if inizio >= 0:
            intervalli.append((inizio, min(fine, len(testo))))
    intervalli.sort()
    uniti = []
    for a, b in intervalli:
        if uniti and a <= uniti[-1][1]:
            uniti[-1] = (uniti[-1][0], max(uniti[-1][1], b))
        else:
            uniti.append((a, b))
    segmenti, pos = [], 0
    for a, b in uniti:
        if a > pos:
            segmenti.append((testo[pos:a], False))
        segmenti.append((testo[a:b], True))
        pos = b
    if pos < len(testo):
        segmenti.append((testo[pos:], False))
    return segmenti


def _testo_documento(documento, evidenze, pagina_aperta=None):
    """Blocchi del documento: uno per pagina nei PDF, uno solo per gli altri file."""
    from .conoscenza import estrai
    file = documento.contenuto
    if not file:
        return []
    with file.open("rb") as f:
        pagine, esito = estrai(documento.nome, f.read(20 * 1024 * 1024))
    if esito != "ok":
        return []
    blocchi = []
    for numero, testo in pagine:
        testo = _normalizza(testo)
        if not testo:
            continue
        segmenti = _segmenti(testo, evidenze)
        blocchi.append({"pagina": numero, "segmenti": segmenti, "evidenziato": any(e for _, e in segmenti),
                        "aperta": numero is not None and numero == pagina_aperta})
    return blocchi


def _testo_record(content_type_id, object_id, citati):
    frammenti = list(Frammento.objects.filter(content_type_id=content_type_id, object_id=object_id)
                     .order_by("fonte", "chiave").only("pk", "titolo", "testo", "pagina")[:MAX_BLOCCHI])
    pk_citati = {f.pk for f in citati}
    return [{"titolo": f.titolo, "pagina": f.pagina, "segmenti": [(f.testo, f.pk in pk_citati)],
             "evidenziato": f.pk in pk_citati, "aperta": False} for f in frammenti]


def fonte(messaggio, url, request):
    """{titolo, url, blocchi, documento} da mostrare accanto alla chat, o None se il link non è una fonte del turno
    o chi guarda non la può vedere."""
    from . import strumenti
    from .strumenti.conoscenza import _visibilita
    if not messaggio.turno_id or not url:
        return None
    citati = _citati(messaggio.turno, url)
    if not citati:
        return None
    voce, frammento = citati[0]
    contesto = strumenti.Contesto(utente=request.user, azienda=getattr(request, "azienda", None),
                                  conversazione=messaggio.conversazione)
    visibile = _visibilita(contesto)
    frammenti = [f for _, f in citati if f is not None]
    documento_id = _documento_id(voce)
    pagina = next((v.get("pagina") or v.get("da_pagina_pdf") for v, _ in citati if v.get("pagina") or v.get("da_pagina_pdf")), None)
    if documento_id is not None:
        from django.apps import apps
        if not apps.is_installed("documenti"):
            return None
        from documenti.models import Documento
        ct = ContentType.objects.get_for_model(Documento)
        prova = Frammento(content_type_id=ct.pk, object_id=documento_id)
        if not visibile(prova):
            return None
        documento = Documento.objects.filter(pk=documento_id, cestinato_il__isnull=True).first()
        if documento is None:
            return None
        blocchi = _testo_documento(documento, [f.testo for f in frammenti], pagina)
        return {"titolo": documento.nome, "url": url, "blocchi": blocchi, "documento": True,
                "nessuna_evidenza": bool(frammenti) and not any(b["evidenziato"] for b in blocchi)}
    if frammento is None or not visibile(frammento):
        return None
    ct = ContentType.objects.get_for_id(frammento.content_type_id)
    record = ct.model_class()._default_manager.filter(pk=frammento.object_id).first() if ct.model_class() else None
    titolo = f"{str(ct.model_class()._meta.verbose_name).capitalize()} «{record}»" if record is not None else frammento.titolo
    return {"titolo": titolo, "url": url, "blocchi": _testo_record(frammento.content_type_id, frammento.object_id, frammenti),
            "documento": False, "nessuna_evidenza": False}
