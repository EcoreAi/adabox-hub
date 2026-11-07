"""Il preventivo online: la pagina pubblica dal link nell'email, senza accesso."""
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_ipv46_address
from django.shortcuts import render

from . import operazioni


def _ip(request):
    """L'ultimo X-Forwarded-For è quello scritto dal nostro nginx: i precedenti li può inventare il client."""
    inoltrato = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[-1].strip()
    ip = inoltrato or request.META.get("REMOTE_ADDR", "")
    try:
        validate_ipv46_address(ip)
    except ValidationError:
        return None
    return ip


def preventivo_online(request, token):
    ordine, stato = operazioni.da_token(token)
    if ordine is None:
        return render(request, "vendite/online.html", {"stato": stato}, status=400)
    contesto = {"ordine": ordine, "stato": stato, "righe": ordine.righe.select_related("aliquota"),
                "iva": ordine.riepilogo_iva()}
    if request.method == "POST" and stato == "valido":
        azione = request.POST.get("azione")
        try:
            if azione == "accetta":
                nome = request.POST.get("nome", "").strip()[:120]
                if len(nome) < 2 or request.POST.get("conferma") != "1":
                    contesto.update(errore="Scrivi il tuo nome e spunta la conferma.", nome=nome)
                    return render(request, "vendite/online.html", contesto, status=400)
                contesto.update(ordine=operazioni.accetta(ordine, nome, _ip(request)), stato="risposto", appena=True)
            elif azione == "rifiuta":
                motivo = request.POST.get("motivo", "").strip()[:1000]
                contesto.update(ordine=operazioni.rifiuta(ordine, motivo, _ip(request)), stato="risposto", appena=True)
        except ValidationError:
            contesto.update(ordine=type(ordine).objects.get(pk=ordine.pk), stato="chiuso")
    return render(request, "vendite/online.html", contesto)


@login_required
@permission_required("vendite.add_ordinevendita", raise_exception=True)
def da_opportunita(request, pk):
    """«Crea preventivo» dalla scheda dell'opportunità."""
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.shortcuts import get_object_or_404, redirect

    from core.dashboard import queryset
    from crm.models import Opportunita

    from . import opportunita
    opp = get_object_or_404(queryset(request, Opportunita), pk=pk)
    if request.method != "POST":
        return redirect("crm:opportunita_dettaglio", opp.pk)
    try:
        ordine = opportunita.crea_preventivo(opp, request.user)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("crm:opportunita_dettaglio", opp.pk)
    messages.success(request, "Preventivo creato dall'opportunità: aggiungi le righe.")
    return redirect("vendite:ordini_modifica", ordine.pk)
