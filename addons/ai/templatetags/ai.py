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
