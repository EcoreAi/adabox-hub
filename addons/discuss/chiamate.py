"""Chiamate: chi entra, chi può esserci, e il centralino con cui i browser si collegano tra loro.

I media vanno da browser a browser (WebRTC): qui passano solo i messaggi per trovarsi. Un partecipante si riconosce dal
suo segreto, che vale anche per gli ospiti esterni: entrano col link, se la chiamata li ammette, e restano in attesa
finché un collega non li fa passare. Finché aspettano non ricevono né nomi né segnali degli altri."""
import asyncio
import base64
import datetime
import hashlib
import hmac
import json
import secrets
import time

from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.handlers.asgi import ASGIRequest
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from core import parametri

from . import eventi, servizi
from .models import Canale, Chiamata, Partecipante, Segnale

SCOMPARSO_SECONDI = 40                  # senza battito per tanto, si è fuori
SQUILLO_SECONDI = 60
MASSIMO_SEGNALE = 64_000
MASSIMO_IN_ATTESA = 10
INTERVALLO = 0.5
DURATA_MASSIMA = 280
BATTITO = 12
RIPROVA_MS = 2000
ORE_SENZA_NESSUNO = 24
DURATA_CREDENZIALI_TURN = 6 * 3600


# --- servizi ---

def attiva_del(canale):
    """La chiamata in corso nel canale, con quanti ci sono."""
    c = canale.chiamate.filter(finita__isnull=True).select_related("avviata_da").first()
    if c is not None:
        c.n_presenti = presenti(c).count()
    return c


def presenti(chiamata):
    return chiamata.partecipanti.filter(uscito__isnull=True, ammesso=True)


def avvia(canale, utente, video=True):
    """La chiamata del canale: si entra in quella in corso, altrimenti ne parte una."""
    with transaction.atomic():
        c = canale.chiamate.filter(finita__isnull=True).first()
        if c is not None:
            return c
        c = Chiamata.objects.create(canale=canale, avviata_da=utente, video=video, token=secrets.token_urlsafe(24))
        if not canale.vocale:
            servizi.avviso(canale, utente, f"{servizi.nome_di(utente)} ha avviato una {'videochiamata' if video else 'chiamata'}")
        eventi.emetti("chiamata", canale, token=c.token, video=video, autore=utente.pk, nome=servizi.nome_di(utente),
                      squilla=canale.diretto, url=reverse("discuss:chiamata", args=[c.token]))
    return c


def squilli_per(utente):
    """Le chiamate dirette appena partite, che questa persona non ha ancora raggiunto."""
    if not utente.has_perm("discuss.view_canale"):
        return []
    limite = timezone.now() - datetime.timedelta(seconds=SQUILLO_SECONDI)
    return list(Chiamata.objects.filter(finita__isnull=True, iniziata__gte=limite, canale__tipo=Canale.DIRETTO,
                                        canale__iscrizioni__utente=utente).exclude(avviata_da=utente)
                .exclude(partecipanti__utente=utente, partecipanti__uscito__isnull=True).select_related("avviata_da"))


def segnala(chiamata, tipo, da=None, a=None, **dati):
    return Segnale.objects.create(chiamata=chiamata, tipo=tipo, da=da, a=a, dati=dati)


def descrivi(p):
    return {"id": p.pk, "nome": p.nome, "ospite": p.utente_id is None, "microfono": p.microfono, "camera": p.camera,
            "schermo": p.schermo, "mano": p.mano}


@transaction.atomic
def entra(chiamata, utente=None, nome=""):
    """Un partecipante nuovo. Un collega passa subito; se aveva già una finestra aperta, quella esce."""
    if utente is not None:
        for vecchio in chiamata.partecipanti.filter(utente=utente, uscito__isnull=True):
            esci(vecchio, chiudi=False)
    ammesso = utente is not None
    p = Partecipante.objects.create(chiamata=chiamata, utente=utente, ammesso=ammesso, segreto=secrets.token_urlsafe(32),
                                    nome=(servizi.nome_di(utente) if utente else nome.strip())[:80] or "Ospite")
    if ammesso:
        segnala(chiamata, "entrato", da=p, **descrivi(p))
    else:
        segnala(chiamata, "bussa", da=p, id=p.pk, nome=p.nome)
    return p


def ammetti(p, si):
    if p.ammesso or p.uscito:
        return
    if si:
        p.ammesso = True
        p.save(update_fields=["ammesso"])
        segnala(p.chiamata, "ammesso", a=p, altri=[descrivi(x) for x in presenti(p.chiamata).exclude(pk=p.pk)])
        segnala(p.chiamata, "entrato", da=p, **descrivi(p))
    else:
        p.uscito = timezone.now()
        p.save(update_fields=["uscito"])
        segnala(p.chiamata, "rifiutato", a=p)
    segnala(p.chiamata, "attesa_chiusa", id=p.pk)


def esci(p, chiudi=True):
    if p.uscito:
        return
    p.uscito = timezone.now()
    p.save(update_fields=["uscito"])
    if p.ammesso:
        segnala(p.chiamata, "uscito", da=p, id=p.pk)
    else:
        segnala(p.chiamata, "attesa_chiusa", id=p.pk)
    if chiudi:
        chiudi_se_vuota(p.chiamata)


def chiudi_se_vuota(chiamata):
    if chiamata.finita or presenti(chiamata).exists():
        return
    # solo gli ospiti in attesa: senza colleghi nessuno può farli entrare
    for g in chiamata.partecipanti.filter(uscito__isnull=True, ammesso=False):
        g.uscito = timezone.now()
        g.save(update_fields=["uscito"])
    chiamata.finita = timezone.now()
    chiamata.save(update_fields=["finita"])
    segnala(chiamata, "fine")
    minuti = max(round((chiamata.finita - chiamata.iniziata).total_seconds() / 60), 1)
    if not chiamata.canale.vocale:
        servizi.avviso(chiamata.canale, chiamata.avviata_da, f"Chiamata terminata · {minuti} min")
    eventi.emetti("chiamata_fine", chiamata.canale, token=chiamata.token)


def togli_scomparsi(chiamata):
    """Chi ha chiuso il computer non saluta: passato il tempo senza battito, per gli altri è uscito."""
    limite = timezone.now() - datetime.timedelta(seconds=SCOMPARSO_SECONDI)
    for p in chiamata.partecipanti.filter(uscito__isnull=True, ultimo_visto__lt=limite):
        esci(p)


def pulisci():
    """Lavoro pianificato: chiude le chiamate rimaste aperte e butta i vecchi segnali."""
    chiuse = 0
    limite = timezone.now() - datetime.timedelta(hours=ORE_SENZA_NESSUNO)
    for c in Chiamata.objects.filter(finita__isnull=True):
        togli_scomparsi(c)
        c.refresh_from_db()
        if not c.finita and c.iniziata < limite and not presenti(c).exists():
            chiudi_se_vuota(c)
        chiuse += bool(c.finita)
    vecchi = Segnale.objects.filter(creato__lt=timezone.now() - datetime.timedelta(days=1)).delete()[0]
    return f"chiamate chiuse: {chiuse}, segnali eliminati: {vecchi}"


def server_ice():
    """I server per trovarsi. Le credenziali TURN durano poche ore: chi le vede in pagina non le riusa a lungo."""
    server = []
    if stun := (parametri.leggi("discuss.stun") or "").strip():
        server.append({"urls": stun})
    turn, segreto = (parametri.leggi("discuss.turn_url") or "").strip(), (parametri.leggi("discuss.turn_segreto") or "").strip()
    if turn and segreto:
        utente = str(int(time.time()) + DURATA_CREDENZIALI_TURN)
        firma = hmac.new(segreto.encode(), utente.encode(), hashlib.sha1).digest()
        server.append({"urls": turn, "username": utente, "credential": base64.b64encode(firma).decode()})
    return server


# --- chi è chi ---

def _chiamata(token):
    return get_object_or_404(Chiamata.objects.select_related("canale"), token=token)


def _e_collega(request, chiamata):
    """Un utente collegato che può stare in questo canale; quelli di un canale pubblico entrano nel canale."""
    return (request.user.is_authenticated and servizi.puo_vedere(request.user, chiamata.canale)
            and (chiamata.canale.tipo == Canale.PUBBLICO or servizi.iscrizione(request.user, chiamata.canale) is not None))


def _partecipante(request, token):
    """Il partecipante dal suo segreto: l'intestazione è una prova che un altro sito non può falsificare."""
    segreto = request.headers.get("X-Segreto") or request.GET.get("s", "")
    p = Partecipante.objects.select_related("chiamata", "chiamata__canale").filter(segreto=segreto, chiamata__token=token, uscito__isnull=True).first() if segreto else None
    if p is None:
        raise PermissionDenied
    return p


# --- pagine ---

@login_required
@permission_required("discuss.view_canale", raise_exception=True)
@require_POST
def avvia_vista(request, pk):
    canale = get_object_or_404(Canale, pk=pk, archiviato=False)
    if not servizi.puo_vedere(request.user, canale):
        raise Http404
    if servizi.iscrizione(request.user, canale) is None:
        raise PermissionDenied
    return redirect("discuss:chiamata", token=avvia(canale, request.user, request.POST.get("video") == "1").token)


@require_GET
@ensure_csrf_cookie
def pagina(request, token):
    """La stessa pagina per colleghi e ospiti: a un ospite non mostra niente del gestionale."""
    c = _chiamata(token)
    collega = _e_collega(request, c)
    if c.finita:
        return render(request, "discuss/chiamata_finita.html", {"collega": collega, "canale": c.canale}, status=410 if not collega else 200)
    if not collega:
        if c.ospiti_ammessi:
            return render(request, "discuss/chiamata.html", {"c": c, "collega": False, "titolo": "Riunione"})
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        raise Http404
    return render(request, "discuss/chiamata.html", {
        "c": c, "collega": True, "titolo": c.canale.titolo_per(request.user), "nome": servizi.nome_di(request.user),
        "url_ospiti": request.build_absolute_uri(reverse("discuss:chiamata", args=[c.token]))})


@require_POST
def entra_vista(request, token):
    c = _chiamata(token)
    if c.finita:
        return JsonResponse({"errore": "La chiamata è finita."}, status=410)
    collega = _e_collega(request, c)
    if not collega and not c.ospiti_ammessi:
        raise PermissionDenied
    massimo = parametri.leggi("discuss.max_partecipanti") or 8
    if presenti(c).count() >= massimo:
        return JsonResponse({"errore": f"La chiamata è al completo: al massimo {massimo} persone."}, status=409)
    if not collega:
        if not request.POST.get("nome", "").strip():
            return JsonResponse({"errore": "Scrivi il tuo nome."}, status=422)
        if c.partecipanti.filter(uscito__isnull=True, ammesso=False).count() >= MASSIMO_IN_ATTESA:
            return JsonResponse({"errore": "Troppe persone in attesa: riprova tra poco."}, status=429)
    if collega and c.canale.tipo == Canale.PUBBLICO:
        servizi.entra(c.canale, request.user)
    p = entra(c, request.user if collega else None, request.POST.get("nome", ""))
    p.microfono = request.POST.get("microfono", "1") == "1"
    p.camera = request.POST.get("camera", "1") == "1"
    p.save(update_fields=["microfono", "camera"])
    ultimo = c.segnali.order_by("-pk").values_list("pk", flat=True).first() or 0
    risposta = {"io": p.pk, "segreto": p.segreto, "ammesso": p.ammesso, "ice": server_ice(), "dopo": ultimo, "nome": p.nome}
    if p.ammesso:
        risposta["altri"] = [descrivi(x) for x in presenti(c).exclude(pk=p.pk)]
        risposta["attesa"] = [{"id": x.pk, "nome": x.nome} for x in c.partecipanti.filter(uscito__isnull=True, ammesso=False)]
    return JsonResponse(risposta)


@csrf_exempt
@require_POST
def segnale_vista(request, token):
    p = _partecipante(request, token)
    if not p.ammesso:
        raise PermissionDenied                     # chi aspetta non parla con nessuno
    if len(request.body) > MASSIMO_SEGNALE:
        return HttpResponse(status=413)
    try:
        dati = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    a = p.chiamata.partecipanti.filter(pk=dati.get("a"), uscito__isnull=True, ammesso=True).first()
    if a is None or dati.get("tipo") not in ("offerta", "risposta", "candidato"):
        return HttpResponse(status=204)
    segnala(p.chiamata, dati["tipo"], da=p, a=a, id=p.pk, corpo=dati.get("corpo"))
    return HttpResponse(status=204)


@csrf_exempt
@require_POST
def stato_vista(request, token):
    p = _partecipante(request, token)
    if not p.ammesso:
        raise PermissionDenied
    try:
        dati = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    campi = [c for c in ("microfono", "camera", "schermo", "mano") if isinstance(dati.get(c), bool)]
    for c in campi:
        setattr(p, c, dati[c])
    if campi:
        p.save(update_fields=campi)
        segnala(p.chiamata, "stato", da=p, **descrivi(p))
    return HttpResponse(status=204)


@csrf_exempt
@require_POST
def esci_vista(request, token):
    """Anche con sendBeacon alla chiusura della finestra, che manda il segreto nel corpo."""
    segreto = request.headers.get("X-Segreto") or request.POST.get("s", "") or request.body.decode(errors="ignore")
    p = Partecipante.objects.select_related("chiamata", "chiamata__canale").filter(segreto=segreto[:64], chiamata__token=token, uscito__isnull=True).first()
    if p is not None:
        esci(p)
    return HttpResponse(status=204)


def _collega_presente(request, token):
    c = _chiamata(token)
    if not _e_collega(request, c):
        raise PermissionDenied
    return c


@require_POST
def ammetti_vista(request, token):
    c = _collega_presente(request, token)
    g = get_object_or_404(Partecipante, pk=request.POST.get("id") if str(request.POST.get("id", "")).isdigit() else 0, chiamata=c, utente__isnull=True)
    ammetti(g, request.POST.get("si") == "1")
    return HttpResponse(status=204)


@require_POST
def ospiti_vista(request, token):
    """Apre o chiude la chiamata agli ospiti col link. Chiudendo, chi aspetta resta fuori."""
    c = _collega_presente(request, token)
    c.ospiti_ammessi = request.POST.get("si") == "1"
    c.save(update_fields=["ospiti_ammessi"])
    if not c.ospiti_ammessi:
        for g in c.partecipanti.filter(uscito__isnull=True, ammesso=False):
            ammetti(g, False)
    return JsonResponse({"ospiti": c.ospiti_ammessi})


# --- flusso dei segnali ---

def _testo(s):
    return f"id: {s.pk}\nevent: segnale\ndata: {json.dumps({'tipo': s.tipo, **s.dati}, ensure_ascii=False)}\n\n"


def passo(p_id, stato):
    """I segnali per questo partecipante, e il suo battito. (righe, finito)"""
    p = Partecipante.objects.select_related("chiamata").filter(pk=p_id).first()
    if p is None or p.uscito:
        return ["event: fuori\ndata: {}\n\n"], True
    ora = time.monotonic()
    if ora - stato.get("battito", 0) > BATTITO:
        stato["battito"] = ora
        Partecipante.objects.filter(pk=p.pk).update(ultimo_visto=timezone.now())
        togli_scomparsi(p.chiamata)
    # gli altri si sentono solo una volta ammessi; a chi aspetta arriva solo ciò che è per lui
    filtro = Q(a=p) | (Q(a__isnull=True) & ~Q(da=p)) if p.ammesso else Q(a=p)
    righe = list(Segnale.objects.filter(filtro, chiamata=p.chiamata, pk__gt=stato["dopo"]).order_by("pk")[:50])
    if righe:
        stato["dopo"] = righe[-1].pk
    return [_testo(s) for s in righe], any(s.tipo == "fine" for s in righe)


def _sincrono(p_id, stato):
    yield f"retry: {RIPROVA_MS}\n\n"
    yield from passo(p_id, stato)[0]


async def _asincrono(p_id, stato):
    funzione = sync_to_async(passo, thread_sensitive=False)
    yield f"retry: {RIPROVA_MS}\n\n"
    inizio = ultimo = time.monotonic()
    while time.monotonic() - inizio < DURATA_MASSIMA:
        righe, finito = await funzione(p_id, stato)
        for r in righe:
            yield r
        if finito:
            return
        if time.monotonic() - ultimo > BATTITO:
            ultimo = time.monotonic()
            yield ": battito\n\n"
        await asyncio.sleep(INTERVALLO)


@require_GET
def flusso(request, token):
    p = _partecipante(request, token)
    ripresa = request.headers.get("Last-Event-ID") or request.GET.get("dopo", "")
    stato = {"dopo": int(ripresa) if ripresa.isdigit() else 0}
    generatore = (_asincrono if isinstance(request, ASGIRequest) else _sincrono)(p.pk, stato)
    risposta = StreamingHttpResponse(generatore, content_type="text/event-stream; charset=utf-8")
    risposta["Cache-Control"] = "no-cache"
    risposta["X-Accel-Buffering"] = "no"
    return risposta
