"""Le pagine pubbliche della prenotazione: scelta del giorno e dell'orario, dati, conferma; annullamento dal link."""
import datetime

from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from . import prenotazioni
from .models import Prenotazione, TipoAppuntamento


def _data(testo):
    try:
        return datetime.date.fromisoformat(testo) if testo else None
    except ValueError:
        return None


def prenota(request, codice):
    tipo = TipoAppuntamento.objects.filter(codice=codice, attivo=True).select_related("azienda").first()
    if tipo is None:
        raise Http404
    errore = ""
    if request.method == "POST" and not request.POST.get("sito"):          # «sito» è il campo trappola per i robot
        try:
            inizio = datetime.datetime.fromisoformat(request.POST.get("inizio", ""))
            inizio = inizio if timezone.is_aware(inizio) else timezone.make_aware(inizio)
        except ValueError:
            errore = "Scegli un orario."
        else:
            try:
                p = prenotazioni.prenota(tipo, inizio, request.POST.get("nome", ""), request.POST.get("email", ""),
                                         request.POST.get("telefono", ""), request.POST.get("societa", ""),
                                         request.POST.get("note", ""))
            except ValidationError as e:
                errore = " ".join(e.messages)
            else:
                return render(request, "calendario/prenotata.html", {"p": p, "tipo": tipo, "link": prenotazioni.link(p)})
    tutte = prenotazioni.fasce(tipo)
    giorni = sorted({timezone.localdate(i) for i, _ in tutte})
    scelto = _data(request.GET.get("giorno") or request.POST.get("giorno"))
    if scelto not in giorni:
        scelto = giorni[0] if giorni else None
    orari = [timezone.localtime(i) for i, _ in tutte if timezone.localdate(i) == scelto]
    return render(request, "calendario/prenota.html", {"tipo": tipo, "giorni": giorni, "scelto": scelto, "orari": orari,
                                                        "errore": errore, "dati": request.POST})


def prenotazione(request, token):
    p = prenotazioni.da_token(token)
    if p is None:
        return render(request, "calendario/prenotazione.html", {"invalido": True}, status=400)
    esito = ""
    passata = p.inizio <= timezone.now()
    if request.method == "POST" and request.POST.get("azione") == "annulla" and p.stato == Prenotazione.CONFERMATA and not passata:
        prenotazioni.annulla(p, da_cliente=True, motivo=request.POST.get("motivo", "").strip()[:500])
        esito = "L'appuntamento è annullato."
    return render(request, "calendario/prenotazione.html", {"p": p, "esito": esito, "passata": passata})
