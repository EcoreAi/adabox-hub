"""L'archivio: albero delle cartelle, documenti, anteprima, caricamento, azioni di massa, download."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core import allegati

from . import accesso, richieste, servizi
from .models import Cartella, Condivisione, Documento, Richiesta, Tag


def _albero(cartelle, conteggi):
    """[{cartella, figlie, n}] dalle cartelle visibili; una cartella con la madre invisibile va in cima."""
    pk = {c.pk for c in cartelle}
    nodi = {c.pk: {"cartella": c, "figlie": [], "n": conteggi.get(c.pk, 0)} for c in cartelle}
    radici = []
    for c in sorted(cartelle, key=lambda c: c.nome.lower()):
        (nodi[c.padre_id]["figlie"] if c.padre_id in pk else radici).append(nodi[c.pk])
    return radici


def _url_archivio(cartella=None, cestino=False):
    base = reverse("documenti:archivio")
    return f"{base}?cartella=cestino" if cestino else f"{base}?cartella={cartella.pk}" if cartella else base


@login_required
@permission_required("documenti.view_documento", raise_exception=True)
def archivio(request):
    azienda = request.azienda
    visibili = accesso.visibili(request.user, azienda)
    scrivibili = {c.pk for c in accesso.scrivibili(request.user, azienda)}
    tutti = Documento.objects.filter(azienda=azienda, cartella__in=[c.pk for c in visibili])
    conteggi = dict(tutti.filter(cestinato_il__isnull=True).values_list("cartella").annotate(n=Count("pk")))
    scelta = request.GET.get("cartella", "")
    cestino = scelta == "cestino"
    corrente = next((c for c in visibili if str(c.pk) == scelta), None)
    if cestino:
        documenti = tutti.filter(cestinato_il__isnull=False)
    elif corrente is not None:
        documenti = tutti.filter(cartella=corrente, cestinato_il__isnull=True)
    else:
        documenti = tutti.filter(cestinato_il__isnull=True)
    q = request.GET.get("q", "").strip()
    if q:
        documenti = documenti.filter(Q(nome__icontains=q) | Q(descrizione__icontains=q))
    tag = request.GET.get("tag", "")
    if tag.isdigit():
        documenti = documenti.filter(tag=int(tag))
    documenti = documenti.select_related("cartella", "proprietario").prefetch_related("tag")[:500]
    contesto = {
        "albero": _albero(visibili, conteggi), "corrente": corrente, "cestino": cestino, "documenti": documenti,
        "tag": Tag.objects.all(), "tag_scelto": int(tag) if tag.isdigit() else None, "q": q,
        "puo_caricare": corrente is not None and corrente.pk in scrivibili,
        "cartelle_scrivibili": [c for c in visibili if c.pk in scrivibili],
        "totale": sum(conteggi.values()), "n_cestino": tutti.filter(cestinato_il__isnull=False).count(),
        "spazio": servizi.spazio_usato(azienda),
    }
    if request.headers.get("HX-Request") and request.GET.get("parziale"):
        return render(request, "documenti/_griglia.html", contesto)
    return render(request, "documenti/archivio.html", contesto)


def _documento(request, pk):
    documento = get_object_or_404(accesso.documenti(request.user, request.azienda), pk=pk)
    return documento


@login_required
@permission_required("documenti.view_documento", raise_exception=True)
def anteprima(request, pk):
    documento = _documento(request, pk)
    return render(request, "documenti/_anteprima.html", {
        "d": documento, "tag": Tag.objects.all(), "puo_modificare": accesso.puo_modificare(request.user, documento)})


@login_required
@permission_required("documenti.view_documento", raise_exception=True)
def scarica(request, pk):
    documento = _documento(request, pk)
    return servizi.risposta(documento, in_linea=request.GET.get("inline") == "1")


@login_required
@permission_required("documenti.add_documento", raise_exception=True)
@require_POST
def carica(request):
    cartella = get_object_or_404(Cartella, pk=request.POST.get("cartella", 0) or 0, azienda=request.azienda)
    if not accesso.puo_scrivere(request.user, cartella):
        raise PermissionDenied
    caricati, errori = [], []
    for file in request.FILES.getlist("file"):
        try:
            caricati.append(servizi.carica(cartella, file, request.user))
        except allegati.AllegatoNonValido as e:
            errori.append(str(e))
    if request.headers.get("Accept") == "application/json":
        return JsonResponse({"caricati": [d.pk for d in caricati], "errori": errori}, status=400 if errori and not caricati else 200)
    if caricati:
        messages.success(request, f"Documenti caricati: {len(caricati)}.")
    for e in errori:
        messages.error(request, e)
    return redirect(_url_archivio(cartella))


@login_required
@permission_required("documenti.add_documento", raise_exception=True)
@require_POST
def nuova_cartella(request):
    nome = request.POST.get("nome", "").strip()[:120]
    padre = None
    if request.POST.get("padre"):
        padre = get_object_or_404(Cartella, pk=request.POST["padre"], azienda=request.azienda)
        if not accesso.puo_scrivere(request.user, padre):
            raise PermissionDenied
    elif not request.user.has_perm("documenti.add_cartella"):
        raise PermissionDenied                       # in cima solo chi gestisce le cartelle
    if not nome:
        messages.error(request, "Indica il nome della cartella.")
        return redirect(_url_archivio(padre))
    cartella = Cartella.objects.create(azienda=request.azienda, nome=nome, padre=padre)
    return redirect(_url_archivio(cartella))


@login_required
@permission_required("documenti.change_documento", raise_exception=True)
@require_POST
def modifica(request, pk):
    documento = _documento(request, pk)
    if not accesso.puo_modificare(request.user, documento):
        raise PermissionDenied
    nome = request.POST.get("nome", "").strip()[:200]
    if nome:
        documento.nome = nome
    documento.descrizione = request.POST.get("descrizione", documento.descrizione)
    documento.save(update_fields=["nome", "descrizione", "modificato"])
    documento.tag.set(Tag.objects.filter(pk__in=[t for t in request.POST.getlist("tag") if t.isdigit()]))
    messages.success(request, f"«{documento}» aggiornato.")
    return redirect(_url_archivio(documento.cartella))


@login_required
@permission_required("documenti.view_documento", raise_exception=True)
@require_POST
def azione(request):
    """Azioni sui documenti selezionati: zip, sposta, tag, cestina, ripristina, elimina."""
    nome = request.POST.get("azione", "")
    pks = [p for p in request.POST.getlist("pk") if p.isdigit()]
    documenti = list(accesso.documenti(request.user, request.azienda).filter(pk__in=pks))
    ritorno = request.POST.get("ritorno") or reverse("documenti:archivio")
    if not ritorno.startswith("/"):
        ritorno = reverse("documenti:archivio")
    if not documenti:
        messages.warning(request, "Nessun documento selezionato.")
        return redirect(ritorno)
    if nome == "zip":
        try:
            contenuto = servizi.zip_di(documenti)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect(ritorno)
        risposta = HttpResponse(contenuto, content_type="application/zip")
        risposta["Content-Disposition"] = 'attachment; filename="documenti.zip"'
        return risposta
    if nome == "condividi":
        if not request.user.has_perm("documenti.add_condivisione"):
            raise PermissionDenied
        import datetime

        from django.utils import timezone
        condivisione = Condivisione.objects.create(
            azienda=request.azienda, nome=f"Condivisione del {timezone.localdate():%d/%m/%Y}", creata_da=request.user,
            scadenza=timezone.localdate() + datetime.timedelta(days=30))
        condivisione.documenti.set(documenti)
        messages.success(request, f"Link creato per {len(documenti)} documenti: valido 30 giorni (modificabile).")
        return redirect("documenti:condivisioni_dettaglio", pk=condivisione.pk)
    modificabili = [d for d in documenti if accesso.puo_modificare(request.user, d)]
    if len(modificabili) < len(documenti):
        messages.warning(request, f"Documenti esclusi perché bloccati o in cartelle di sola lettura: "
                                  f"{len(documenti) - len(modificabili)}.")
    if nome == "sposta":
        cartella = Cartella.objects.filter(pk=request.POST.get("cartella") or 0, azienda=request.azienda).first()
        if cartella is None or not accesso.puo_scrivere(request.user, cartella):
            raise PermissionDenied
        messages.success(request, f"Spostati in {cartella}: {servizi.sposta(modificabili, cartella)}.")
    elif nome == "tag":
        tag = get_object_or_404(Tag, pk=request.POST.get("tag") or 0)
        for d in modificabili:
            d.tag.add(tag)
        messages.success(request, f"Tag «{tag}» aggiunto a {len(modificabili)} documenti.")
    elif nome == "cestina":
        messages.success(request, f"Nel cestino: {servizi.cestina(modificabili)}.")
    elif nome == "ripristina":
        messages.success(request, f"Ripristinati: {servizi.ripristina(modificabili)}.")
    elif nome == "elimina":
        if not request.user.has_perm("documenti.delete_documento"):
            raise PermissionDenied
        messages.success(request, f"Eliminati definitivamente: {servizi.elimina(modificabili)}.")
    else:
        raise Http404("Azione sconosciuta")
    return redirect(ritorno)


@login_required
@require_POST
def evadi(request, pk):
    """Il destinatario carica il documento richiesto, che va nella cartella della richiesta."""
    richiesta = get_object_or_404(Richiesta, pk=pk, azienda=request.azienda, destinatario=request.user,
                                  stato=Richiesta.APERTA)
    file = request.FILES.get("file")
    if file is None:
        messages.error(request, "Scegli un file.")
        return redirect("documenti:richieste_dettaglio", pk=pk)
    try:
        documento = richieste.evadi(richiesta, file, request.user)
    except allegati.AllegatoNonValido as e:
        messages.error(request, str(e))
        return redirect("documenti:richieste_dettaglio", pk=pk)
    messages.success(request, f"«{documento}» archiviato in {richiesta.cartella}. Richiesta completata.")
    return redirect("documenti:richieste_dettaglio", pk=pk)
