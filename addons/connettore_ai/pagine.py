"""«Le mie chat AI»: l'indirizzo da incollare nella chat, i collegamenti attivi della persona e il bottone per
scollegarli. I collegamenti sono personali: qui ognuno vede e revoca solo i propri, di tutte le sue aziende."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import stato
from .models import ChatCollegata


@login_required
@permission_required(stato.PERMESSO, raise_exception=True)
def mie(request):
    collegabili = stato.aziende_collegabili(request.user)
    collegamenti = (ChatCollegata.objects.filter(utente=request.user, revocato__isnull=True, azienda__in=collegabili)
                    .select_related("client", "azienda").annotate(n_chiamate=Count("chiamate")))
    return render(request, "connettore_ai/mie.html", {
        "indirizzo": stato.risorsa(), "collegabili": collegabili, "collegamenti": collegamenti,
        "spento": stato.spento(), "in_chiaro": stato.base().startswith("http://")})


@login_required
@require_POST
def scollega(request, pk):
    collegamento = get_object_or_404(ChatCollegata, pk=pk, utente=request.user)
    collegamento.revoca(da=request.user)
    messages.success(request, f"{collegamento.get_fornitore_display()} scollegata: da adesso non legge più niente. "
                              "Per pulizia toglila anche dall'elenco dei connettori della chat.")
    return redirect("connettore_ai:mie")


@login_required
@permission_required("connettore_ai.add_clientoauth", raise_exception=True)
def credenziali(request):
    """Gemini Enterprise non si registra da sé: un amministratore crea qui identificativo e segreto e li copia nella
    console di Google. Il segreto si vede solo in questa risposta: qui ne resta l'impronta."""
    from django.urls import reverse

    from . import clienti
    contesto = {"indirizzo": stato.risorsa(), "ritorno": clienti.A_MANO["gemini"][1], "ambiti": f"{stato.AMBITO} offline_access",
                "url_autorizza": stato.base() + reverse("connettore_ai:autorizza"),
                "url_token": stato.base() + reverse("connettore_ai:token")}
    if request.method == "POST":
        client, segreto = clienti.crea_a_mano("gemini")
        contesto.update(client=client, segreto=segreto)
    return render(request, "connettore_ai/credenziali.html", contesto)
