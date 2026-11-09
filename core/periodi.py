"""Pagine del kernel per le numerazioni dei documenti e per il periodo chiuso dell'azienda."""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import redirect, render
from django.utils import timezone

from . import blocco, chatter, sequenze
from .models import Azienda, Sequenza


@login_required
@permission_required("core.change_sequenza", raise_exception=True)
def numerazioni(request):
    """Le numerazioni dell'azienda corrente: formato, prossimo numero, azzeramento, con l'anteprima."""
    azienda = request.azienda
    definite = sequenze.definizioni()
    sequenze.crea([v for v in definite.values()], [azienda]) if azienda else None
    righe = list(Sequenza.objects.filter(azienda=azienda, codice__in=definite).order_by("codice"))
    if request.method == "POST":
        seq = next((s for s in righe if str(s.pk) == request.POST.get("sequenza")), None)
        if seq is None:
            messages.error(request, "Numerazione non trovata.")
            return redirect("core:numerazioni")
        formato = request.POST.get("formato", "").strip()[:100]
        try:
            sequenze.formatta(formato, 1)
            if "{numero" not in formato:
                raise ValueError
            prossimo = int(request.POST.get("prossimo", ""))
            if prossimo < 1:
                raise ValueError
        except (ValueError, KeyError, IndexError):
            messages.error(request, "Formato o numero non validi: il formato deve contenere {numero}, per esempio FT/{anno}/{numero:04d}.")
            return redirect("core:numerazioni")
        abbassato = prossimo < seq.prossimo
        seq.formato, seq.prossimo = formato, prossimo
        seq.azzera = request.POST.get("azzera") if request.POST.get("azzera") in (Sequenza.MAI, Sequenza.ANNO) else seq.azzera
        seq.personalizzata = True
        if seq.azzera == Sequenza.ANNO:              # il numero scritto vale per quest'anno: non si azzera subito
            seq.anno = timezone.localdate().year
        seq.save()
        messages.success(request, f"Numerazione salvata: il prossimo sarà {sequenze.formatta(formato, prossimo)}."
                         + (" Attenzione: hai abbassato il numero, controlla che non esista già." if abbassato else ""))
        return redirect("core:numerazioni")
    for s in righe:
        s.voce = definite.get(s.codice, {})
        try:
            s.anteprima = sequenze.formatta(s.formato, s.prossimo)
        except (ValueError, KeyError, IndexError):
            s.anteprima = "formato non valido"
    return render(request, "core/numerazioni.html", {"righe": righe})


@login_required
@permission_required("core.change_azienda", raise_exception=True)
def periodo_chiuso(request, pk):
    from django.shortcuts import get_object_or_404
    azienda = get_object_or_404(Azienda, pk=pk)
    if request.method == "POST":
        testo = request.POST.get("data", "")
        try:
            data = datetime.date.fromisoformat(testo) if testo else None
        except ValueError:
            messages.error(request, "Data non valida.")
            return redirect("core:aziende_dettaglio", pk=pk)
        if data and data > timezone.localdate():
            messages.error(request, "Non si chiude un periodo che non è ancora finito.")
            return redirect("core:aziende_dettaglio", pk=pk)
        prima = azienda.chiuso_fino_al
        azienda.chiuso_fino_al = data
        azienda.save(update_fields=["chiuso_fino_al"])
        chatter.scrivi(azienda, request.user, f"Periodo chiuso: da {prima:%d/%m/%Y} a {data:%d/%m/%Y}." if prima and data else
                       f"Periodo chiuso fino al {data:%d/%m/%Y}." if data else "Periodo riaperto.", tipo="nota")
        messages.success(request, f"Periodo chiuso fino al {data:%d/%m/%Y}." if data else "Periodo riaperto.")
    return redirect("core:aziende_dettaglio", pk=pk)


@login_required
@permission_required("core.change_pianificazione", raise_exception=True)
def pianificazioni(request):
    """I lavori pianificati dei moduli: quando girano, l'ultima e la prossima volta, accesi o spenti."""
    from .models import Pianificazione
    if request.method == "POST":
        p = Pianificazione.objects.filter(pk=request.POST.get("pk")).first()
        if p is not None:
            if request.POST.get("azione") == "ora":
                p.prossima_esecuzione = timezone.now()
                p.save(update_fields=["prossima_esecuzione"])
                messages.success(request, f"«{p.nome}» parte al prossimo giro (entro un minuto).")
            else:
                p.attiva = not p.attiva
                p.save(update_fields=["attiva"])
                messages.success(request, f"«{p.nome}» {'acceso' if p.attiva else 'spento'}.")
        return redirect("core:pianificazioni")
    return render(request, "core/pianificazioni.html", {"righe": Pianificazione.objects.order_by("modulo", "nome")})
