"""«Il mio profilo»: tutto ciò che riguarda il dipendente, visto da lui. Solo i suoi dati, anche senza permessi d'ufficio."""
import datetime

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import allegati

from . import contratti, saldi, turni
from .models import Dipendente, DocumentoDipendente, RichiestaModifica


def _me(request):
    return Dipendente.objects.filter(utente=request.user, attivo=True).select_related("azienda", "reparto", "responsabile").first()


@login_required
def profilo(request):
    io = _me(request)
    if io is None:
        return render(request, "personale/profilo.html", {"io": None})
    if request.method == "POST":
        r = RichiestaModifica(azienda=io.azienda, dipendente=io, email=request.POST.get("email", "").strip()[:254],
                              telefono=request.POST.get("telefono", "").strip()[:40], altro=request.POST.get("altro", "").strip()[:2000])
        try:
            r.full_clean(exclude=["azienda"])
        except Exception as e:                       # noqa: BLE001 (il messaggio va all'utente)
            messages.error(request, " ".join(getattr(e, "messages", [str(e)])))
        else:
            r.save()
            messages.success(request, "Richiesta inviata all'ufficio del personale.")
        return redirect("personale:profilo")
    oggi = timezone.localdate()
    contesto = {"io": io, "saldo": saldi.saldo(io, oggi.year), "anno": oggi.year, "contratto": contratti.in_vigore(io),
                "assenze": io.assenze.select_related("tipo")[:8], "documenti": io.documenti.all()[:24],
                "richieste": io.richieste_modifica.all()[:5], "turni": turni.miei(io)}
    if apps.is_installed("spese"):
        from spese.models import NotaSpese
        contesto["note_spese"] = NotaSpese.objects.filter(dipendente=io).order_by("-pk")[:5]
    if apps.is_installed("timesheet"):
        from django.db.models import Sum

        from timesheet.models import RigaOre
        inizio = oggi.replace(day=1)
        contesto["ore_mese"] = RigaOre.objects.filter(utente=request.user, data__gte=inizio, data__lte=oggi).aggregate(t=Sum("ore"))["t"] or 0
    return render(request, "personale/profilo.html", contesto)


@login_required
def documento(request, pk):
    """Il documento lo scarica il suo dipendente, o chi gestisce i documenti dell'azienda."""
    d = get_object_or_404(DocumentoDipendente.objects.select_related("dipendente"), pk=pk)
    mio = d.dipendente.utente_id == request.user.pk
    if not mio and not (request.user.has_perm("personale.view_documentodipendente") and getattr(request, "azienda", None)
                        and d.azienda_id == request.azienda.pk):
        raise Http404
    if mio and d.letto_il is None:
        DocumentoDipendente.objects.filter(pk=d.pk).update(letto_il=timezone.now())
    import mimetypes
    nome = d.file.name.rsplit("/", 1)[-1].split("-", 1)[-1]
    finto = type("File", (), {"mime": mimetypes.guess_type(nome)[0] or "application/octet-stream", "file": d.file, "nome": nome})()
    return allegati.risposta(finto)


@login_required
@permission_required("personale.change_richiestamodifica", raise_exception=True)
@require_POST
def decidi(request, pk):
    from core.dashboard import queryset
    r = get_object_or_404(queryset(request, RichiestaModifica).select_related("dipendente"), pk=pk, stato=RichiestaModifica.IN_ATTESA)
    if request.POST.get("esito") == "approva":
        campi = []
        if r.email:
            r.dipendente.email = r.email
            campi.append("email")
        if r.telefono:
            r.dipendente.telefono = r.telefono
            campi.append("telefono")
        if campi:
            r.dipendente.save(update_fields=campi)
        r.stato = RichiestaModifica.APPROVATA
        messages.success(request, "Richiesta approvata" + (": dati aggiornati." if campi else ". Aggiorna a mano ciò che è scritto in «altro»."))
    else:
        r.stato = RichiestaModifica.RIFIUTATA
        messages.success(request, "Richiesta rifiutata.")
    r.decisa_da, r.decisa_il = request.user, timezone.now()
    r.save(update_fields=["stato", "decisa_da", "decisa_il"])
    return redirect("personale:richieste_dettaglio", pk=r.pk)
