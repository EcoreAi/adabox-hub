"""Pagine di Studio: elenco delle viste, editor, storico, esportazione e importazione."""
import json
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import campi, servizi
from .models import Personalizzazione

PERMESSO = "studio.change_personalizzazione"


def _vista(modulo, slug):
    vista = servizi.trova(modulo, slug)
    if vista is None:
        raise Http404("Vista non trovata")
    return vista


@login_required
@permission_required(PERMESSO, raise_exception=True)
def indice(request):
    personalizzate = {(p.modulo, p.vista): p for p in Personalizzazione.objects.exclude(dati={})}
    gruppi = [(modulo, [(v, personalizzate.get((modulo, v.slug))) for v in viste]) for modulo, viste in servizi.tutte()]
    return render(request, "studio/indice.html", {"gruppi": gruppi})


@login_required
@permission_required(PERMESSO, raise_exception=True)
def editor(request, modulo, slug):
    vista = _vista(modulo, slug)
    riga = Personalizzazione.objects.filter(modulo=modulo, vista=slug).first()
    originali = campi.valori_originali(vista)
    problemi = []
    if request.method == "POST":
        try:
            dati = json.loads(request.POST.get("dati", ""))
            if not isinstance(dati, dict):
                raise ValueError
        except ValueError:
            dati, problemi = {}, ["Dati dell'editor non validi."]
        dati = {k: v for k, v in dati.items() if k in originali}
        problemi = problemi or campi.errori(vista, dati)
        if not problemi:
            servizi.salva(vista, {**originali, **dati}, request.user)
            messages.success(request, f"Vista «{vista.verbose_name_plural}» salvata.")
            return redirect("studio:editor", modulo=modulo, slug=slug)
        for p in problemi:
            messages.error(request, p)
    attuali = {**originali, **campi.pulisci(vista, riga.dati if riga else {})}
    disponibili = campi.disponibili(vista)
    stato = {"attuali": attuali, "originali": originali, "disponibili": disponibili,
             "obbligatori": campi.obbligatori(vista), "kanban": bool(vista.kanban_group),
             "form_modificabile": not vista.form_class,
             "etichette_base": {n: str(vista.etichetta(n)) for n, _ in disponibili["list_display"] + disponibili["form"]
                                if not n.startswith(("@", "prop_"))}}
    return render(request, "studio/editor.html", {
        "vista": vista, "riga": riga, "stato": stato, "versioni": _versioni(riga),
        "personalizzata": bool(riga and riga.dati), "url_vista": vista.url("lista"),
    })


def _versioni(riga):
    risultato = []
    for i, v in enumerate(riga.storico if riga else []):
        try:
            quando = datetime.fromisoformat(v.get("quando", ""))
        except ValueError:
            quando = None
        risultato.append({"indice": i, "quando": quando, "utente": v.get("utente", ""), "originale": not v.get("dati")})
    return risultato


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def ripristina(request, modulo, slug):
    vista = _vista(modulo, slug)
    indice = request.POST.get("versione", "")
    try:
        servizi.ripristina(vista, int(indice) if indice.isdigit() else None, request.user)
    except IndexError:
        raise Http404("Versione non trovata")
    messages.success(request, "Versione ripristinata." if indice.isdigit() else "Vista riportata all'originale.")
    return redirect("studio:editor", modulo=modulo, slug=slug)


@login_required
@permission_required(PERMESSO, raise_exception=True)
def esporta(request):
    risposta = JsonResponse(servizi.esporta(), json_dumps_params={"ensure_ascii": False, "indent": 2})
    risposta["Content-Disposition"] = 'attachment; filename="studio-personalizzazioni.json"'
    return risposta


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def importa(request):
    file = request.FILES.get("file")
    try:
        contenuto = json.loads(file.read().decode("utf-8")) if file else None
        importate, saltate = servizi.importa(contenuto, request.user)
    except (ValueError, UnicodeDecodeError, ValidationError) as e:
        messages.error(request, f"Importazione non riuscita: {'; '.join(getattr(e, 'messages', [str(e)]))}")
        return redirect("studio:indice")
    messages.success(request, f"Importati: {len(importate)}." + (f" Saltati: {', '.join(saltate)}." if saltate else ""))
    return redirect("studio:indice")
