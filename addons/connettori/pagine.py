"""«I miei account esterni»: ogni utente collega il suo account dei sistemi con «ogni utente con la sua chiave»
(Odoo). La chiave si verifica subito chiedendo al sistema chi è l'utente, si salva cifrata e non si rilegge più;
da quel momento in adabox arriva, e lui vede, solo ciò che quel sistema mostra a lui."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import cifratura, lavori

from . import sistemi
from .models import AccountEsterno, CollegamentoEsterno
from .sistemi.base import ErroreConnettore


def _collegamenti(request):
    azienda = getattr(request, "azienda", None)
    if azienda is None:
        return CollegamentoEsterno.objects.none()
    return CollegamentoEsterno.objects.filter(azienda=azienda, attivo=True, per_utente=True)


@login_required
def account(request):
    voci = []
    for c in _collegamenti(request):
        voci.append({"collegamento": c, "account": AccountEsterno.objects.filter(collegamento=c, utente=request.user).first()})
    return render(request, "connettori/account.html", {"voci": voci})


@login_required
@require_POST
def collega(request, pk):
    collegamento = get_object_or_404(_collegamenti(request), pk=pk)
    chiave = request.POST.get("chiave", "").strip()
    if not chiave:
        messages.error(request, "Incolla la chiave API del tuo account.")
        return redirect("connettori:account")
    prova = AccountEsterno(collegamento=collegamento, utente=request.user, chiave_cifrata=cifratura.cifra(chiave))
    try:
        uid = sistemi.client(collegamento, prova).utente()
    except ErroreConnettore as e:
        messages.error(request, f"La chiave non funziona: {e}")
        return redirect("connettori:account")
    altro = AccountEsterno.objects.filter(collegamento=collegamento, id_utente_esterno=uid).exclude(utente=request.user).select_related("utente").first()
    if uid and altro is not None:
        messages.error(request, f"Questo account di {collegamento.get_sistema_display()} è già collegato da {altro.utente}.")
        return redirect("connettori:account")
    with transaction.atomic():
        voce, nuovo = AccountEsterno.objects.update_or_create(collegamento=collegamento, utente=request.user, defaults={
            "chiave_cifrata": prova.chiave_cifrata, "id_utente_esterno": uid, "in_errore": False, "ultimo_esito": ""})
        if not nuovo:                                      # un account diverso vede altro: si rilegge da capo
            AccountEsterno.objects.filter(pk=voce.pk).update(cursori={})
    transaction.on_commit(lambda: lavori.accoda("connettori.sincronia.giro_account", account_id=voce.pk, azienda=collegamento.azienda,
                                                utente=request.user, max_tentativi=3))
    messages.success(request, f"Account di {collegamento.get_sistema_display()} collegato: i tuoi dati arrivano tra poco.")
    return redirect("connettori:account")


@login_required
@require_POST
def sincronizza(request, pk):
    voce = get_object_or_404(AccountEsterno, pk=pk, utente=request.user, collegamento__in=_collegamenti(request))
    lavori.accoda("connettori.sincronia.giro_account", account_id=voce.pk, azienda=voce.collegamento.azienda, utente=request.user, max_tentativi=1)
    messages.success(request, "Sincronizzazione avviata: l'esito compare qui sotto.")
    return redirect("connettori:account")


@login_required
@require_POST
def scollega(request, pk):
    """Si dimentica la chiave e la visibilità: i record arrivati restano, ma non li vedi più (a meno di altri permessi)."""
    voce = get_object_or_404(AccountEsterno, pk=pk, utente=request.user)
    sistema = voce.collegamento.get_sistema_display()
    voce.delete()
    messages.success(request, f"Account di {sistema} scollegato. Per togliere del tutto l'accesso, revoca anche la chiave in {sistema}.")
    return redirect("connettori:account")
