"""Moduli «contattaci» sul sito (web-to-lead): chi compila diventa un'opportunità, con l'origine, l'etichetta, il
contatto se l'email è già in anagrafica, una nota nel chatter e un'attività al commerciale per ricontattarlo.

Controlli come il widget dell'assistenza: modulo attivo e sito ammesso (CORS), campo esca contro i bot, al massimo
LIMITE_ORA invii l'ora per indirizzo, dimensioni dei campi. Nessun dato torna indietro: solo «ok»."""
import hashlib
import logging
from datetime import timedelta

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from contatti.models import Contatto
from core import attivita, chatter
from core.models import TipoAttivita

from .models import ModuloWeb, Opportunita

log = logging.getLogger("crm.modulo_web")
LIMITE_ORA = 5
CAMPI_PROVENIENZA = ("pagina", "utm_source", "utm_medium", "utm_campaign")


def _origine(request):
    return (request.headers.get("Origin") or "").rstrip("/").lower()


def _cors(risposta, origine):
    if origine:
        risposta["Access-Control-Allow-Origin"] = origine
        risposta["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        risposta["Access-Control-Allow-Headers"] = "Content-Type"
        risposta["Access-Control-Max-Age"] = "600"
        risposta["Vary"] = "Origin"
    return risposta


def _errore(messaggio, origine, stato=400):
    return _cors(JsonResponse({"ok": False, "errore": messaggio}, status=stato), origine)


def _troppi(modulo, request):
    """Conta gli invii dell'ora per indirizzo (solo l'impronta, l'indirizzo non si conserva)."""
    inoltrato = request.headers.get("X-Forwarded-For", "")
    ip = inoltrato.split(",")[0].strip() if inoltrato else request.META.get("REMOTE_ADDR", "")
    chiave = "crm.modulo:" + hashlib.sha256(f"{modulo.pk}:{ip}".encode()).hexdigest()[:32]
    if cache.get(chiave, 0) >= LIMITE_ORA:
        return True
    cache.set(chiave, cache.get(chiave, 0) + 1, 3600)
    return False


def crea_lead(modulo, nome, email, telefono="", azienda="", messaggio="", provenienza=None):
    """L'opportunità nata dal modulo, con nota, etichetta e attività al commerciale."""
    contatto = Contatto.objects.filter(azienda=modulo.azienda, email__iexact=email).order_by("pk").first()
    righe = [messaggio] if messaggio else []
    righe += [f"{k}: {v}" for k, v in (provenienza or {}).items() if v]
    opp = Opportunita.objects.create(
        azienda=modulo.azienda, titolo=(f"{nome} · {azienda}" if azienda else nome)[:200], contatto=contatto,
        nome_contatto=" · ".join(x for x in (nome, azienda) if x)[:200], email=email, telefono=telefono,
        commerciale=modulo.commerciale, note="\n".join(righe), origine=f"Modulo del sito: {modulo.nome}"[:100])
    if modulo.etichetta_id:
        opp.etichette.add(modulo.etichetta)
    chatter.scrivi(opp, None, f"Arrivata dal modulo «{modulo.nome}» del sito." + (f"\n\n{messaggio}" if messaggio else ""),
                   tipo="sistema")
    if modulo.commerciale_id:
        chatter.segui(opp, modulo.commerciale)
        tipo = TipoAttivita.objects.filter(nome__icontains="chiamat").first() or TipoAttivita.objects.first()
        if tipo is not None:
            attivita.pianifica(opp, tipo, modulo.commerciale, timezone.localdate() + timedelta(days=1),
                               f"Ricontattare {nome}"[:200], "Richiesta arrivata dal sito.")
    return opp


@csrf_exempt
def invia(request, chiave):
    origine = _origine(request)
    modulo = ModuloWeb.objects.filter(chiave=chiave, attivo=True).select_related("commerciale", "etichetta").first()
    if modulo is None or not modulo.elenco_domini():
        return _errore("modulo non attivo", origine, 404)
    if origine not in modulo.elenco_domini():
        log.warning("modulo web %s: origine non ammessa %r", modulo.pk, origine)
        return _errore("sito non ammesso", "", 403)
    if request.method == "OPTIONS":
        return _cors(HttpResponse(status=204), origine)
    if request.method != "POST":
        return _errore("solo POST", origine, 405)
    if request.POST.get("sito_web"):                       # campo esca: lo compila solo un bot
        return _cors(JsonResponse({"ok": True, "grazie": modulo.grazie}), origine)
    nome = (request.POST.get("nome") or "").strip()[:120]
    email = (request.POST.get("email") or "").strip()[:254]
    if not nome:
        return _errore("scrivi il tuo nome", origine)
    try:
        validate_email(email)
    except ValidationError:
        return _errore("serve un indirizzo email valido per risponderti", origine)
    if _troppi(modulo, request):
        return _errore("troppi invii: riprova più tardi", origine, 429)
    crea_lead(modulo, nome, email,
              telefono=(request.POST.get("telefono") or "").strip()[:40] if modulo.chiedi_telefono else "",
              azienda=(request.POST.get("azienda") or "").strip()[:120] if modulo.chiedi_azienda else "",
              messaggio=(request.POST.get("messaggio") or "").strip()[:5000],
              provenienza={k: (request.POST.get(k) or "").strip()[:300] for k in CAMPI_PROVENIENZA})
    return _cors(JsonResponse({"ok": True, "grazie": modulo.grazie}), origine)
