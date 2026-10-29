"""Esecuzione di un collaudo: un caso alla volta con esito e note; da un caso fallito si apre il difetto."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import chatter
from progetti.models import Compito, TipoCompito, progetti_visibili

from .models import Collaudo, Esecuzione


def _collaudo(request, pk):
    if not request.user.has_perm("qualita.view_collaudo"):
        raise PermissionDenied
    return get_object_or_404(Collaudo.objects.filter(progetto__in=progetti_visibili(request.user).values("pk"))
                             .select_related("progetto", "rilascio", "ambiente"), pk=pk)


@login_required
def esegui(request, pk):
    collaudo = _collaudo(request, pk)
    if request.method == "POST":
        if not request.user.has_perm("qualita.change_esecuzione") or collaudo.stato == Collaudo.CONCLUSO:
            raise PermissionDenied
        e = get_object_or_404(collaudo.esecuzioni, pk=request.POST.get("esecuzione"))
        esito = request.POST.get("esito")
        if esito not in dict(Esecuzione.ESITI):
            messages.error(request, "Esito non valido.")
        else:
            e.esito, e.note = esito, request.POST.get("note", "").strip()[:5000]
            e.eseguito_da, e.eseguito_il = (None, None) if esito == Esecuzione.DA_FARE else (request.user, timezone.now())
            e.save()
        return redirect(f"{request.path}#e{e.pk}")
    esecuzioni = collaudo.esecuzioni.select_related("caso", "eseguito_da", "difetto", "difetto__fase")
    return render(request, "qualita/esegui.html", {"collaudo": collaudo, "esecuzioni": esecuzioni,
                                                   "esiti": Esecuzione.ESITI, "r": collaudo.riepilogo(),
                                                   "modificabile": collaudo.stato == Collaudo.APERTO and
                                                   request.user.has_perm("qualita.change_esecuzione")})


def apri_difetto(esecuzione, utente):
    """Compito di tipo difetto nel progetto (e nel rilascio) del collaudo, con passi, atteso e note."""
    if esecuzione.difetto_id:
        return esecuzione.difetto
    collaudo, caso = esecuzione.collaudo, esecuzione.caso
    passi = "\n".join(f"{i}. {p}" for i, p in enumerate(caso.elenco_passi(), 1))
    descrizione = "\n\n".join(t for t in (
        f"Trovato dal collaudo «{collaudo}»" + (f" su {collaudo.ambiente}" if collaudo.ambiente_id else "") + ".",
        f"Precondizioni:\n{caso.precondizioni}" if caso.precondizioni else "",
        f"Passi:\n{passi}", f"Risultato atteso:\n{caso.atteso}",
        f"Risultato ottenuto:\n{esecuzione.note}" if esecuzione.note else "") if t)
    compito = Compito.objects.create(
        azienda=collaudo.azienda, progetto=collaudo.progetto, titolo=f"Collaudo: {caso.titolo}"[:200],
        descrizione=descrizione, tipo=TipoCompito.objects.filter(difetto=True).first(), rilascio=collaudo.rilascio,
        priorita=Compito.ALTA if caso.priorita == caso.ALTA else Compito.NORMALE)
    esecuzione.difetto = compito
    esecuzione.save(update_fields=["difetto"])
    chatter.scrivi(compito, utente, f"Difetto aperto dal collaudo «{collaudo}».", tipo="nota")
    return compito


@login_required
@require_POST
def difetto(request, pk, esecuzione):
    collaudo = _collaudo(request, pk)
    if not request.user.has_perm("progetti.add_compito"):
        raise PermissionDenied
    e = get_object_or_404(collaudo.esecuzioni.select_related("caso"), pk=esecuzione)
    if e.esito not in (Esecuzione.FALLITO, Esecuzione.BLOCCATO):
        messages.error(request, "Il difetto si apre da un caso fallito o bloccato.")
        return redirect("qualita:esegui", pk=pk)
    compito = apri_difetto(e, request.user)
    messages.success(request, f"Difetto «{compito}» aperto.")
    return redirect(f"{redirect('qualita:esegui', pk=pk).url}#e{e.pk}")
