from django import template

from ai import markdown

register = template.Library()


@register.filter
def markdown_ai(testo):
    return markdown.rendi(testo)


@register.filter
def proposte(messaggio):
    """Le proposte preparate nel turno di una risposta dell'assistente (schede sotto il testo)."""
    if getattr(messaggio, "ruolo", "") != "assistente" or not messaggio.turno_id:
        return []
    from ai.models import Proposta
    return Proposta.objects.filter(turno_id=messaggio.turno_id).select_related("azienda")


@register.filter
def artifact(messaggio):
    """Grafici e tabelle prodotti nel turno di una risposta dell'assistente."""
    if getattr(messaggio, "ruolo", "") != "assistente" or not messaggio.turno_id:
        return []
    from ai.models import Artifact
    return Artifact.objects.filter(turno_id=messaggio.turno_id)


@register.filter
def documenti(messaggio):
    """I documenti scritti o modificati da Ada nel turno di una risposta."""
    if getattr(messaggio, "ruolo", "") != "assistente" or not messaggio.turno_id:
        return []
    from ai.models import DocumentoChat
    return DocumentoChat.objects.filter(versioni__turno_id=messaggio.turno_id).distinct()


@register.filter
def svg_artifact(a):
    from django.utils.safestring import mark_safe

    from ai import artifact as modulo
    return mark_safe(modulo.svg_di(a))                  # SVG del kernel: testi già passati da escape


@register.filter
def serie_artifact(a, dati=None):
    """Il grafico come lo disegna core/grafici.js (lo stesso di Analisi), con il link ai record di ogni punto (nella
    stessa pagina: con Indietro si torna alla chat). None per le previsioni e senza dati: resta il disegno del server."""
    dati = dati if dati is not None else a.dati
    if a.spec.get("grafico") == "previsione" or not dati or not dati.get("serie"):
        return None
    serie = [tuple(c) for c in dati["serie"]]
    link = [x or None for x in dati.get("link", [])]        # salvati prima dei link: nessun clic finché non si aggiorna
    return {"dom": f"ai-serie-{a.pk}", "dati": {
        "tipo": a.spec.get("grafico", "barre"), "titolo": a.titolo, "etichette": [str(e) for e, _ in serie],
        "valori": [float(v) for _, v in serie], "link": link if any(link) else [],
        **({"confronto": dati["confronto"]} if dati.get("confronto") and a.spec.get("grafico") != "torta" else {})}}


@register.simple_tag(takes_context=True)
def filtri_artifact(context, a):
    """«Filtra» e le etichette dei filtri scelti per un grafico della chat (core/_filtri_grafico.html): solo per il
    proprietario e per i grafici che hanno filtri; altrimenti None."""
    from django.urls import reverse

    from core import misure
    request = context.get("request")
    if request is None or a.tipo != "grafico" or a.utente_id != request.user.pk:
        return None
    if not misure.filtri_possibili(a.spec) and not a.spec.get("scelti"):      # le etichette scelte restano da togliere
        return None
    return {"url": reverse("ai:filtro_artifact", args=[a.pk]), "url_pannello": reverse("ai:filtri_artifact", args=[a.pk]),
            "bersaglio": f"#ai-artifact-{a.pk}", "etichette": [(campo, testo) for campo, testo in _etichette_filtri(a.spec)]}


def _etichette_filtri(spec):
    from core import misure
    return [(campo, misure.etichetta_filtri({"scelti": {campo: v}})) for campo, v in (spec.get("scelti") or {}).items()]


@register.filter
def etichetta_filtri(spec):
    from core import misure
    return misure.etichetta_filtri(spec or {})


@register.filter
def etichetta_periodo(spec):
    """«dell'anno in corso», «del mese in corso, a confronto con l'anno prima»: accanto al titolo del grafico."""
    from core import misure
    try:
        return misure.etichetta_periodo(spec or {})
    except Exception:
        return ""


@register.filter
def periodo_artifact(a):
    """I pulsanti del periodo per un grafico della chat (core/_periodo_grafico.html), o None se non ne ha."""
    from django.urls import reverse

    from core import misure
    p = misure.periodo_grafico(a.spec) if a.tipo == "grafico" else None
    if p is None:
        return None
    return {**p, "url": reverse("ai:periodo_artifact", args=[a.pk]), "bersaglio": f"#ai-artifact-{a.pk}",
            "confronto_possibile": a.spec.get("grafico") != "torta"}


@register.filter
def righe_con_link(dati):
    righe = dati.get("righe", [])
    return zip(righe, list(dati.get("link", [])) + [""] * (len(righe) - len(dati.get("link", []))))



@register.filter
def provenienza(messaggio):
    """La provenienza calcolata a fine turno di una risposta dell'assistente ({} se non c'è), con i dettagli da aprire:
    i dati personali protetti (tipo, valore, segnaposto: i valori dalla conversazione, che li ha già) e i token."""
    if getattr(messaggio, "ruolo", "") != "assistente" or not messaggio.turno_id:
        return {}
    turno = messaggio.turno
    if not turno.provenienza:
        return {}
    pv = {**turno.provenienza, "modello": turno.modello, "costo": turno.costo}
    mappa = getattr(messaggio.conversazione, "segnaposto", None) or {}
    pv["protetti"] = [{"tipo": tipo_dato(s), "valore": mappa[s], "segnaposto": s} for s in pv.get("segnaposto") or [] if s in mappa]
    uso = turno.uso or {}
    if uso:
        cache = int(uso.get("cache_lettura") or 0) + int(uso.get("cache_scrittura") or 0)
        pv["token"] = {"entrata": int(uso.get("input") or 0) + cache, "cache": cache, "uscita": int(uso.get("output") or 0),
                       "passi": turno.passi}
    return pv


TIPI_DATO = {"FULLNAME": "Nome", "USERNAME": "Nome utente", "ORG": "Organizzazione", "CITY": "Città", "PROVINCE": "Provincia",
             "EMAIL": "Email", "TELEPHONENUM": "Telefono", "CREDITCARDNUMBER": "Carta di credito", "IBAN": "IBAN",
             "CF": "Codice fiscale", "PIVA": "Partita IVA", "IPADDR": "Indirizzo IP", "POD": "Codice POD", "PDR": "Codice PDR",
             "DEVICE_ID": "Codice dispositivo", "EMPLOYEE_ID": "Matricola", "ID_DOC": "Documento d'identità",
             "BUSINESS_CODE": "Codice aziendale", "SECRET": "Dato riservato", "TARGA": "Targa", "CATASTO": "Dati catastali",
             "BUILDINGNUM": "Numero civico", "ZIPCODE": "CAP", "DOCID": "Numero di documento", "DATE": "Data", "TIME": "Ora",
             "AMOUNT": "Importo", "AGE": "Età", "STREET": "Via", "ADDRESS": "Indirizzo"}


def tipo_dato(segnaposto):
    """«[FULLNAME_1]» → «Nome»; un'etichetta che non conosciamo resta leggibile («[TAX_ID_2]» → «Tax id»)."""
    etichetta = segnaposto.strip("[]").rsplit("_", 1)[0]
    return TIPI_DATO.get(etichetta, etichetta.replace("_", " ").capitalize())


@register.filter
def allegati(messaggio):
    """I file allegati a un messaggio dell'utente."""
    from ai import allegati_chat
    return allegati_chat.di(messaggio) if getattr(messaggio, "ruolo", "") == "utente" else []


@register.filter
def voto(messaggio):
    """Il voto dato a una risposta dell'assistente, se c'è."""
    from ai.models import ValutazioneRisposta
    return ValutazioneRisposta.objects.filter(messaggio=messaggio).first()


@register.simple_tag
def ct_progetto():
    from django.contrib.contenttypes.models import ContentType

    from ai.models import ProgettoChat
    return ContentType.objects.get_for_model(ProgettoChat).pk


@register.simple_tag
def campi_scrivi_con_ada():
    """Le domande di «Scrivi con Ada» per ogni campo, per lo script del riquadro."""
    from ai.aiuto_testi import CAMPI
    return {k: {"domande": v["domande"]} for k, v in CAMPI.items()}


@register.simple_tag(takes_context=True)
def progetti_del_record(context, obj, vista=None):
    """Per la sezione nel dettaglio di un record: (progetti collegati, progetti dell'utente da collegare, tipo di record)."""
    request = context.get("request")
    from .. import funzioni
    if request is None or obj is None or getattr(vista, "modulo", "") == "ai" or not funzioni.attiva("aree_di_lavoro"):
        return None
    from django.contrib.contenttypes.models import ContentType

    from ai import collegamenti
    from ai.models import ProgettoChat
    from django.apps import apps as django_apps
    from django.urls import reverse
    azienda = getattr(request, "azienda", None)
    if azienda is None or not request.user.has_perm("ai.view_progettochat"):
        return None
    collegati = collegamenti.progetti_del_record(request.user, azienda, obj)
    gestite = list(ProgettoChat.objects.filter(utente=request.user, azienda=azienda))      # collega solo chi gestisce
    dashboard = django_apps.is_installed("grafici") and request.user.has_perm("grafici.view_pagina")
    return {"collegati": [{"area": a, **collegamenti.contenuto(request.user, a),
                           "dashboard": reverse("grafici:pagina_area", args=[a.pk]) if dashboard else ""} for a in collegati],
            "liberi": [p for p in gestite if p not in collegati], "ct": ContentType.objects.get_for_model(type(obj)).pk,
            "puo_creare": request.user.has_perm("ai.add_progettochat")}


@register.simple_tag(takes_context=True)
def chat_dell_area(context, area):
    """Le chat dell'area che chi guarda può vedere: le sue e quelle condivise dagli altri membri (mai le private altrui)."""
    request = context.get("request")
    if request is None:
        return []
    from ai import aree
    return aree.chat_visibili(request.user, area).order_by("-aggiornata")[:100]


@register.simple_tag(takes_context=True)
def colleghi_per(context, oggetto):
    """Con chi si può condividere un documento, un grafico o una tabella (e con chi lo è già)."""
    from ..condivisione import colleghi
    return colleghi(context["request"], oggetto)


@register.simple_tag
def url_riassunto(vista, obj):
    """L'indirizzo che fa riassumere il record ad Ada."""
    from django.urls import reverse

    from core.generici import ct_di
    return reverse("ai:riassumi_record", args=[ct_di(vista.model).pk, obj.pk])


@register.simple_tag
def indice_documento(documento):
    """Lo stato del documento nell'indice dell'assistente, o None se non è ancora stato letto."""
    from ai.models import IndiceDocumento
    return IndiceDocumento.objects.filter(documento_id=documento.pk).first()


@register.simple_tag(takes_context=True)
def parla_disponibile(context):
    """L'icona «Parla con Ada» nella testata: con la funzione voce in licenza e dettatura e lettura configurate."""
    from .. import funzioni, parla
    request = context.get("request")
    try:
        return funzioni.attiva("voce") and parla.disponibile(getattr(request, "azienda", None))
    except KeyError:                                       # parametri della voce non registrati: niente icona
        return False
