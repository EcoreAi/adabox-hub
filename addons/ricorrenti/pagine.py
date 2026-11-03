"""Il cruscotto dei ricavi ricorrenti e l'adeguamento ISTAT di più contratti insieme."""
import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone

from core.dashboard import queryset
from fatturazione.dashboard import MESI

from . import operazioni
from .models import Canone, piu_mesi


@login_required
@permission_required("ricorrenti.view_canone", raise_exception=True)
def cruscotto(request):
    oggi = timezone.localdate()
    tutti = queryset(request, Canone).select_related("cliente")
    attivi = list(operazioni.attivi(tutti))
    mensile = sum((c.mensile for c in attivi), Decimal(0))
    colonne = operazioni.previsione(attivi, 12, oggi)
    massimo = max((v for _, v in colonne), default=0) or 1
    clienti = {}
    for c in attivi:
        clienti[c.cliente] = clienti.get(c.cliente, Decimal(0)) + c.mensile
    entro = oggi + datetime.timedelta(days=90)
    return render(request, "ricorrenti/cruscotto.html", {
        "mensile": mensile, "annuale": mensile * 12, "numero": len(attivi),
        "da_attivare": tutti.filter(stato=Canone.BOZZA).count(),
        "previsione": [{"mese": f"{MESI[m.month - 1]} {m.year}", "importo": v, "quota": int(v * 100 / massimo)} for m, v in colonne],
        "totale_previsto": sum((v for _, v in colonne), Decimal(0)),
        "clienti": [{"cliente": k, "mensile": v, "quota": int(v * 100 / mensile) if mensile else 0} for k, v in
                    sorted(clienti.items(), key=lambda x: -x[1])[:10]],
        "in_scadenza": sorted((c for c in attivi if (c.cessa_il or c.scadenza) and (c.cessa_il or c.scadenza) <= entro),
                              key=lambda c: c.cessa_il or c.scadenza),
    })


@login_required
@permission_required("ricorrenti.change_canone", raise_exception=True)
def adeguamento(request):
    canoni = list(operazioni.attivi(queryset(request, Canone).filter(adeguamento_istat=True)).select_related("cliente"))
    un_anno_fa = piu_mesi(timezone.localdate(), -12)
    if request.method == "POST":
        try:
            percentuale = Decimal(request.POST.get("percentuale", "").replace(",", "."))
            if not percentuale.is_finite():
                raise InvalidOperation
        except InvalidOperation:
            messages.error(request, "Indica la percentuale, per esempio 1,5.")
            return redirect("ricorrenti:adeguamento")
        scelti = {p for p in request.POST.getlist("canone")}
        fatti, errori = 0, []
        for c in canoni:
            if str(c.pk) in scelti:
                try:
                    operazioni.adegua(c, percentuale, utente=request.user)
                    fatti += 1
                except ValidationError as e:
                    errori.append(" ".join(e.messages))
        for e in errori:
            messages.error(request, e)
        if fatti:
            messages.success(request, f"Contratti adeguati: {fatti}. Vale dalle prossime fatture.")
        elif not errori:
            messages.warning(request, "Non hai scelto nessun contratto.")
        return redirect("ricorrenti:adeguamento")
    voci = []
    for c in canoni:
        ultimo = operazioni.ultimo_adeguamento(c)
        voci.append({"canone": c, "ultimo": ultimo, "recente": bool(ultimo and ultimo.data > un_anno_fa)})
    return render(request, "ricorrenti/adeguamento.html", {"voci": voci})
