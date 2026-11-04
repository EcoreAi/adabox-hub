"""La sandbox dei connettori: un telefono finto per provare WhatsApp e Telegram senza account.

Non è un percorso parallelo. Ciò che «scrive il cliente» diventa il vero messaggio della piattaforma, con la vera firma,
e passa da `connettori.ricevi` come in produzione. Ciò che esce si ferma all'ultimo passo, `api`, che risponde come
farebbero le API vere, errori compresi, e lo registra per mostrarlo. Solo le connessioni di prova possono usarla."""
import hashlib
import hmac
import json
import secrets
import struct
import time
import zlib

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import connettori
from .models import Connessione, ConversazioneEsterna, Messaggio, SandboxEvento, SandboxMedia

GUASTI = {"": (0, {}), "token": (401, "Token non valido"), "limite": (429, "Troppe richieste"), "giu": (503, "Servizio non disponibile"),
          "bloccato": (403, "Il cliente ha bloccato il bot")}


# --- ciò che fa la piattaforma quando le si manda un messaggio ---

def _png_prova():
    """Una vera immagine PNG, piccola, generata qui: niente file di esempio da distribuire."""
    lato = 96
    righe = b"".join(b"\x00" + b"".join(bytes((20 + x * 2, 110 + y, 220 - x)) for x in range(lato)) for y in range(lato))

    def pezzo(tipo, dati):
        return struct.pack(">I", len(dati)) + tipo + dati + struct.pack(">I", zlib.crc32(tipo + dati))
    return b"\x89PNG\r\n\x1a\n" + pezzo(b"IHDR", struct.pack(">IIBBBBB", lato, lato, 8, 2, 0, 0, 0)) + pezzo(b"IDAT", zlib.compress(righe)) + pezzo(b"IEND", b"")


def conserva(c, nome, mime, dati):
    return SandboxMedia.objects.create(connessione=c, id_media=secrets.token_urlsafe(16), nome=nome[:160], mime=mime[:100], dati=dati)


def scarica(c, media_id):
    """Come i server della piattaforma: il file c'è, o l'errore che darebbero loro."""
    codice, descrizione = GUASTI.get(c.sandbox_guasto, GUASTI[""])
    if codice:
        raise connettori.ErroreConsegna(descrizione, temporaneo=codice == 429 or codice >= 500)
    f = SandboxMedia.objects.filter(connessione=c, id_media=media_id).first()
    if f is None:
        raise connettori.ErroreConsegna("File inesistente")
    return bytes(f.dati), f.mime


def api_file(c, url, dati, file):
    """Il caricamento di un file: su WhatsApp dà un id, su Telegram è già l'invio."""
    _, nome, contenuto, mime = file
    codice, descrizione = GUASTI.get(c.sandbox_guasto, GUASTI[""])
    if url.endswith("/media"):                     # WhatsApp: prima si carica, poi si manda il messaggio con l'id
        if codice:
            return _errore(c, codice, descrizione)
        return 200, {"id": conserva(c, nome, mime, contenuto).id_media}
    destinatario = str(dati.get("chat_id", ""))
    media = None
    if codice:
        risposta = _errore(c, codice, descrizione)
    else:
        media = conserva(c, nome, mime, contenuto)
        risposta = 200, {"ok": True, "result": {"message_id": secrets.randbelow(10**9), "chat": {"id": destinatario, "type": "private"}}}
    SandboxEvento.objects.create(connessione=c, contatto=destinatario, verso=SandboxEvento.USCITA, testo=f"[{url.rsplit('/', 1)[-1]}] {nome}", richiesta={**dati, "file": nome, "mime": mime}, risposta=risposta[1], codice=risposta[0], media=media)
    return risposta


def _errore(c, codice, testo):
    if c.tipo == Connessione.WHATSAPP:
        return codice, {"error": {"message": testo, "type": "OAuthException", "code": codice}}
    return codice, {"ok": False, "error_code": codice, "description": testo}


def api(c, dati):
    """Risponde come l'API vera, nel suo formato, e registra ciò che è stato chiesto."""
    media = None
    if c.tipo == Connessione.WHATSAPP and dati.get("type") in connettori.TIPI_MEDIA:
        destinatario = dati.get("to", "")
        media = SandboxMedia.objects.filter(connessione=c, id_media=(dati.get(dati["type"]) or {}).get("id", "")).first()
        testo = f"[{dati['type']}] {media.nome}" if media else ""
    elif c.tipo == Connessione.WHATSAPP:
        destinatario, testo = dati.get("to", ""), (dati.get("text") or {}).get("body", "")
    else:
        destinatario, testo = str(dati.get("chat_id", "")), dati.get("text", "")
    codice, descrizione = GUASTI.get(c.sandbox_guasto, GUASTI[""])
    if codice:
        risposta = _errore(c, codice, descrizione)
    elif not testo:
        risposta = _errore(c, 400, "Testo mancante")
    elif len(testo) > connettori.MASSIMO_TESTO:
        risposta = _errore(c, 400, "Testo troppo lungo")
    elif c.tipo == Connessione.WHATSAPP:
        risposta = 200, {"messaging_product": "whatsapp", "contacts": [{"input": destinatario, "wa_id": destinatario}], "messages": [{"id": f"wamid.{secrets.token_hex(12)}"}]}
    else:
        risposta = 200, {"ok": True, "result": {"message_id": secrets.randbelow(10**9), "chat": {"id": destinatario, "type": "private"}, "text": testo}}
    SandboxEvento.objects.create(connessione=c, contatto=destinatario, verso=SandboxEvento.USCITA, testo=testo, richiesta=dati, risposta=risposta[1], codice=risposta[0], media=media)
    return risposta


# --- ciò che la piattaforma manda a noi ---

def _firma_whatsapp(c, corpo):
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(c.segreto().encode(), corpo, hashlib.sha256).hexdigest()}


def _corpo_whatsapp(c, valore):
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "SANDBOX", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "390000000000", "phone_number_id": c.id_numero}, **valore}}]}]}).encode()


def messaggio_cliente(c, contatto, nome, testo="", tipo="text", media=None):
    """(corpo, intestazioni): il messaggio come lo manderebbe la piattaforma. `media`: un SandboxMedia già caricato."""
    ora = int(time.time())
    if c.tipo == Connessione.WHATSAPP:
        messaggio = {"from": contatto, "id": f"wamid.{secrets.token_hex(12)}", "timestamp": str(ora), "type": tipo}
        if tipo == "text":
            messaggio["text"] = {"body": testo}
        elif media is not None:
            voce = tipo == "voice"
            messaggio["type"] = "audio" if voce else tipo
            messaggio[messaggio["type"]] = {"id": media.id_media, "mime_type": media.mime, **({"voice": True} if voce else {}),
                                            **({"caption": testo} if testo else {}), **({"filename": media.nome} if tipo == "document" else {})}
        else:                                      # posizione, contatto: ciò che non è un file
            messaggio[tipo] = {"latitude": 44.6, "longitude": 10.9}
        corpo = _corpo_whatsapp(c, {"contacts": [{"profile": {"name": nome}, "wa_id": contatto}], "messages": [messaggio]})
        return corpo, _firma_whatsapp(c, corpo)
    chat = int(contatto) if contatto.lstrip("-").isdigit() else contatto
    messaggio = {"message_id": secrets.randbelow(10**9), "from": {"id": chat, "is_bot": False, "first_name": nome}, "chat": {"id": chat, "type": "private", "first_name": nome}, "date": ora}
    if tipo == "text":
        messaggio["text"] = testo
    elif media is None:
        messaggio[tipo] = {"latitude": 44.6, "longitude": 10.9}
    else:
        if testo:
            messaggio["caption"] = testo
        if tipo == "image":
            messaggio["photo"] = [{"file_id": "piccola", "width": 90, "height": 90}, {"file_id": media.id_media, "width": 96, "height": 96}]
        else:
            messaggio[tipo] = {"file_id": media.id_media, "mime_type": media.mime, **({"file_name": media.nome} if tipo == "document" else {})}
    corpo = json.dumps({"update_id": secrets.randbelow(10**9), "message": messaggio}).encode()
    return corpo, {"X-Telegram-Bot-Api-Secret-Token": c.segreto()}


def stato_whatsapp(c, id_messaggio, stato, contatto):
    corpo = _corpo_whatsapp(c, {"statuses": [{"id": id_messaggio, "status": stato, "timestamp": str(int(time.time())), "recipient_id": contatto}]})
    return corpo, _firma_whatsapp(c, corpo)


def _arriva(c, contatto, corpo, intestazioni, testo, descrizione="", media=None):
    codice, esito = connettori.ricevi(c, corpo, intestazioni)
    return SandboxEvento.objects.create(connessione=c, contatto=contatto, verso=SandboxEvento.ENTRATA, testo=testo, richiesta=json.loads(corpo),
                                        risposta={"esito": esito, "prova": descrizione}, codice=codice, media=media)


# --- pagina ---

def _prova(request, pk):
    if not request.user.has_perm("discuss.change_connessione"):
        raise PermissionDenied
    c = get_object_or_404(Connessione.objects.select_related("sportello"), pk=pk)
    if not c.sandbox:
        raise Http404                              # su una connessione vera non si simula niente
    return c


def _contatto(request, c):
    predefinito = "393330000001" if c.tipo == Connessione.WHATSAPP else "100000001"
    valore = "".join(x for x in request.POST.get("contatto", request.GET.get("contatto", "")) if x.isdigit())[:20]
    return valore or predefinito


@login_required
def pagina(request, pk):
    c = _prova(request, pk)
    return render(request, "discuss/sandbox.html", {"c": c, "contatto": _contatto(request, c), "url_webhook": connettori.url_webhook(c, f"{request.scheme}://{request.get_host()}"),
                                                    "guasti": [("", "Nessuno"), ("token", "Token non valido"), ("limite", "Troppe richieste"), ("giu", "Servizio giù"), ("bloccato", "Cliente che blocca")]})


def _dati(c, contatto, dopo):
    eventi_nuovi = list(SandboxEvento.objects.filter(connessione=c, pk__gt=dopo).select_related("media").order_by("pk")[:100])
    conv = ConversazioneEsterna.objects.select_related("canale").filter(connessione=c, id_esterno=contatto, chiusa__isnull=True).first()
    return {"eventi": [{"id": e.pk, "verso": e.verso, "contatto": e.contatto, "testo": e.testo, "codice": e.codice, "richiesta": e.richiesta, "risposta": e.risposta,
                        "media": {"url": reverse("discuss:sandbox_media", args=[e.media.id_media]), "nome": e.media.nome, "immagine": e.media.mime.startswith("image/"), "audio": e.media.mime.startswith("audio/")} if e.media else None,
                        "ora": timezone.localtime(e.creato).strftime("%H:%M:%S")} for e in eventi_nuovi],
            "conversazione": {"url": reverse("discuss:canale", args=[conv.canale_id]), "gestita_da": conv.gestita_da, "fuori_finestra": conv.fuori_finestra} if conv else None}


@login_required
def eventi_vista(request, pk):
    c = _prova(request, pk)
    dopo = request.GET.get("dopo", "0")
    return JsonResponse(_dati(c, _contatto(request, c), int(dopo) if dopo.isdigit() else 0))


@login_required
@require_POST
def azione(request, pk):
    """Ciò che può succedere davvero: un messaggio, una foto, un messaggio ripetuto, una firma falsa, 24 ore che passano."""
    c = _prova(request, pk)
    contatto, nome = _contatto(request, c), " ".join(request.POST.get("nome", "").split())[:80] or "Cliente di prova"
    fa = request.POST.get("fa", "")
    if fa == "scrivi":
        testo = request.POST.get("testo", "").strip()[:4096]
        if testo:
            _arriva(c, contatto, *messaggio_cliente(c, contatto, nome, testo), testo)
    elif fa == "foto":
        media = conserva(c, "foto-di-prova.png", "image/png", _png_prova())
        didascalia = request.POST.get("testo", "").strip()[:1000]
        _arriva(c, contatto, *messaggio_cliente(c, contatto, nome, didascalia, "image", media), didascalia or "[foto]", media=media)
    elif fa == "file":
        f = request.FILES.get("file")
        if f is not None and f.size <= settings.ALLEGATI_MAX_MB * 1024 * 1024:
            mime = f.content_type or "application/octet-stream"
            tipo = "voice" if request.POST.get("vocale") else "image" if mime in ("image/jpeg", "image/png", "image/webp") else "audio" if mime.startswith("audio/") else "video" if mime == "video/mp4" else "document"
            media = conserva(c, f.name, mime, f.read())
            didascalia = request.POST.get("testo", "").strip()[:1000]
            _arriva(c, contatto, *messaggio_cliente(c, contatto, nome, didascalia, tipo, media), didascalia or f"[{tipo}] {f.name}", media=media)
    elif fa == "posizione":
        _arriva(c, contatto, *messaggio_cliente(c, contatto, nome, tipo="location"), "[posizione]")
    elif fa == "ripeti":
        # la piattaforma ripete un messaggio già consegnato: non deve contare due volte
        corpo, intestazioni = messaggio_cliente(c, contatto, nome, "Messaggio ripetuto dalla piattaforma")
        _arriva(c, contatto, corpo, intestazioni, "Messaggio ripetuto dalla piattaforma", "primo invio")
        _arriva(c, contatto, corpo, intestazioni, "Messaggio ripetuto dalla piattaforma", "ripetizione")
    elif fa == "firma":
        corpo, _ = messaggio_cliente(c, contatto, nome, "Messaggio con firma falsa")
        finta = {"X-Hub-Signature-256": "sha256=" + "0" * 64} if c.tipo == Connessione.WHATSAPP else {"X-Telegram-Bot-Api-Secret-Token": "falso"}
        _arriva(c, contatto, corpo, finta, "Messaggio con firma falsa", "firma falsa")
    elif fa == "stato" and c.tipo == Connessione.WHATSAPP:
        stato = "read" if request.POST.get("stato") == "read" else "delivered"
        ultimo = Messaggio.objects.filter(canale__esterna__connessione=c, canale__esterna__id_esterno=contatto).exclude(id_uscita="").order_by("-pk").first()
        if ultimo is not None:
            corpo, intestazioni = stato_whatsapp(c, ultimo.id_uscita, stato, contatto)
            _arriva(c, contatto, corpo, intestazioni, f"[stato: {stato}]")
    elif fa == "tempo":
        ConversazioneEsterna.objects.filter(connessione=c, id_esterno=contatto, chiusa__isnull=True).update(ultimo_in_arrivo=timezone.now() - connettori.FINESTRA_WHATSAPP * 1.05)
        SandboxEvento.objects.create(connessione=c, contatto=contatto, verso=SandboxEvento.ENTRATA, testo="[sono passate 25 ore]", richiesta={}, risposta={"prova": "tempo"}, codice=200)
    elif fa == "guasto":
        valore = request.POST.get("guasto", "")
        Connessione.objects.filter(pk=c.pk).update(sandbox_guasto=valore if valore in GUASTI else "")
    elif fa == "azzera":
        for conv in ConversazioneEsterna.objects.filter(connessione=c).select_related("canale"):
            conv.canale.delete()
        SandboxEvento.objects.filter(connessione=c).delete()
    dopo = request.POST.get("dopo", "0")
    return JsonResponse(_dati(c, contatto, int(dopo) if dopo.isdigit() else 0))


@login_required
def media_vista(request, id_media):
    f = get_object_or_404(SandboxMedia, id_media=id_media)
    _prova(request, f.connessione_id)
    risposta = HttpResponse(bytes(f.dati), content_type=f.mime if f.mime.startswith(("image/png", "image/jpeg", "audio/")) else "application/octet-stream")
    if not f.mime.startswith(("image/png", "image/jpeg", "audio/")):
        risposta["Content-Disposition"] = "attachment"
    risposta["X-Content-Type-Options"] = "nosniff"
    return risposta
