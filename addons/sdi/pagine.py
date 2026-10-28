"""Pagine dello SDI: invio di una fattura, XML, caricamento a mano dei file ricevuti."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.dashboard import queryset
from fatturazione.models import Fattura

from . import ricezione, servizi
from .models import FatturaPassiva, Trasmissione


def _alla_fattura(fattura):
    return redirect("fatturazione:fatture_dettaglio", pk=fattura.pk)


@login_required
@permission_required("sdi.add_trasmissione", raise_exception=True)
@require_POST
def invia(request, pk):
    fattura = get_object_or_404(queryset(request, Fattura), pk=pk)
    try:
        _, messaggio = servizi.invia(fattura, request.user)
    except ValidationError as e:
        for m in e.messages:
            messages.error(request, m)
    else:
        messages.success(request, messaggio)
    return _alla_fattura(fattura)


def _trasmissione(request, pk):
    azienda_id = getattr(getattr(request, "azienda", None), "pk", None)
    qs = Trasmissione.objects.all() if azienda_id is None else Trasmissione.objects.filter(azienda_id=azienda_id)
    return get_object_or_404(qs, pk=pk)


@login_required
@permission_required("sdi.view_trasmissione", raise_exception=True)
def xml(request, pk):
    t = _trasmissione(request, pk)
    with t.file.open("rb") as f:
        risposta = HttpResponse(f.read(), content_type="application/xml")
    risposta["Content-Disposition"] = f'attachment; filename="{t.nome_file}"'
    return risposta


@login_required
@permission_required("sdi.add_trasmissione", raise_exception=True)
@require_POST
def caricata(request, pk):
    t = _trasmissione(request, pk)
    if t.stato == Trasmissione.PRONTA:
        servizi.segna_caricata(t, request.user)
        messages.success(request, f"{t.nome_file} segnato come caricato: ora si attende la notifica dello SDI.")
    return _alla_fattura(t.fattura)


@login_required
@permission_required("sdi.add_notificasdi", raise_exception=True)
def carica(request):
    """Caricamento a mano di notifiche (e, con le fatture passive, di fatture dei fornitori), anche in zip."""
    esiti = []
    if request.method == "POST":
        for file in request.FILES.getlist("file")[:200]:
            esiti.extend(_appiattisci(ricezione.ricevi(file.name, file.read(), getattr(request, "azienda", None)),
                                      file.name))
        if not esiti:
            messages.warning(request, "Nessun file caricato.")
    return render(request, "sdi/carica.html", {"esiti": esiti})


def _appiattisci(risultato, nome):
    esito, oggetto = risultato
    if esito == "zip":
        return [r for i, sotto in enumerate(oggetto) for r in _appiattisci(sotto, f"{nome} [{i + 1}]")]
    return [{"esito": esito, "oggetto": oggetto, "nome": getattr(oggetto, "nome_file", None) or str(oggetto) or nome}]


@login_required
@permission_required("sdi.view_fatturapassiva", raise_exception=True)
def originale(request, pk):
    f = get_object_or_404(queryset(request, FatturaPassiva), pk=pk)
    with f.originale.open("rb") as file:
        tipo = "application/pkcs7-mime" if f.nome_file.lower().endswith(".p7m") else "application/xml"
        risposta = HttpResponse(file.read(), content_type=tipo)
    risposta["Content-Disposition"] = f'attachment; filename="{f.nome_file}"'
    return risposta


@login_required
@permission_required("sdi.view_fatturapassiva", raise_exception=True)
def registro_acquisti(request):
    """Registro IVA degli acquisti: le fatture registrate del periodo, per aliquota; note di credito in negativo."""
    import csv
    from decimal import Decimal

    from django.utils import timezone

    from fatturazione.registro import MESI, periodo
    anno, mese = periodo(request)
    fatture = (queryset(request, FatturaPassiva).filter(stato=FatturaPassiva.REGISTRATA, registrata_il__year=anno)
               .select_related("fornitore").prefetch_related("riepilogo").order_by("registrata_il", "pk"))
    if mese:
        fatture = fatture.filter(registrata_il__month=mese)
    righe, riepilogo = [], {}
    for f in fatture:
        segno = Decimal(-1) if f.nota_credito else Decimal(1)
        for r in f.riepilogo.all():
            chiave = (r.aliquota, r.natura)
            righe.append({"fattura": f, "aliquota": f"{r.aliquota:.0f}%" + (f" {r.natura}" if r.natura else ""),
                          "imponibile": r.imponibile * segno, "imposta": r.imposta * segno})
            voce = riepilogo.setdefault(chiave, {"aliquota": righe[-1]["aliquota"], "imponibile": Decimal(0),
                                                 "imposta": Decimal(0)})
            voce["imponibile"] += r.imponibile * segno
            voce["imposta"] += r.imposta * segno
    if request.GET.get("formato") == "csv":
        risposta = HttpResponse(content_type="text/csv; charset=utf-8")
        risposta["Content-Disposition"] = f'attachment; filename="registro-acquisti-{anno}.csv"'
        scrittore = csv.writer(risposta, delimiter=";")
        scrittore.writerow(["Registrata il", "Numero", "Data", "Fornitore", "Partita IVA", "Aliquota", "Imponibile",
                            "Imposta"])
        for r in righe:
            f = r["fattura"]
            scrittore.writerow([f.registrata_il.strftime("%d/%m/%Y"), f.numero, f.data.strftime("%d/%m/%Y"),
                                f.fornitore.nome, f.fornitore.partita_iva, r["aliquota"],
                                f"{r['imponibile']:.2f}".replace(".", ","), f"{r['imposta']:.2f}".replace(".", ",")])
        return risposta
    voci = list(riepilogo.values())
    oggi = timezone.localdate()
    return render(request, "sdi/registro_acquisti.html", {
        "righe": righe, "riepilogo": voci, "anno": anno, "mese": mese, "anni": range(oggi.year, oggi.year - 6, -1),
        "mesi": list(enumerate(MESI, start=1)), "titolo_periodo": f"{MESI[mese - 1]} {anno}" if mese else str(anno),
        "totale": {"imponibile": sum((v["imponibile"] for v in voci), Decimal(0)),
                   "imposta": sum((v["imposta"] for v in voci), Decimal(0))}})
