"""Prelievo e imballaggio di una consegna prima del DDT: lista ordinata per ubicazione (il giro nel magazzino), con
ubicazione e lotti suggeriti, quantità prelevata confermata e collo di ogni riga; stampa della lista e della distinta
colli. Alla conferma la consegna diventa pronta e i colli del DDT sono quelli usati."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from core.dashboard import queryset

from . import lotti, operazioni
from .models import Consegna, ubicazione_di_prelievo


def giro(consegna):
    """[{riga, parti: [{prodotto, quantita, ubicazione, lotti}], ordine}] con i kit esplosi, in ordine di ubicazione."""
    voci = []
    for r in consegna.righe.select_related("prodotto", "ubicazione").order_by("pk"):
        parti = []
        for p in operazioni.parti_da_scaricare([r]):
            ubicazione = p.ubicazione or ubicazione_di_prelievo(p.prodotto, consegna.magazzino)
            try:
                suggeriti = ", ".join(f"{l.codice}: {q:g}" for l, q in lotti.per_uscita(p, p.prodotto, consegna.magazzino) if l is not None)
            except ValidationError as e:
                suggeriti = " ".join(e.messages)
            parti.append({"prodotto": p.prodotto, "quantita": p.quantita, "ubicazione": ubicazione, "lotti": suggeriti, "kit": p.kit})
        chiave = min((x["ubicazione"].percorso if x["ubicazione"] else "~") for x in parti) if parti else "~"
        voci.append({"riga": r, "parti": parti, "ordine": chiave})
    return sorted(voci, key=lambda v: (v["ordine"], v["riga"].pk))


def _decimale(testo, massimo):
    try:
        valore = Decimal((testo or "").replace(",", ".").strip())
    except InvalidOperation:
        raise ValidationError("Scrivi le quantità con i numeri.")
    if valore < 0 or valore > massimo:
        raise ValidationError(f"Si prelevano fra 0 e {massimo:g} pezzi.")
    return valore


@login_required
@permission_required("magazzino.change_consegna", raise_exception=True)
def prelievo(request, pk):
    c = get_object_or_404(queryset(request, Consegna).select_related("cliente", "magazzino", "destinazione"), pk=pk)
    stampa = request.GET.get("stampa", "")
    if request.method == "POST":
        if c.stato not in Consegna.APERTI:
            messages.error(request, "La consegna non è più da preparare.")
            return redirect("magazzino:consegne_dettaglio", pk=c.pk)
        try:
            with transaction.atomic():
                prelevate = {}
                for r in c.righe.all():
                    r.prelevata = _decimale(request.POST.get(f"p_{r.pk}", str(r.quantita)), r.quantita)
                    collo = (request.POST.get(f"k_{r.pk}") or "").strip()
                    r.collo = int(collo) if collo.isdigit() and int(collo) > 0 else None
                    r.save(update_fields=["prelevata", "collo"])
                    prelevate[r.pk] = r.prelevata
                residuo = None
                if any(q < r.quantita for r in c.righe.all() for q in [prelevate[r.pk]]):
                    if request.POST.get("resto") == "dopo":
                        residuo = operazioni.dividi(c, prelevate)
                    else:
                        for r in c.righe.all():
                            if prelevate[r.pk] == 0:
                                r.delete()
                            elif prelevate[r.pk] < r.quantita:
                                r.quantita = prelevate[r.pk]
                                r.save(update_fields=["quantita"])
                colli = {r.collo for r in c.righe.all() if r.collo}
                if colli:
                    c.colli = len(colli)
                    c.save(update_fields=["colli"])
                if c.stato == Consegna.BOZZA:
                    operazioni.segna_pronta(c)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            return redirect("magazzino:prelievo", pk=c.pk)
        messages.success(request, "Merce prelevata: consegna pronta." + (f" Il resto è in {residuo}." if residuo else ""))
        return redirect("magazzino:consegne_dettaglio", pk=c.pk)
    voci = giro(c)
    colli = {}
    for r in c.righe.select_related("prodotto").order_by("collo", "pk"):
        colli.setdefault(r.collo, []).append(r)
    return render(request, "magazzino/prelievo_stampa.html" if stampa else "magazzino/prelievo.html", {
        "c": c, "voci": voci, "stampa": stampa, "colli": sorted(colli.items(), key=lambda x: (x[0] is None, x[0] or 0)),
        "aperta": c.stato in Consegna.APERTI})
