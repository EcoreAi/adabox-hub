"""Lettura dei codici a barre nel magazzino: dal telefono o con un lettore (che scrive il codice e preme Invio), si
leggono i pezzi di un ricevimento o di una consegna in bozza, o quelli da spostare; alla conferma le quantità lette
diventano quelle del documento. Il codice di una confezione vale tutti i suoi pezzi."""
import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.dashboard import queryset
from prodotti.models import Prodotto, da_codice

from . import operazioni
from .models import Consegna, Ricevimento, RigaConsegna, RigaRicevimento

TIPI = {"ricevimento": (Ricevimento, RigaRicevimento, "ricevimento"), "consegna": (Consegna, RigaConsegna, "consegna")}


@login_required
@permission_required("magazzino.view_movimento", raise_exception=True)
def inizio(request):
    """I documenti aperti da leggere e lo spostamento di merce."""
    return render(request, "magazzino/lettura.html", {
        "ricevimenti": queryset(request, Ricevimento).filter(stato=Ricevimento.BOZZA).select_related("fornitore").order_by("data", "pk")[:50]
        if request.user.has_perm("magazzino.change_ricevimento") else [],
        "consegne": queryset(request, Consegna).filter(stato=Consegna.BOZZA).select_related("cliente").order_by("data", "pk")[:50]
        if request.user.has_perm("magazzino.change_consegna") else [],
        "trasferire": request.user.has_perm("magazzino.add_movimento")})


@login_required
@permission_required("magazzino.view_movimento", raise_exception=True)
def codice(request):
    """Il prodotto di un codice letto: {id, nome, pezzi} oppure 404 con il motivo."""
    trovato = da_codice(request.azienda, request.GET.get("c", ""))
    if trovato is None or trovato[0].tipo != Prodotto.BENE:
        return JsonResponse({"errore": f"Nessun prodotto con il codice «{request.GET.get('c', '')[:40]}»."}, status=404)
    prodotto, pezzi = trovato
    return JsonResponse({"id": prodotto.pk, "nome": str(prodotto), "pezzi": float(pezzi)})


def _letture(request):
    """{prodotto_id: quantità} dal POST (JSON), solo prodotti dell'azienda e quantità non negative."""
    try:
        grezze = json.loads(request.POST.get("letture") or "{}")
        valori = {int(k): Decimal(str(v)) for k, v in grezze.items()}
    except (ValueError, TypeError, InvalidOperation, AttributeError):
        raise ValidationError("Letture illeggibili: ricarica la pagina e riprova.")
    if any(v < 0 for v in valori.values()):
        raise ValidationError("Una quantità letta non può essere negativa.")
    validi = set(queryset(request, Prodotto).filter(pk__in=valori, tipo=Prodotto.BENE).values_list("pk", flat=True))
    return {k: v for k, v in valori.items() if k in validi and v}


@transaction.atomic
def applica(documento, letture, togli_non_letti=False):
    """Le quantità lette diventano quelle delle righe. Nel ricevimento un prodotto in più diventa una riga nuova; nella
    consegna no (non si spedisce ciò che non è stato chiesto). Restituisce le differenze in parole."""
    ricevimento = isinstance(documento, Ricevimento)
    righe = list(documento.righe.select_related("prodotto").order_by("pk"))
    restano, differenze = dict(letture), []
    per_prodotto = {}
    for r in righe:
        per_prodotto.setdefault(r.prodotto_id, []).append(r)
    for prodotto_id, gruppo in per_prodotto.items():
        letto = restano.pop(prodotto_id, Decimal(0))
        atteso = sum((Decimal(r.quantita) for r in gruppo), Decimal(0))
        if letto == atteso:
            continue
        if not letto and not togli_non_letti:
            differenze.append(f"{gruppo[0].prodotto}: non letto, resta {atteso:g}")
            continue
        differenze.append(f"{gruppo[0].prodotto}: {atteso:g} attesi, {letto:g} letti")
        for r in gruppo[1:]:                                  # più righe dello stesso prodotto: la quantità va sulla prima
            r.delete()
        if letto:
            gruppo[0].quantita = letto
            gruppo[0].save(update_fields=["quantita"])
        else:
            gruppo[0].delete()
    if restano:
        prodotti = {p.pk: p for p in Prodotto.objects.filter(pk__in=restano)}
        if not ricevimento:
            raise ValidationError("Nella consegna non ci sono: " + ", ".join(str(prodotti[k]) for k in restano) + ". Toglili o aggiungili alla consegna.")
        for prodotto_id, q in restano.items():
            RigaRicevimento.objects.create(ricevimento=documento, prodotto=prodotti[prodotto_id], quantita=q)
            differenze.append(f"{prodotti[prodotto_id]}: {q:g} in più, aggiunto")
    return differenze


@login_required
def documento(request, tipo, pk):
    if tipo not in TIPI:
        raise PermissionDenied
    modello, _, nome = TIPI[tipo]
    if not request.user.has_perm(f"magazzino.change_{nome}"):
        raise PermissionDenied
    doc = get_object_or_404(queryset(request, modello), pk=pk)
    dettaglio = reverse(f"magazzino:{'ricevimenti' if tipo == 'ricevimento' else 'consegne'}_dettaglio", args=[doc.pk])
    if doc.stato != modello.BOZZA:
        messages.warning(request, "Il documento non è più in bozza.")
        return redirect(dettaglio)
    if request.method == "POST":
        try:
            differenze = applica(doc, _letture(request), request.POST.get("togli") == "1")
            if request.POST.get("chiudi") == "1":
                if tipo == "ricevimento":
                    operazioni.ricevi(doc, request.user)
                else:
                    operazioni.spedisci(doc, request.user)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            return redirect(request.path)
        testo = "Quantità aggiornate" + (": " + "; ".join(differenze) if differenze else ": tutto come atteso") + "."
        if request.POST.get("chiudi") == "1":
            testo += " Merce ricevuta." if tipo == "ricevimento" else f" Consegna spedita con il DDT {doc.numero}."
        messages.success(request, testo)
        return redirect(dettaglio)
    righe = {}
    for r in doc.righe.select_related("prodotto"):
        x = righe.setdefault(r.prodotto_id, {"id": r.prodotto_id, "nome": str(r.prodotto), "attesi": 0.0})
        x["attesi"] += float(r.quantita)
    return render(request, "magazzino/lettura_documento.html", {
        "doc": doc, "tipo": tipo, "righe": list(righe.values()), "dettaglio": dettaglio,
        "titolo": f"Ricevimento da {doc.fornitore}" if tipo == "ricevimento" else f"Consegna a {doc.cliente}"})


@login_required
@permission_required("magazzino.add_movimento", raise_exception=True)
def trasferimento(request):
    """Leggi i pezzi da spostare, poi scegli da dove a dove."""
    from .pagine import _posti, _posto
    if request.method == "POST":
        da_m, da_u = _posto(request, request.POST.get("da", ""))
        a_m, a_u = _posto(request, request.POST.get("a", ""))
        try:
            letture = _letture(request)
            if da_m is None or a_m is None:
                raise ValidationError("Scegli da dove e verso dove.")
            if not letture:
                raise ValidationError("Non hai letto nessun pezzo.")
            with transaction.atomic():
                for p in Prodotto.objects.filter(pk__in=letture):
                    operazioni.trasferisci(p, letture[p.pk], da_m, a_m, da_u, a_u, request.user, "Lettura codici")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            return redirect(request.path)
        messages.success(request, f"Spostati {len(letture)} prodotti.")
        return redirect("magazzino:lettura")
    return render(request, "magazzino/lettura_documento.html", {"tipo": "trasferimento", "righe": [], "posti": _posti(request),
                                                                "titolo": "Sposta merce", "dettaglio": reverse("magazzino:lettura")})
