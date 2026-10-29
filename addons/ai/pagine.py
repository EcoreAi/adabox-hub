"""Chat con l'assistente: pagina a tutto schermo a tre colonne (pannelli laterali chiusi di default)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.registry import modules

from . import motore, suggerimenti
from .models import Conversazione, MessaggioChat, Turno

PANNELLI_SINISTRA = [("storico", "Cronologia chat", "ai-storico"), ("preferite", "Chat preferite", "ai-stella")]
PANNELLI_DESTRA = [("artifact", "Artifact salvati", "ai-artifact"), ("documenti", "Documenti salvati", "ai-documento"),
                   ("grafici", "Grafici salvati", "ai-grafico")]


def _mie(request):
    return Conversazione.objects.filter(utente=request.user)


def app_selezionabili(user):
    """Le app che l'utente vede (tranne l'assistente stesso): la chat si può limitare a una di queste."""
    return [a for a in modules.app_visibili(user) if a["slug"] != "ai"]


def _avviso_spesa(request):
    """Testo dell'avviso quando la spesa del mese si avvicina al tetto (o l'assistente non è attivo)."""
    from core import parametri

    from . import licenza, limiti
    stato = licenza.attuale()
    if not stato.valida:
        return f"L'assistente non è attivo: {stato.motivo}"
    azienda = getattr(request, "azienda", None)
    if azienda is None or limiti.tetto(azienda) <= 0:
        return ""
    spesa, tetto = limiti.spesa_mese(azienda), limiti.tetto(azienda)
    soglia = tetto * (parametri.leggi("ai.avviso_percentuale", azienda) or 80) / 100
    if spesa >= tetto:
        return "Raggiunto il tetto di spesa mensile: l'assistente riprenderà il mese prossimo."
    if spesa >= soglia:
        return f"Spesa del mese a {spesa:.2f} $ su {tetto} $."
    return ""


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def chat(request, pk=None):
    conversazione = get_object_or_404(_mie(request), pk=pk) if pk else None
    mie = _mie(request)
    app = app_selezionabili(request.user)
    ambito = next((a for a in app if conversazione and a["slug"] == conversazione.ambito), None)
    if conversazione is not None:
        motore.segna_interrotti(conversazione)
    in_corso = conversazione.turni.filter(stato=Turno.IN_CORSO).first() if conversazione else None
    return render(request, "ai/chat.html", {
        "conversazione": conversazione, "ambito": ambito, "turno": in_corso, "avviso_spesa": _avviso_spesa(request),
        "messaggi": conversazione.messaggi.all() if conversazione else [],
        "storico": mie[:50], "preferite": mie.filter(preferita=True)[:50],
        "pannelli_sinistra": PANNELLI_SINISTRA, "pannelli_destra": PANNELLI_DESTRA,
        "app": app, "suggerimenti": suggerimenti.per(), "suggerimenti_per_app": suggerimenti.tutti(),
    })


@require_POST
@login_required
@permission_required("ai.add_conversazione", raise_exception=True)
def invia(request, pk=None):
    testo = request.POST.get("testo", "").strip()
    conversazione = get_object_or_404(_mie(request), pk=pk) if pk else None
    if not testo:
        return HttpResponse(status=204) if request.headers.get("HX-Request") else redirect(
            reverse("ai:conversazione", args=[pk]) if pk else reverse("ai:chat"))
    nuova = conversazione is None
    if nuova:
        titolo = " ".join(testo.split())
        ammessi = {a["slug"] for a in app_selezionabili(request.user)}
        ambito = request.POST.get("ambito", "")
        conversazione = Conversazione.objects.create(utente=request.user, ambito=ambito if ambito in ammessi else "",
                                                     titolo=titolo[:60] + ("…" if len(titolo) > 60 else ""))
    primo = conversazione.messaggi.order_by("-pk").values_list("pk", flat=True).first() or 0
    turno = motore.avvia(conversazione, testo, request.user, getattr(request, "azienda", None))
    conversazione.save(update_fields=["aggiornata"])
    url = reverse("ai:conversazione", args=[conversazione.pk])
    if request.headers.get("HX-Request"):
        if nuova:                                        # nuova chat: si carica la pagina della conversazione
            return HttpResponse(status=204, headers={"HX-Redirect": url})
        turno.refresh_from_db()
        return render(request, "ai/_messaggi.html", {
            "messaggi": conversazione.messaggi.filter(pk__gt=primo), "turno": None if turno.concluso else turno})
    return redirect(url)


@require_POST
@login_required
def preferita(request, pk):
    c = get_object_or_404(_mie(request), pk=pk)
    c.preferita = not c.preferita
    c.save(update_fields=["preferita"])
    return redirect("ai:conversazione", pk=c.pk)


@require_POST
@login_required
@permission_required("ai.delete_conversazione", raise_exception=True)
def elimina(request, pk):
    c = get_object_or_404(_mie(request), pk=pk)
    c.delete()
    messages.success(request, "Conversazione eliminata.")
    return redirect("ai:chat")


@require_POST
@login_required
def stop(request, pk):
    turno = get_object_or_404(Turno, pk=pk, conversazione__utente=request.user)
    motore.ferma(turno)
    return HttpResponse(status=204)


@login_required
@permission_required("ai.change_licenza", raise_exception=True)
def pagina_licenza(request):
    """Stato della licenza e caricamento di un nuovo file."""
    from . import licenza, limiti
    from .models import Licenza
    if request.method == "POST":
        file = request.FILES.get("file")
        testo = file.read().decode("utf-8", errors="replace") if file else request.POST.get("testo", "")
        stato = licenza.leggi(testo)
        if stato.valida:
            Licenza.objects.create(testo=testo, caricata_da=request.user)
            messages.success(request, f"Licenza di {stato.cliente} caricata: valida fino al {stato.scadenza:%d/%m/%Y}.")
        else:
            messages.error(request, f"Licenza non caricata: {stato.motivo}")
        return redirect("ai:licenza")
    azienda = getattr(request, "azienda", None)
    return render(request, "ai/licenza.html", {
        "stato": licenza.attuale(), "spesa": limiti.spesa_mese(azienda) if azienda else None,
        "tetto": limiti.tetto(azienda) if azienda else None, "utenti_mese": len(limiti.utenti_del_mese())})
