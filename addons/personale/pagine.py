"""Le mie assenze: saldo, richieste fatte e una nuova richiesta, per il dipendente collegato all'utente."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.viste import registry

from . import flusso, organigramma as org, saldi
from .models import Assenza, Dipendente, Reparto, TipoAssenza


class RichiestaForm(forms.ModelForm):
    class Meta:
        model = Assenza
        fields = ["tipo", "dal", "al", "ore", "motivo"]
        widgets = {"dal": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "al": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, dipendente=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.dipendente, self.instance.azienda = dipendente, dipendente.azienda
        self.fields["tipo"].queryset = TipoAssenza.objects.filter(attivo=True)
        for campo in self.fields.values():
            campo.widget.attrs.setdefault("class", "ui-input")


@login_required
@permission_required("personale.add_assenza", raise_exception=True)
def mie(request):
    dipendente = Dipendente.objects.filter(utente=request.user, attivo=True).select_related("azienda").first()
    if dipendente is None:
        return render(request, "personale/mie.html", {"dipendente": None})
    form = RichiestaForm(request.POST or None, dipendente=dipendente)
    if request.method == "POST" and form.is_valid():
        assenza = form.save()
        flusso.richiesta_inviata(assenza, request.user)
        messages.success(request, f"Richiesta inviata: {assenza}." + (
            "" if dipendente.approvatori() else " Nessun responsabile indicato: la vedrà l'ufficio del personale."))
        return redirect("personale:mie")
    anno = timezone.localdate().year
    return render(request, "personale/mie.html", {
        "dipendente": dipendente, "form": form, "saldo": saldi.saldo(dipendente, anno), "anno": anno,
        "assenze": dipendente.assenze.select_related("tipo")[:30],
        "da_approvare": Assenza.objects.filter(stato=Assenza.RICHIESTA, dipendente__responsabile=dipendente).count()})


@login_required
@permission_required("personale.view_dipendente", raise_exception=True)
def organigramma(request):
    """L'organigramma dell'azienda corrente (o di un reparto), dai responsabili; a lato le posizioni scoperte."""
    vista = registry.per_modello(Dipendente)
    persone = (vista.get_queryset(request).filter(attivo=True)
               .select_related("posizione", "reparto", "utente"))
    reparti = Reparto.objects.filter(azienda=request.azienda).order_by("nome") if request.azienda else Reparto.objects.none()
    reparto = None
    if request.GET.get("reparto", "").isdigit():
        reparto = get_object_or_404(reparti, pk=request.GET["reparto"])
        persone = persone.filter(reparto=reparto)
    persone = list(persone)
    radici = org.albero(persone)

    def link(nodi):
        for n in nodi:
            n.url = vista.url("dettaglio", pk=n.dipendente.pk)
            link(n.figli)
    link(radici)
    return render(request, "personale/organigramma.html", {
        "radici": radici, "totale": len(persone), "reparti": reparti, "reparto": reparto,
        "scoperte": org.scoperte(request.azienda, reparto) if request.azienda else []})


# ---------- timbrature e presenze

@login_required
@permission_required("personale.add_timbratura", raise_exception=True)
def chiosco(request):
    """Il chiosco all'ingresso: badge o PIN, poi Entrata o Uscita (quella giusta è proposta per prima)."""
    from . import presenze
    from .models import Timbratura
    if request.azienda is None:
        from django.http import Http404
        raise Http404
    chiave = f"{request.user.pk}:{request.META.get('REMOTE_ADDR', '')}"
    dipendente, esito = None, ""
    if request.method == "POST":
        if presenze.bloccato(chiave):
            messages.error(request, f"Troppi codici sbagliati: riprova tra {presenze.BLOCCO_MINUTI} minuti.")
            return redirect("personale:chiosco")
        dipendente = presenze.riconosci(request.azienda, request.POST.get("codice"), chiave)
        if dipendente is None:
            messages.error(request, "Badge o PIN non riconosciuto.")
            return redirect("personale:chiosco")
        verso = request.POST.get("verso")
        if verso in (Timbratura.ENTRATA, Timbratura.USCITA):
            t = presenze.timbra(dipendente, verso, "chiosco")
            messages.success(request, f"{'Buongiorno' if verso == 'entrata' else 'Arrivederci'}, {dipendente.nome}: {t.get_verso_display().lower()} alle {timezone.localtime(t.il):%H:%M}.")
            return redirect("personale:chiosco")
        esito = presenze.prossimo_verso(dipendente)
    return render(request, "personale/chiosco.html", {"dipendente": dipendente, "proposto": esito,
                                                      "codice": request.POST.get("codice", "") if dipendente else ""})


@login_required
def timbra_io(request):
    """Il dipendente collegato all'utente timbra dal web o dal telefono."""
    from . import presenze
    dipendente = Dipendente.objects.filter(utente=request.user, attivo=True).first()
    if dipendente is None:
        messages.error(request, "Il tuo utente non è collegato a una scheda dipendente.")
        return redirect("core:tasca")
    if request.method == "POST":
        t = presenze.timbra(dipendente, request.POST.get("verso") or None, "web")
        messages.success(request, f"{t.get_verso_display()} registrata alle {timezone.localtime(t.il):%H:%M}.")
        return redirect("personale:timbra_io")
    oggi = presenze.giornata(dipendente, timezone.localdate())
    return render(request, "personale/timbra_io.html", {"dipendente": dipendente, "proposto": presenze.prossimo_verso(dipendente),
                                                        "oggi": oggi})


def _mese_richiesto(request):
    oggi = timezone.localdate()
    try:
        anno, numero = (int(x) for x in request.GET.get("mese", "").split("-"))
        datetime_ok = 1 <= numero <= 12 and 2000 <= anno <= 2100
    except ValueError:
        datetime_ok = False
    return (anno, numero) if datetime_ok else (oggi.year, oggi.month)


@login_required
@permission_required("personale.view_timbratura", raise_exception=True)
def presenze_mese(request):
    from . import presenze
    anno, numero = _mese_richiesto(request)
    if request.GET.get("formato") == "xlsx":
        from django.http import HttpResponse
        r = HttpResponse(presenze.esporta(request.azienda, anno, numero),
                         content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        r["Content-Disposition"] = f'attachment; filename="presenze-{anno}-{numero:02d}.xlsx"'
        return r
    righe = presenze.riepilogo(request.azienda, anno, numero) if request.azienda else []
    scelto = next((r for r in righe if str(r["dipendente"].pk) == request.GET.get("dipendente")), None)
    import datetime as dt
    primo = dt.date(anno, numero, 1)
    prima = (primo - dt.timedelta(days=1)).strftime("%Y-%m")
    dopo = (primo + dt.timedelta(days=32)).replace(day=1).strftime("%Y-%m")
    return render(request, "personale/presenze.html", {"righe": righe, "scelto": scelto, "mese": primo, "prima": prima, "dopo": dopo,
                                                       "valore_mese": primo.strftime("%Y-%m")})


@login_required
@permission_required("personale.change_dipendente", raise_exception=True)
def imposta_pin(request, pk):
    from django.shortcuts import get_object_or_404

    from core.viste import registry

    from . import presenze
    vista = registry.per_modello(Dipendente)
    dipendente = get_object_or_404(vista.get_queryset(request), pk=pk)
    if request.method == "POST":
        try:
            presenze.imposta_pin(dipendente, request.POST.get("pin"))
        except ValueError as e:
            messages.error(request, str(e))
            return redirect("personale:imposta_pin", pk=pk)
        messages.success(request, f"PIN di {dipendente} impostato: lo usa al chiosco per timbrare.")
        return redirect(vista.url("dettaglio", pk=pk))
    return render(request, "personale/pin.html", {"dipendente": dipendente, "url_dettaglio": vista.url("dettaglio", pk=pk)})
