"""Importare un estratto e abbinare i movimenti."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.dashboard import queryset

from . import abbina as motore, estratti
from .models import Abbinamento, Conto, MovimentoBanca

PER_PAGINA = 40
PERMESSO_ABBINA = "banca.add_abbinamento"


def _movimento(request, pk):
    return get_object_or_404(queryset(request, MovimentoBanca), pk=pk)


def _ritorno(request, ripiego="banca:riconcilia"):
    url = request.POST.get("ritorno", "")
    return redirect(url) if url and url_has_allowed_host_and_scheme(url, {request.get_host()}) else redirect(ripiego)


@login_required
@permission_required("banca.view_movimentobanca", raise_exception=True)
def riconcilia(request):
    conti = queryset(request, Conto).filter(attivo=True)
    conto = conti.filter(pk=request.GET["conto"]).first() if request.GET.get("conto", "").isdigit() else None
    tutti = queryset(request, MovimentoBanca).filter(stato__in=(MovimentoBanca.DA_ABBINARE, MovimentoBanca.PARZIALE)).select_related("conto")
    if conto:
        tutti = tutti.filter(conto=conto)
    attive, passive = motore.aperte_attive(request.azienda), motore.aperte_passive(request.azienda)
    schede, sicuri = [], 0
    for m in tutti.order_by("-data", "-pk")[:PER_PAGINA]:
        lista = motore.proposte(m, attive, passive)
        sicura = m.stato == MovimentoBanca.DA_ABBINARE and motore.e_sicura(lista)
        sicuri += sicura
        schede.append({"m": m, "proposte": lista, "sicura": sicura})
    return render(request, "banca/riconcilia.html", {
        "schede": schede, "conti": conti, "conto": conto, "totale": tutti.count(), "sicuri": sicuri,
        "entrate": tutti.filter(importo__gt=0).aggregate(t=Sum("importo"))["t"] or 0, "uscite": tutti.filter(importo__lt=0).aggregate(t=Sum("importo"))["t"] or 0,
        "puo_abbinare": request.user.has_perm(PERMESSO_ABBINA)})


@login_required
@permission_required("banca.add_importazione", raise_exception=True)
def importa(request):
    conti = queryset(request, Conto).filter(attivo=True)
    if request.method == "POST":
        conto = conti.filter(pk=request.POST.get("conto")).first() if str(request.POST.get("conto", "")).isdigit() else None
        file = request.FILES.get("file")
        if conto is None or file is None:
            messages.error(request, "Scegli il conto e il file dell'estratto.")
            return redirect("banca:importa")
        if file.size > estratti.MASSIMO_BYTE:
            messages.error(request, "Il file è troppo grande: il massimo è 10 MB.")
            return redirect("banca:importa")
        try:
            esito = motore.importa(conto, file.read(), file.name, request.user)
        except estratti.EstrattoNonValido as e:
            messages.error(request, str(e))
            return redirect("banca:importa")
        testo = f"Movimenti nuovi: {esito.nuovi}."
        if esito.doppi:
            testo += f" Già presenti, non ripetuti: {esito.doppi}."
        messages.success(request, testo)
        if esito.scartati:
            messages.warning(request, f"Righe non lette: {esito.scartati}. Controllale nel file: quei movimenti non sono stati importati.")
        return redirect(f"{_url_riconcilia()}?conto={conto.pk}")
    return render(request, "banca/importa.html", {"conti": conti})


def _url_riconcilia():
    from django.urls import reverse
    return reverse("banca:riconcilia")


@login_required
@permission_required(PERMESSO_ABBINA, raise_exception=True)
def scegli(request, pk):
    """Quando il suggerimento non c'è: si cerca a mano la fattura, e si possono scegliere più scadenze per un unico bonifico."""
    m = _movimento(request, pk)
    testo = request.GET.get("q", "").strip()
    if m.importo > 0:
        tutte = motore.aperte_attive(request.azienda)
        filtro = lambda s: testo.lower() in f"{s.fattura.numero} {s.fattura.cliente.nome}".lower()      # noqa: E731
    else:
        tutte = motore.aperte_passive(request.azienda)
        filtro = lambda s: testo.lower() in f"{s.fattura.numero} {s.fattura.fornitore.nome}".lower()    # noqa: E731
    scelte = [motore._valuta(m, s, m.importo < 0) for s in tutte if not testo or filtro(s)]
    scelte.sort(key=lambda p: -p.punti)
    return render(request, "banca/scegli.html", {"m": m, "scelte": scelte[:100], "q": testo, "altre": max(len(scelte) - 100, 0)})


@login_required
@permission_required(PERMESSO_ABBINA, raise_exception=True)
@require_POST
def abbina(request, pk):
    m = _movimento(request, pk)
    try:
        fatti = motore.abbina(m, request.POST.getlist("scadenza"), request.user)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    else:
        messages.success(request, f"Abbinato: {sum((a.importo for a in fatti), 0)} € su {len(fatti)} scadenz{'a' if len(fatti) == 1 else 'e'}.")
    return _ritorno(request)


@login_required
@permission_required(PERMESSO_ABBINA, raise_exception=True)
@require_POST
def abbina_sicuri(request):
    conto = queryset(request, Conto).filter(pk=request.POST.get("conto")).first() if str(request.POST.get("conto", "")).isdigit() else None
    fatti = motore.abbina_i_sicuri(request.azienda, request.user, conto)
    messages.success(request, f"Movimenti abbinati: {fatti}.")
    return _ritorno(request)


@login_required
@permission_required(PERMESSO_ABBINA, raise_exception=True)
@require_POST
def ignora(request, pk):
    try:
        motore.ignora(_movimento(request, pk))
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    return _ritorno(request)


@login_required
@permission_required(PERMESSO_ABBINA, raise_exception=True)
@require_POST
def ripristina(request, pk):
    motore.ripristina(_movimento(request, pk))
    return _ritorno(request)


@login_required
@permission_required(PERMESSO_ABBINA, raise_exception=True)
@require_POST
def annulla(request, pk):
    abbinamento = get_object_or_404(Abbinamento.objects.filter(Q(movimento__in=queryset(request, MovimentoBanca))), pk=pk)
    motore.annulla(abbinamento)
    messages.success(request, "Abbinamento tolto: l'incasso non c'è più e la scadenza è di nuovo aperta.")
    return _ritorno(request, "banca:movimenti_lista")
