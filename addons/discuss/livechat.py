"""La chat sul sito: un visitatore senza account scrive, gli operatori rispondono dalle Comunicazioni.

Queste pagine sono aperte a chiunque su internet, quindi: il token del visitatore è l'unica cosa che apre la sua
conversazione; si limita quante ne può aprire un indirizzo (di cui si tiene solo un'impronta) e quanto può scrivere; il
suo testo non fa scattare menzioni, schede né anteprime; solo i domini indicati possono incorporare la chat, e lo fa
rispettare il browser con Content-Security-Policy. La pagina sta in un iframe: cookie e sessione non servono."""
import datetime
import json
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.registry import modules

from core import lavori

from . import assistente_sito, eventi, presenza, servizi
from .models import Canale, ConversazioneEsterna, DomandaSenzaRisposta, Iscrizione, Messaggio, Sportello, VoceConoscenza

MASSIMO_TESTO = 2000
CHAT_PER_ORA = 5                        # nuove conversazioni da uno stesso indirizzo
MESSAGGI_AL_MINUTO = 20
MESSAGGI_RESTITUITI = 200
VISITATORE_ASSENTE_SECONDI = 90


def _sportello(chiave):
    s = Sportello.objects.filter(chiave=chiave, attivo=True).first()
    if s is None or not s.operatori.exists():
        raise Http404
    return s


def _impronta(request):
    # l'ultimo valore è quello aggiunto dal nostro nginx: i precedenti li sceglie chi fa la richiesta
    ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[-1].strip() or request.META.get("REMOTE_ADDR", "")
    return salted_hmac("discuss.livechat", ip).hexdigest()[:40]


def _qualcuno_online(sportello):
    stati = presenza.di(sportello.operatori.values_list("pk", flat=True))
    return any(presenza.stato_da(p) in (presenza.ONLINE, presenza.ASSENTE) for p in stati.values())


def _antenati(sportello):
    domini = [d.strip().lower() for d in sportello.domini.splitlines() if d.strip()]
    sicuri = [d for d in domini if all(c.isalnum() or c in ".-:" for c in d)]
    return " ".join(f"https://{d} http://{d}" for d in sicuri) or "'none'"


@require_GET
def widget(request, chiave):
    """Lo script da incollare sul sito: un pulsante e la finestra. Non tocca nulla della pagina che lo ospita."""
    s = _sportello(chiave)
    url = request.build_absolute_uri(reverse("discuss:lc_finestra", args=[s.chiave]))
    corpo = """(function () {
  if (window.__dsLivechat) return; window.__dsLivechat = true;
  var url = %s, aperta = false, fr = null;
  var b = document.createElement('button');
  b.type = 'button'; b.setAttribute('aria-label', 'Apri la chat'); b.textContent = '\\uD83D\\uDCAC';
  b.style.cssText = 'position:fixed;right:20px;bottom:20px;z-index:2147483000;width:56px;height:56px;border:0;border-radius:50%%;background:#2563eb;color:#fff;font-size:24px;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.28)';
  b.addEventListener('click', function () {
    aperta = !aperta;
    if (aperta && !fr) {
      fr = document.createElement('iframe');
      fr.title = 'Chat'; fr.src = url + '?pagina=' + encodeURIComponent(location.href.slice(0, 280));
      fr.style.cssText = 'position:fixed;right:20px;bottom:88px;z-index:2147483000;width:min(380px,calc(100vw - 40px));height:min(560px,calc(100vh - 120px));border:0;border-radius:16px;background:#fff;box-shadow:0 18px 50px rgba(0,0,0,.3)';
      document.body.appendChild(fr);
    }
    if (fr) fr.style.display = aperta ? 'block' : 'none';
    b.setAttribute('aria-label', aperta ? 'Chiudi la chat' : 'Apri la chat');
    b.textContent = aperta ? '\\u00D7' : '\\uD83D\\uDCAC';
  });
  (document.body || document.documentElement).appendChild(b);
}());
""" % json.dumps(url)
    risposta = HttpResponse(corpo, content_type="application/javascript; charset=utf-8")
    risposta["Cache-Control"] = "public, max-age=300"
    return risposta


@require_GET
@xframe_options_exempt
def finestra(request, chiave):
    s = _sportello(chiave)
    risposta = render(request, "discuss/livechat.html", {"s": s, "online": _qualcuno_online(s), "pagina": request.GET.get("pagina", "")[:280],
                                                         "usa_ai": assistente_sito.usa_ai(s)})
    risposta["Content-Security-Policy"] = f"frame-ancestors {_antenati(s)}"
    return risposta


@csrf_exempt
@require_POST
def avvia(request, chiave):
    s = _sportello(chiave)
    if request.POST.get("sito_web"):               # campo nascosto: lo compilano solo i programmi
        return JsonResponse({"errore": "Non è stato possibile inviare il messaggio."}, status=400)
    usa_ai = assistente_sito.usa_ai(s)
    nome = " ".join(request.POST.get("nome", "").split())[:80] or ("Visitatore" if usa_ai else "")
    testo = request.POST.get("testo", "").strip()[:MASSIMO_TESTO]
    email = request.POST.get("email", "").strip()[:254]
    if not nome or not testo:
        return JsonResponse({"errore": "Scrivi il tuo nome e un messaggio."}, status=422)
    if email:
        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse({"errore": "L'email non sembra corretta."}, status=422)
    impronta = _impronta(request)
    limite = timezone.now() - datetime.timedelta(hours=1)
    if ConversazioneEsterna.objects.filter(impronta_ip=impronta, creata__gte=limite).count() >= CHAT_PER_ORA:
        return JsonResponse({"errore": "Troppe conversazioni aperte: riprova più tardi."}, status=429)
    canale = Canale.objects.create(nome=f"{nome} · {s.nome}"[:80], tipo=Canale.PRIVATO, livechat=True, descrizione=f"Chat dal sito: {s.nome}"[:250])
    for u in s.operatori.filter(is_active=True):
        servizi.iscrivi(canale, u, 0, ruolo=Iscrizione.MODERATORE)
        # chi segue una chat dal sito vuole sapere di ogni messaggio
        Iscrizione.objects.filter(canale=canale, utente=u).update(notifiche=Iscrizione.TUTTO)
        eventi.emetti("barra", utente=u)
    c = ConversazioneEsterna.objects.create(sportello=s, canale=canale, token=secrets.token_urlsafe(32), nome=nome, email=email,
                                            pagina=request.POST.get("pagina", "")[:300], impronta_ip=impronta,
                                            gestita_da=ConversazioneEsterna.AI if usa_ai else ConversazioneEsterna.PERSONA)
    _dal_visitatore(c, testo)
    return JsonResponse({"token": c.token})


def _dal_visitatore(c, testo):
    """Il messaggio del visitatore: va alle persone, o all'AI finché risponde lei."""
    with_ai = c.gestita_da == ConversazioneEsterna.AI
    m = servizi.invia(c.canale, None, testo, esterno=c.nome, silenzioso=with_ai)
    if with_ai:
        lavori.accoda("discuss.assistente_sito.rispondi", conversazione=c.pk, messaggio=m.pk, max_tentativi=1)
    return m


def _visitatore(request, chiave):
    token = request.headers.get("X-Token", "")
    c = ConversazioneEsterna.objects.select_related("canale", "sportello").filter(token=token, sportello__chiave=chiave).first() if token else None
    if c is None:
        raise PermissionDenied
    return c


def _per_visitatore(m):
    """Solo ciò che il visitatore deve vedere: niente avvisi interni, messaggi tolti o nomi utente."""
    if m.da_ai:
        return {"id": m.pk, "mio": False, "nome": m.autore_esterno, "testo": m.corpo, "ai": True}
    if m.autore_esterno:
        return {"id": m.pk, "mio": True, "nome": m.autore_esterno, "testo": m.corpo}
    nome = (m.autore.first_name or m.autore.username) if m.autore else "Operatore"
    return {"id": m.pk, "mio": False, "nome": nome, "testo": m.corpo or "(ha inviato un allegato: te lo manderemo in altro modo)"}


@csrf_exempt
@require_GET
def messaggi(request, chiave):
    c = _visitatore(request, chiave)
    dopo = request.GET.get("dopo", "0")
    elenco = (c.canale.messaggi.filter(pk__gt=int(dopo) if dopo.isdigit() else 0, tipo=Messaggio.NORMALE, eliminato=False)
              .select_related("autore").order_by("pk")[:MESSAGGI_RESTITUITI])
    ConversazioneEsterna.objects.filter(pk=c.pk).update(ultimo_visto=timezone.now())
    ultimo = c.canale.messaggi.filter(tipo=Messaggio.NORMALE, eliminato=False).order_by("-pk").first()
    con_ai = c.gestita_da == ConversazioneEsterna.AI
    return JsonResponse({"messaggi": [_per_visitatore(m) for m in elenco], "chiusa": bool(c.chiusa), "online": _qualcuno_online(c.sportello),
                         "con_ai": con_ai, "ai_scrive": con_ai and ultimo is not None and bool(ultimo.autore_esterno) and not ultimo.da_ai,
                         "chiedi_persona": con_ai and c.sportello.modalita == Sportello.AI})


@csrf_exempt
@require_POST
def scrivi(request, chiave):
    c = _visitatore(request, chiave)
    if c.chiusa:
        return JsonResponse({"errore": "Questa conversazione è chiusa."}, status=409)
    testo = request.POST.get("testo", "").strip()[:MASSIMO_TESTO]
    if not testo:
        return JsonResponse({"errore": "Il messaggio è vuoto."}, status=422)
    limite = timezone.now() - datetime.timedelta(minutes=1)
    if c.canale.messaggi.filter(autore__isnull=True, autore_esterno__gt="", creato__gte=limite).count() >= MESSAGGI_AL_MINUTO:
        return JsonResponse({"errore": "Stai scrivendo troppo in fretta: aspetta un momento."}, status=429)
    m = _dal_visitatore(c, testo)
    return JsonResponse({"id": m.pk})


@csrf_exempt
@require_POST
def persona(request, chiave):
    """Il visitatore chiede una persona: l'AI si fa da parte."""
    c = _visitatore(request, chiave)
    if c.sportello.modalita == Sportello.AI and c.gestita_da == ConversazioneEsterna.AI and not c.chiusa:
        assistente_sito.passa_a_persona(c, "Il visitatore ha chiesto di parlare con una persona")
    return HttpResponse(status=204)


def _gestore_sportello(request, pk):
    if not request.user.has_perm("discuss.change_sportello"):
        raise PermissionDenied
    return get_object_or_404(Sportello, pk=pk)


@login_required
@require_POST
def carica_conoscenza(request, pk):
    """Documenti per l'AI del sito: se ne tiene il testo, che si può rileggere e correggere."""
    s = _gestore_sportello(request, pk)
    caricati, scartati = 0, []
    for f in request.FILES.getlist("file"):
        testo = assistente_sito.testo_del_file(f.name, f.read()).strip()
        if not testo:
            scartati.append(f.name)
            continue
        VoceConoscenza.objects.create(sportello=s, tipo=VoceConoscenza.DOCUMENTO, titolo=f.name[:200], testo=testo)
        caricati += 1
    if caricati:
        messages.success(request, f"Documenti aggiunti alla conoscenza: {caricati}. Controlla il testo: l'AI può riferire tutto ai visitatori.")
    if scartati:
        messages.error(request, "Non sono riuscito a leggere: " + ", ".join(scartati))
    return redirect("discuss:sportelli_dettaglio", pk=s.pk)


@login_required
@require_POST
def domanda_risolta(request, pk):
    d = get_object_or_404(DomandaSenzaRisposta, pk=pk)
    _gestore_sportello(request, d.sportello_id)
    d.risolta = True
    d.save(update_fields=["risolta"])
    return redirect("discuss:sportelli_dettaglio", pk=d.sportello_id)


@login_required
@permission_required("discuss.view_canale", raise_exception=True)
@require_POST
def chiudi(request, pk):
    """L'operatore chiude: il visitatore lo vede e la chat esce dall'elenco, ma resta cercabile e nello storico."""
    canale = get_object_or_404(Canale, pk=pk, livechat=True)
    if servizi.iscrizione(request.user, canale) is None:
        raise Http404
    ConversazioneEsterna.objects.filter(canale=canale, chiusa__isnull=True).update(chiusa=timezone.now())
    canale.archiviato = True
    canale.save(update_fields=["archiviato"])
    servizi.avviso(canale, request.user, f"{servizi.nome_di(request.user)} ha chiuso la chat")
    for i in canale.iscrizioni.all():
        eventi.emetti("barra", utente=i.utente)
    return redirect("discuss:home")


def avvisa_visitatore(messaggio):
    """Se il visitatore ha lasciato la pagina prima della risposta e ha dato l'email, la risposta gli arriva lì."""
    m = Messaggio.objects.select_related("canale", "autore").filter(pk=messaggio, eliminato=False).first()
    if m is None or not m.canale.livechat or "discuss" in modules.disattivati():
        return "niente"
    c = ConversazioneEsterna.objects.select_related("sportello").filter(canale=m.canale).first()
    if c is None or not c.email or not m.corpo or c.chiusa:
        return "niente"
    if (timezone.now() - c.ultimo_visto).total_seconds() < VISITATORE_ASSENTE_SECONDI:
        return "è ancora sulla pagina"
    # si scrive una sola volta tra una visita e l'altra: i messaggi successivi aspettano che torni
    if c.canale.messaggi.filter(pk__gt=m.pk, autore__isnull=False, tipo=Messaggio.NORMALE, eliminato=False).exists():
        return "c'è una risposta più recente"
    send_mail(f"Risposta da {c.sportello.nome}", f"{m.corpo}\n\n—\n{c.sportello.nome}\nÈ una risposta alla chat sul sito: non rispondere a questa email, torna sul sito per continuare.",
              None, [c.email], fail_silently=True)
    return "email inviata"
