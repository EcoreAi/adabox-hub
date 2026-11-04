"""Discuss: la conversazione, i pannelli laterali, le azioni sui messaggi, canali, gruppi, presenza e ricerca."""
import datetime
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import allegati, attivita, chatter
from core.generici import ct_di, vista_e_oggetto
from core.models import Allegato, TipoAttivita
from core.models import Messaggio as MessaggioChatter

from . import assegnazioni, chiamate, eventi, ia, notifiche, presenza as presenze, schede, servizi, testo
from .models import Canale, ConversazioneEsterna, Iscrizione, Messaggio, Notifica, Presenza

PERMESSO = "discuss.view_canale"
EMOJI_MASSIMA = 16
FILTRI_POSTA = {"menzioni": [Notifica.MENZIONE, Notifica.RISPOSTA], "diretti": [Notifica.DIRETTO, Notifica.CANALE],
                "record": [Notifica.RECORD], "attivita": [Notifica.ATTIVITA]}


def _canale(request, pk):
    canale = get_object_or_404(Canale, pk=pk)
    if not servizi.puo_vedere(request.user, canale):
        raise Http404
    return canale


def _prepara(request, elenco, precedente=None):
    servizi.prepara(elenco, request.user, precedente)
    schede.arricchisci(request, elenco)
    return elenco


def _colleghi(request):
    return get_user_model().objects.filter(is_active=True).exclude(pk=request.user.pk).order_by("first_name", "username")


def _utenti_scelti(request, campo="utenti"):
    scelti = [p for p in request.POST.getlist(campo) if p.isdigit()]
    return get_user_model().objects.filter(pk__in=scelti, is_active=True)


def _diritti(request, canale):
    """Ciò che i template dei messaggi devono sapere su questa persona in questo canale."""
    return {"puo_moderare": servizi.puo_moderare(request.user, canale), "puo_fissare": servizi.puo_fissare(request.user, canale),
            "puo_scrivere": servizi.puo_scrivere(request.user, canale),
            "puo_reagire": servizi.iscrizione(request.user, canale) is not None and not canale.archiviato,
            "puo_trascrivere": ia.trascrizione_attiva()}


def _clienti(request, iscrizioni):
    """Le chat con i clienti di chi guarda: le sue, quelle da prendere e, a parte, quelle dei colleghi."""
    gruppi = {"clienti_miei": [], "clienti_liberi": [], "clienti_ai": [], "clienti_altri": []}
    for i in iscrizioni:
        if not i.canale.livechat or i.fissata:
            continue
        e = getattr(i.canale, "esterna", None)
        if e is not None and e.assegnata_a_id == request.user.pk:
            gruppi["clienti_miei"].append(i)
        elif e is not None and e.assegnata_a_id:
            i.incaricato = servizi.nome_di(e.assegnata_a)
            gruppi["clienti_altri"].append(i)
        elif e is not None and e.gestita_da == ConversazioneEsterna.AI:
            gruppi["clienti_ai"].append(i)
        else:
            gruppi["clienti_liberi"].append(i)
    gruppi["ha_clienti"] = any(gruppi.values())
    return gruppi


def _barra(request, corrente=None):
    """Elenco delle conversazioni: preferiti, canali e messaggi diretti, con presenza e non letti."""
    iscrizioni = list(servizi.iscrizioni_di(request.user))
    persone = {u.pk for i in iscrizioni if i.canale.diretto for u in i.canale.membri.all()}
    stati = presenze.di(persone)
    for i in iscrizioni:
        i.titolo = i.canale.titolo_per(request.user)
        if i.canale.diretto:
            altri = [u for u in i.canale.membri.all() if u.pk != request.user.pk]
            i.altri = altri
            i.presenza = presenze.scheda(stati.get(altri[0].pk)) if len(altri) == 1 else None
    return {"preferiti": [i for i in iscrizioni if i.fissata],
            "canali": [i for i in iscrizioni if not i.canale.diretto and not i.fissata and not i.canale.vocale and not i.canale.livechat],
            **_clienti(request, iscrizioni),
            "vocali": [i for i in iscrizioni if i.canale.vocale and not i.fissata],
            "diretti": [i for i in iscrizioni if i.canale.diretto and not i.fissata],
            "corrente": corrente, "corrente_pk": corrente.pk if corrente else None,
            "da_scoprire": servizi.pubblici_da_scoprire(request.user),
            "posta_non_letta": notifiche.non_lette(request.user)}


def _contesto(request, canale=None):
    presenze.tocca(request.user)               # chi apre la pagina è collegato, senza aspettare il primo battito
    contesto = _barra(request, canale)
    p = presenze.mia(request.user)
    contesto.update({"utenti": _colleghi(request), "evento": eventi.ultimo_id(), "mia_presenza": p,
                     "mia_scheda": presenze.scheda(p), "stati": Presenza.STATI})
    return contesto


@login_required
@permission_required(PERMESSO, raise_exception=True)
def home(request):
    iscrizioni = list(servizi.iscrizioni_di(request.user))
    # una conversazione segnata da leggere non si apre da sola: aprirla la segnerebbe come letta
    scelta = next((i for i in iscrizioni if not i.tieni_non_letto), None)
    if scelta:
        coda = f"?cerca={request.GET['cerca']}" if request.GET.get("cerca") else ""
        return redirect(reverse("discuss:canale", args=[scelta.canale_id]) + coda)
    return render(request, "discuss/home.html", _contesto(request))


@login_required
@permission_required(PERMESSO, raise_exception=True)
def barra(request):
    corrente = request.GET.get("corrente", "")
    canale = None
    if corrente.isdigit():
        canale = Canale.objects.filter(pk=corrente).first()
        canale = canale if canale is not None and servizi.puo_vedere(request.user, canale) else None
    return render(request, "discuss/_barra.html", _barra(request, canale))


def _dati_canale(request, canale):
    """Testata della conversazione: nome, presenza dell'altra persona, chi può fare cosa."""
    membri = list(canale.membri.order_by("first_name", "username"))
    altri = [u for u in membri if u.pk != request.user.pk]
    dati = {"canale": canale, "titolo": canale.titolo_per(request.user), "membri": membri,
            "n_fissati": canale.messaggi.filter(fissato_il__isnull=False, eliminato=False).count(),
            "puo_gestire": servizi.puo_gestire(request.user, canale), "chiamata_attiva": chiamate.attiva_del(canale),
            "ia_attiva": ia.disponibile(request.user), "esterna": getattr(canale, "esterna", None) if canale.livechat else None,
            "operatori_chat": assegnazioni.operatori_di(canale),
            **_diritti(request, canale)}
    if canale.diretto and len(altri) == 1:
        dati["altra"] = altri[0]
        dati["altra_presenza"] = presenze.scheda(presenze.di([altri[0].pk]).get(altri[0].pk))
        dati["altra_persona"] = servizi.nome_di(altri[0])
    return dati


@login_required
@permission_required(PERMESSO, raise_exception=True)
def canale(request, pk):
    canale = _canale(request, pk)
    iscrizione = servizi.iscrizione(request.user, canale)
    bersaglio = request.GET.get("a", "")
    contesto = _contesto(request, canale)
    if bersaglio.isdigit() and canale.messaggi.filter(pk=bersaglio).exists():
        # si arriva a un messaggio preciso: si legge lo storico, senza toccare i non letti
        elenco = servizi.attorno(canale, int(bersaglio))
        recenti = elenco and canale.messaggi.filter(pk__gt=elenco[-1].pk).exists()
        contesto.update({"bersaglio": int(bersaglio), "in_storico": bool(recenti)})
        primo_non_letto = None
    else:
        elenco = servizi.messaggi(canale)
        ultimo_letto = iscrizione.ultimo_letto if iscrizione else None
        if iscrizione and iscrizione.tieni_non_letto:
            Iscrizione.objects.filter(pk=iscrizione.pk).update(tieni_non_letto=False)
        if iscrizione and elenco:
            Iscrizione.objects.filter(pk=iscrizione.pk, ultimo_letto__lt=elenco[-1].pk).update(ultimo_letto=elenco[-1].pk)
            eventi.emetti("barra", utente=request.user)
        notifiche.segna_lette_del_canale(request.user, canale)
        primo_non_letto = next((m.pk for m in elenco if ultimo_letto is not None and m.pk > ultimo_letto
                                and m.autore_id != request.user.pk and m.tipo == Messaggio.NORMALE), None)
        contesto.update(_barra(request, canale))
    precedente = canale.messaggi.filter(pk__lt=elenco[0].pk).order_by("-pk").first() if elenco else None
    contesto.update(_dati_canale(request, canale))
    contesto.update({"iscrizione": iscrizione, "messaggi": _prepara(request, elenco, precedente),
                     "primo_non_letto": primo_non_letto, "ultimo": elenco[-1].pk if elenco else 0,
                     "altro_prima": len(elenco) >= servizi.PAGINA // 2 and precedente is not None,
                     "cerca_iniziale": request.GET.get("cerca", "")})
    return render(request, "discuss/home.html", contesto)


@login_required
@permission_required(PERMESSO, raise_exception=True)
def nuovi(request, pk):
    """I messaggi dopo `dopo` e un nuovo poller (sostituisce il precedente)."""
    canale = _canale(request, pk)
    dopo = request.GET.get("dopo", "0")
    dopo = int(dopo) if dopo.isdigit() else 0
    elenco = servizi.messaggi(canale, dopo=dopo)
    ultimo = elenco[-1].pk if elenco else dopo
    if elenco and servizi.iscrizione(request.user, canale):
        servizi.segna_letto(request.user, canale, ultimo)
        notifiche.segna_lette_del_canale(request.user, canale)
    precedente = canale.messaggi.filter(pk__lte=dopo).order_by("-pk").first()
    return render(request, "discuss/_nuovi.html", {"canale": canale, "ultimo": ultimo,
                                                   "messaggi": _prepara(request, elenco, precedente),
                                                   **_diritti(request, canale)})


@login_required
@permission_required(PERMESSO, raise_exception=True)
def precedenti(request, pk):
    canale = _canale(request, pk)
    prima = request.GET.get("prima", "")
    elenco = servizi.messaggi(canale, prima=int(prima) if prima.isdigit() else None)
    precedente = canale.messaggi.filter(pk__lt=elenco[0].pk).order_by("-pk").first() if elenco else None
    return render(request, "discuss/_precedenti.html", {"canale": canale, "messaggi": _prepara(request, elenco, precedente),
                                                        "altro_prima": len(elenco) == servizi.PAGINA,
                                                        **_diritti(request, canale)})


@login_required
@permission_required("discuss.add_messaggio", raise_exception=True)
@require_POST
def invia(request, pk):
    canale = _canale(request, pk)
    if not servizi.puo_scrivere(request.user, canale):
        raise PermissionDenied                       # si scrive solo nei canali in cui si è entrati, e se il ruolo lo consente
    risposta_a = None
    if request.POST.get("risposta_a", "").isdigit():
        risposta_a = canale.messaggi.filter(pk=request.POST["risposta_a"]).first()
    try:
        servizi.invia(canale, request.user, request.POST.get("corpo", ""), request.FILES.getlist("file"), risposta_a,
                      host=request.get_host())
    except (ValueError, allegati.AllegatoNonValido) as e:
        if request.headers.get("HX-Request"):
            return HttpResponse(str(e), status=422)
        messages.error(request, str(e))
    if request.headers.get("HX-Request"):
        risposta = HttpResponse(status=204)
        risposta["HX-Trigger"] = "ds-nuovi"
        return risposta
    return redirect("discuss:canale", pk=canale.pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def scrivo(request, pk):
    """«Sta scrivendo…»: il browser lo manda al massimo ogni qualche secondo."""
    canale = _canale(request, pk)
    if servizi.iscrizione(request.user, canale):
        eventi.emetti("scrive", canale, autore=request.user.pk, nome=servizi.nome_di(request.user))
    return HttpResponse(status=204)


def _rendi_messaggio(request, messaggio):
    canale = messaggio.canale
    precedente = canale.messaggi.filter(pk__lt=messaggio.pk).order_by("-pk").first()
    _prepara(request, [messaggio], precedente)
    # solo in un aggiornamento: il divisore del giorno è già nella pagina
    messaggio.giorno = ""
    return render(request, "discuss/_messaggio.html", {"m": messaggio, "canale": canale, **_diritti(request, canale)})


def _messaggio_visibile(request, pk):
    messaggio = servizi.uno(pk)
    if messaggio is None or not servizi.puo_vedere(request.user, messaggio.canale):
        raise Http404
    return messaggio


@login_required
@permission_required(PERMESSO, raise_exception=True)
def messaggio(request, pk):
    return _rendi_messaggio(request, _messaggio_visibile(request, pk))


def _mio_messaggio(request, pk):
    messaggio = get_object_or_404(Messaggio.objects.select_related("canale", "autore", "risposta_a__autore"), pk=pk, eliminato=False)
    if messaggio.autore_id != request.user.pk or not servizi.puo_vedere(request.user, messaggio.canale):
        raise PermissionDenied
    return messaggio


@login_required
@permission_required(PERMESSO, raise_exception=True)
def modifica(request, pk):
    messaggio = _mio_messaggio(request, pk)
    if request.method == "POST":
        corpo = request.POST.get("corpo", "").strip()
        if corpo:
            servizi.modifica(messaggio, corpo)
        return _rendi_messaggio(request, messaggio)
    if request.GET.get("annulla"):
        return _rendi_messaggio(request, messaggio)
    return render(request, "discuss/_modifica.html", {"m": messaggio})


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def elimina(request, pk):
    messaggio = _messaggio_visibile(request, pk)
    if messaggio.eliminato:
        raise Http404
    if messaggio.autore_id != request.user.pk and not servizi.puo_moderare(request.user, messaggio.canale):
        raise PermissionDenied
    servizi.elimina(messaggio)
    return _rendi_messaggio(request, messaggio)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def reazione(request, pk):
    messaggio = _messaggio_visibile(request, pk)
    emoji = request.POST.get("emoji", "").strip()
    if messaggio.eliminato or messaggio.tipo != Messaggio.NORMALE or not emoji or len(emoji) > EMOJI_MASSIMA or emoji.isalnum():
        return HttpResponse(status=422)
    if servizi.iscrizione(request.user, messaggio.canale) is None:
        raise PermissionDenied
    servizi.reagisci(messaggio, request.user, emoji)
    return _rendi_messaggio(request, messaggio)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def fissa(request, pk):
    messaggio = _messaggio_visibile(request, pk)
    if messaggio.eliminato or not servizi.puo_fissare(request.user, messaggio.canale):
        raise PermissionDenied
    servizi.fissa(messaggio, request.user)
    return _rendi_messaggio(request, messaggio)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def da_leggere(request, pk):
    messaggio = _messaggio_visibile(request, pk)
    servizi.segna_da_leggere(request.user, messaggio)
    return HttpResponse(status=204)


def _pannello(request, template, canale, **altro):
    return render(request, template, {"canale": canale, **altro, **_diritti(request, canale)})


@login_required
@permission_required(PERMESSO, raise_exception=True)
def pannello_fissati(request, pk):
    canale = _canale(request, pk)
    return _pannello(request, "discuss/_pannello_fissati.html", canale, voci=servizi.fissati(canale))


@login_required
@permission_required(PERMESSO, raise_exception=True)
def pannello_file(request, pk):
    canale = _canale(request, pk)
    voci = servizi.file_del_canale(canale)
    for a in voci:
        a.tipo_file = servizi._tipo_file(a)
    return _pannello(request, "discuss/_pannello_file.html", canale, voci=voci)


def _rendi_info(request, canale):
    iscrizioni = list(canale.iscrizioni.select_related("utente").order_by("utente__first_name", "utente__username"))
    stati = presenze.di(i.utente_id for i in iscrizioni)
    for i in iscrizioni:
        i.scheda = presenze.scheda(stati.get(i.utente_id))
    presenti = {i.utente_id for i in iscrizioni}
    return _pannello(request, "discuss/_pannello_info.html", canale, iscrizioni=iscrizioni, ruoli=Iscrizione.RUOLI,
                     mia=servizi.iscrizione(request.user, canale), puo_gestire=servizi.puo_gestire(request.user, canale),
                     da_aggiungere=_colleghi(request).exclude(pk__in=presenti), notifiche_scelte=Iscrizione.NOTIFICHE)


@login_required
@permission_required(PERMESSO, raise_exception=True)
def pannello_info(request, pk):
    return _rendi_info(request, _canale(request, pk))


@login_required
@permission_required(PERMESSO, raise_exception=True)
def pannello_risposte(request, pk):
    messaggio = _messaggio_visibile(request, pk)
    elenco = servizi.risposte_a(messaggio)
    return _pannello(request, "discuss/_pannello_risposte.html", messaggio.canale, origine=messaggio,
                     voci=_prepara(request, [messaggio, *elenco])[1:])


@login_required
@permission_required(PERMESSO, raise_exception=True)
def cerca(request):
    q = request.GET.get("q", "").strip()
    canale = None
    if request.GET.get("canale", "").isdigit() and request.GET.get("solo"):
        canale = _canale(request, request.GET["canale"])
    voci = servizi.cerca(request.user, q, canale)
    return render(request, "discuss/_pannello_cerca.html", {"q": q, "voci": voci, "canale": canale, "titolo_di": request.user,
                                                            "corrente_pk": request.GET.get("canale", "")})


def _voce_persona(u):
    return {"tipo": "persona", "testo": servizi.nome_di(u), "dettaglio": f"@{u.username}", "valore": u.username,
            "url": reverse("discuss:con", args=[u.username])}


@login_required
@permission_required(PERMESSO, raise_exception=True)
def suggerisci(request):
    """Il completamento di @persona e #canale nel campo di scrittura."""
    q = request.GET.get("q", "").strip()
    if request.GET.get("tipo") == "canali":
        elenco = servizi.visibili(request.user).exclude(tipo=Canale.DIRETTO).filter(archiviato=False, nome__icontains=q)[:8]
        return JsonResponse({"voci": [{"testo": f"#{c.nome}", "dettaglio": c.descrizione[:60], "valore": c.nome.replace(" ", "-")}
                                      for c in elenco if c.nome]})
    persone = get_user_model().objects.filter(is_active=True).filter(
        Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)).order_by("first_name", "username")[:8]
    stati = presenze.di(u.pk for u in persone)
    return JsonResponse({"voci": [{**_voce_persona(u), "stato": presenze.scheda(stati.get(u.pk))["stato"]} for u in persone]})


@login_required
def palette(request):
    """Ctrl+K da qualsiasi pagina: persone, canali e voci fisse."""
    if not request.user.has_perm(PERMESSO):
        return JsonResponse({"voci": []})
    q = request.GET.get("q", "").strip()
    voci = []
    if q:
        canali = servizi.visibili(request.user).exclude(tipo=Canale.DIRETTO).filter(archiviato=False, nome__icontains=q)[:6]
        voci += [{"tipo": "canale", "testo": c.nome, "dettaglio": c.descrizione[:70],
                  "url": reverse("discuss:canale", args=[c.pk])} for c in canali]
        persone = _colleghi(request).filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))[:6]
        stati = presenze.di(u.pk for u in persone)
        voci += [{**_voce_persona(u), "stato": presenze.scheda(stati.get(u.pk))["stato"]} for u in persone]
        voci.append({"tipo": "cerca", "testo": f"Cerca «{q}» nei messaggi", "dettaglio": "",
                     "url": reverse("discuss:home") + "?" + _coda({"cerca": q})})
    else:
        recenti = list(servizi.iscrizioni_di(request.user)[:6])
        voci += [{"tipo": "persona" if i.canale.diretto else "canale", "testo": i.canale.titolo_per(request.user).removeprefix("# "),
                  "dettaglio": f"{i.non_letti} non letti" if i.non_letti else "",
                  "url": reverse("discuss:canale", args=[i.canale_id])} for i in recenti]
        voci.append({"tipo": "posta", "testo": "Posta in arrivo", "dettaglio": "", "url": reverse("discuss:posta")})
    return JsonResponse({"voci": voci})


def _coda(valori):
    return urlencode(valori)


@login_required
@permission_required(PERMESSO, raise_exception=True)
def con(request, username):
    """Clic su una @menzione o su una persona: apre il messaggio diretto."""
    altro = get_user_model().objects.filter(username__iexact=username, is_active=True).first()
    if altro is None:
        messages.error(request, f"Nessun collega si chiama «{username}».")
        return redirect("discuss:home")
    return redirect("discuss:canale", pk=servizi.diretto([request.user, altro]).pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
def vai(request, nome):
    """Clic su un #canale."""
    for c in servizi.visibili(request.user).exclude(tipo=Canale.DIRETTO).filter(archiviato=False):
        if c.nome.lower().replace(" ", "-") == nome.lower():
            return redirect("discuss:canale", pk=c.pk)
    messages.error(request, f"Il canale «{nome}» non c'è o non puoi vederlo.")
    return redirect("discuss:home")


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def presenza(request):
    """Lo stato scelto da una persona: non disturbare, assente, fuori ufficio con data e messaggio."""
    p = presenze.mia(request.user)
    stato = request.POST.get("stato", Presenza.AUTO)
    p.stato = stato if stato in dict(Presenza.STATI) else Presenza.AUTO
    p.messaggio = request.POST.get("messaggio", "").strip()[:140]
    try:
        p.fuori_fino = datetime.date.fromisoformat(request.POST.get("fuori_fino", ""))
    except ValueError:
        p.fuori_fino = None
    p.save(update_fields=["stato", "messaggio", "fuori_fino"])
    return redirect(request.POST.get("torna") if str(request.POST.get("torna", "")).startswith("/discuss/") else "discuss:home")


@login_required
@permission_required(PERMESSO, raise_exception=True)
def allegato(request, pk):
    allegato = get_object_or_404(Allegato, pk=pk, content_type=ct_di(Messaggio))
    messaggio = get_object_or_404(Messaggio, pk=allegato.object_id)
    if not servizi.puo_vedere(request.user, messaggio.canale):
        raise Http404
    return allegati.risposta(allegato)


@login_required
@permission_required("discuss.add_canale", raise_exception=True)
@require_POST
def nuovo_canale(request):
    nome = request.POST.get("nome", "").strip()
    if not nome:
        messages.error(request, "Il canale ha bisogno di un nome.")
        return redirect("discuss:home")
    tipo = Canale.PRIVATO if request.POST.get("tipo") == Canale.PRIVATO else Canale.PUBBLICO
    canale = servizi.crea_canale(nome, tipo, request.user, _utenti_scelti(request, "membri"),
                                 request.POST.get("descrizione", ""), gestito=bool(request.POST.get("gestito")),
                                 vocale=bool(request.POST.get("vocale")))
    return redirect("discuss:canale", pk=canale.pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def diretto(request):
    altri = list(_utenti_scelti(request).exclude(pk=request.user.pk))
    if not altri:
        messages.error(request, "Scegli almeno una persona.")
        return redirect("discuss:home")
    return redirect("discuss:canale", pk=servizi.diretto([request.user, *altri], request.POST.get("nome", "").strip()).pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def gruppo(request, pk):
    """Dal messaggio diretto a un gruppo con altre persone."""
    canale = _canale(request, pk)
    if not canale.diretto:
        raise PermissionDenied
    nuovi = list(_utenti_scelti(request))
    if not nuovi:
        messages.error(request, "Scegli almeno una persona.")
        return redirect("discuss:canale", pk=pk)
    return redirect("discuss:canale", pk=servizi.gruppo_da(canale, request.user, nuovi, request.POST.get("nome", "").strip()).pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def entra(request, pk):
    servizi.entra(_canale(request, pk), request.user)
    return redirect("discuss:canale", pk=pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def esci(request, pk):
    canale = _canale(request, pk)
    if canale.diretto:
        raise PermissionDenied
    servizi.esci(canale, request.user)
    messages.success(request, f"Sei uscito da {canale.titolo_per(request.user)}.")
    return redirect("discuss:home")


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def invita(request, pk):
    canale = _canale(request, pk)
    if canale.diretto or servizi.iscrizione(request.user, canale) is None:
        raise PermissionDenied
    for u in _utenti_scelti(request):
        servizi.entra(canale, u, da=request.user)
    return redirect("discuss:canale", pk=pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def preferenze(request, pk):
    canale = _canale(request, pk)
    valore = request.POST.get("notifiche", "")
    if valore in dict(Iscrizione.NOTIFICHE):
        Iscrizione.objects.filter(canale=canale, utente=request.user).update(notifiche=valore)
    return redirect("discuss:canale", pk=pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def preferito(request, pk):
    canale = _canale(request, pk)
    i = servizi.iscrizione(request.user, canale)
    if i is None:
        raise PermissionDenied
    Iscrizione.objects.filter(pk=i.pk).update(fissata=not i.fissata)
    return redirect("discuss:canale", pk=pk)


def _da_gestore(request, pk):
    canale = _canale(request, pk)
    if not servizi.puo_gestire(request.user, canale):
        raise PermissionDenied
    return canale


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def impostazioni(request, pk):
    canale = _da_gestore(request, pk)
    nome = request.POST.get("nome", "").strip()[:80]
    if nome:
        canale.nome = nome
    canale.descrizione = request.POST.get("descrizione", "").strip()[:250]
    canale.tipo = Canale.PRIVATO if request.POST.get("tipo") == Canale.PRIVATO else Canale.PUBBLICO
    canale.gestito = bool(request.POST.get("gestito"))
    canale.archiviato = bool(request.POST.get("archiviato"))
    canale.lista_email = bool(request.POST.get("lista_email"))
    canale.vocale = bool(request.POST.get("vocale"))
    canale.save(update_fields=["nome", "descrizione", "tipo", "gestito", "archiviato", "lista_email", "vocale"])
    return redirect("discuss:canale", pk=pk) if not canale.archiviato else redirect("discuss:home")


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def ruolo(request, pk):
    canale = _da_gestore(request, pk)
    valore = request.POST.get("ruolo", "")
    if valore in dict(Iscrizione.RUOLI) and request.POST.get("utente", "").isdigit():
        servizi.cambia_ruolo(canale, get_object_or_404(get_user_model(), pk=request.POST["utente"]), valore)
    return _rendi_info(request, canale)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def togli(request, pk):
    canale = _da_gestore(request, pk)
    if request.POST.get("utente", "").isdigit():
        servizi.esci(canale, get_object_or_404(get_user_model(), pk=request.POST["utente"]), da=request.user)
    return _rendi_info(request, canale)


@login_required
@permission_required(PERMESSO, raise_exception=True)
def posta(request):
    """Posta in arrivo: le notifiche, prima le non lette."""
    filtro = request.GET.get("filtro", "")
    voci = Notifica.objects.filter(utente=request.user)
    if filtro == "nonlette":
        voci = voci.filter(letta=False)
    elif filtro in FILTRI_POSTA:
        voci = voci.filter(tipo__in=FILTRI_POSTA[filtro])
    contesto = _contesto(request)
    contesto.update({"voci": voci.select_related("autore").order_by("letta", "-creata")[:200], "in_posta": True,
                     "filtro": filtro, "filtri": [("", "Tutte"), ("nonlette", "Non lette"), ("menzioni", "Menzioni e risposte"),
                                                  ("diretti", "Messaggi diretti"), ("record", "Record seguiti"), ("attivita", "Attività")]})
    return render(request, "discuss/posta.html", contesto)


@login_required
@permission_required(PERMESSO, raise_exception=True)
def apri_notifica(request, pk):
    notifica = get_object_or_404(Notifica, pk=pk, utente=request.user)
    if not notifica.letta:
        notifica.letta = True
        notifica.save(update_fields=["letta"])
    destinazione = notifica.url if notifica.url.startswith("/") and not notifica.url.startswith("//") else "/"
    return redirect(destinazione)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def tutte_lette(request):
    Notifica.objects.filter(utente=request.user, letta=False).update(letta=True)
    return redirect("discuss:posta")


@login_required
def contatore(request):
    """La campanella in testata: ogni 30 secondi, e tiene aggiornata la presenza su qualsiasi pagina."""
    if not request.user.has_perm(PERMESSO):
        return HttpResponse("")
    presenze.tocca(request.user, attivo=request.GET.get("attivo", "1") == "1")
    return render(request, "discuss/_campanella_voce.html")


@login_required
def presenze_di(request):
    """Lo stato di chi compare nel chatter dei record: {pk: stato}. Solo per chi usa le Comunicazioni."""
    if not request.user.has_perm(PERMESSO):
        return JsonResponse({"stati": {}})
    scelti = [p for p in request.GET.get("id", "").split(",") if p.isdigit()][:100]
    stati = presenze.di(scelti)
    return JsonResponse({"stati": {p: {"stato": (c := presenze.scheda(stati.get(int(p))))["stato"], "etichetta": c["etichetta"]} for p in scelti}})


# --- schede dei record ---

@login_required
@permission_required(PERMESSO, raise_exception=True)
def scheda(request, ct, pk):
    return render(request, "discuss/_scheda.html", {"s": schede.scheda(request, ct, pk)})


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def scheda_nota(request, ct, pk):
    """Una nota sul record, scritta dalla conversazione."""
    _, obj = vista_e_oggetto(request, ct, pk, "view")
    corpo = request.POST.get("corpo", "").strip()
    if corpo:
        chatter.scrivi(obj, request.user, corpo, MessaggioChatter.NOTA)
    return render(request, "discuss/_scheda.html", {"s": schede.scheda(request, ct, pk), "avviso": "Nota aggiunta al record." if corpo else ""})


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def scheda_segui(request, ct, pk):
    _, obj = vista_e_oggetto(request, ct, pk, "view")
    (chatter.smetti if chatter.segue(obj, request.user) else chatter.segui)(obj, request.user)
    return render(request, "discuss/_scheda.html", {"s": schede.scheda(request, ct, pk)})


@login_required
@permission_required("discuss.add_messaggio", raise_exception=True)
def condividi(request, ct, pk):
    """«Condividi» da qualsiasi record: a persone e canali, con un messaggio."""
    vista, obj = vista_e_oggetto(request, ct, pk, "view")
    torna = vista.url("dettaglio", pk=obj.pk)
    if request.method != "POST":
        canali = [i.canale for i in servizi.iscrizioni_di(request.user) if not i.canale.diretto]
        return render(request, "discuss/_condividi.html", {
            "obj": obj, "ct": ct, "persone": _colleghi(request),
            "canali": [c for c in canali if servizi.puo_scrivere(request.user, c)]})
    persone = list(_utenti_scelti(request, "persone").exclude(pk=request.user.pk))
    canali = [c for c in Canale.objects.filter(pk__in=[p for p in request.POST.getlist("canali") if p.isdigit()])
              if servizi.puo_scrivere(request.user, c)]
    if not persone and not canali:
        messages.error(request, "Scegli almeno una persona o un canale.")
        return redirect(torna)
    senza_accesso = schede.condividi(obj, request.user, request.POST.get("messaggio", ""), persone, canali)
    messages.success(request, f"«{obj}» condiviso.")
    if senza_accesso:
        messages.warning(request, "Non hanno accesso a questo record e vedranno la scheda senza i dati: " + ", ".join(senza_accesso))
    return redirect(torna)


@login_required
@permission_required("discuss.add_canale", raise_exception=True)
@require_POST
def canale_record(request, ct, pk):
    """La conversazione dedicata a un record: una sola, con chi lo segue. Chi può vedere il record può entrarci."""
    _, obj = vista_e_oggetto(request, ct, pk, "view")
    return redirect("discuss:canale", pk=schede.canale_del_record(obj, request.user).pk)


# --- dal messaggio al lavoro ---

def _messaggio_iscritto(request, pk):
    messaggio = _messaggio_visibile(request, pk)
    if messaggio.eliminato or messaggio.tipo != Messaggio.NORMALE:
        raise Http404
    return messaggio


@login_required
@permission_required(PERMESSO, raise_exception=True)
def da_messaggio(request, pk):
    """Trasforma un messaggio in un'attività sul record collegato o in un record nuovo."""
    messaggio = _messaggio_iscritto(request, pk)
    return render(request, "discuss/_da_messaggio.html", {
        "m": messaggio, "record": schede.record_di(request, messaggio), "tipi": TipoAttivita.objects.all(),
        "persone": get_user_model().objects.filter(is_active=True).order_by("first_name", "username"),
        "creabili": schede.creabili(request), "oggi": timezone.localdate(), "riepilogo": testo.piano(messaggio.corpo)[:200]})


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def attivita_da(request, pk):
    messaggio = _messaggio_iscritto(request, pk)
    voce = request.POST.get("record", "")
    ct, _, oggetto = voce.partition(":")
    if not (ct.isdigit() and oggetto.isdigit()):
        return HttpResponse("Scegli un record.", status=422)
    vista, obj = vista_e_oggetto(request, int(ct), int(oggetto), "view")
    assegnatario = get_object_or_404(get_user_model(), pk=request.POST.get("assegnatario", "0") if request.POST.get("assegnatario", "").isdigit() else 0, is_active=True)
    tipo = get_object_or_404(TipoAttivita, pk=request.POST.get("tipo", "0") if request.POST.get("tipo", "").isdigit() else 0)
    try:
        scadenza = datetime.date.fromisoformat(request.POST.get("scadenza", ""))
    except ValueError:
        scadenza = None
    att = attivita.pianifica(obj, tipo, assegnatario, scadenza, request.POST.get("riepilogo", "").strip()[:200],
                             messaggio.corpo, creato_da=request.user)
    servizi.avviso(messaggio.canale, request.user, f"{servizi.nome_di(request.user)} ha creato un'attività su «{obj}» per {servizi.nome_di(assegnatario)}, entro il {att.scadenza:%d/%m/%Y}")
    return HttpResponse(status=204, headers={"HX-Trigger": "ds-nuovi"})


@login_required
@permission_required(PERMESSO, raise_exception=True)
def crea_da(request, pk):
    """Apre il modulo del record nuovo già compilato; quando è salvato si lega al messaggio (vedi schede.lega_creato)."""
    messaggio = _messaggio_iscritto(request, pk)
    vista = schede.vista_creabile(request, request.GET.get("vista", ""))
    if vista is None:
        raise Http404
    request.session[schede.CHIAVE_SESSIONE] = {"ct": ct_di(vista.model).pk, "m": messaggio.pk,
                                               "dopo": vista.model._default_manager.order_by("-pk").values_list("pk", flat=True).first() or 0,
                                               "quando": timezone.now().timestamp()}
    return redirect(vista.url("nuovo") + "?" + urlencode(schede.iniziali(vista, request, messaggio)))
