"""Le pagine delle automazioni: regole, regole pronte, storico e modelli delle email."""
import uuid

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import modelli_email
from core.generici import url_record
from core.models import ModelloEmail, TipoAttivita

from . import catalogo, motore, regole as controlli, ricette
from .models import Esecuzione, Regola

VEDI, CAMBIA = "automazioni.view_regola", "automazioni.change_regola"
VEDI_MODELLI, CAMBIA_MODELLI = "core.view_modelloemail", "core.change_modelloemail"


def _regola(request, pk):
    return get_object_or_404(Regola.objects.select_related("azienda"), pk=pk, azienda=request.azienda)


def _scheda(regola):
    return {"regola": regola, "quando": controlli.descrivi_quando(regola), "se": controlli.descrivi_condizioni(regola),
            "allora": controlli.descrivi_azioni(regola), "disponibile": catalogo.evento(regola.evento) is not None}


# ---------- regole

@login_required
@permission_required(VEDI, raise_exception=True)
def regole(request):
    tutte = list(Regola.objects.filter(azienda=request.azienda).annotate(
        volte=Count("esecuzioni", filter=~Q(esecuzioni__esito=Esecuzione.SALTATA)),
        errori=Count("esecuzioni", filter=Q(esecuzioni__esito=Esecuzione.ERRORE)), ultima=Max("esecuzioni__creata")))
    schede = [{**_scheda(r), "volte": r.volte, "errori": r.errori, "ultima": r.ultima} for r in tutte]
    return render(request, "automazioni/regole.html", {
        "schede": schede, "attive": sum(1 for r in tutte if r.attiva), "ricette": ricette.disponibili(),
        "puo_cambiare": request.user.has_perm(CAMBIA)})


def _dati_costruttore(azienda):
    gruppi = {}
    for e in catalogo.eventi().values():
        d = catalogo.domini()[e.dominio]
        gruppi.setdefault(d.nome, []).append({"codice": e.codice, "nome": e.nome, "dominio": e.dominio, "giorni": e.giorni,
                                              "giorni_default": e.giorni_default})
    modelli = {}
    for m in ModelloEmail.objects.filter(azienda=azienda).exclude(dominio=""):
        modelli.setdefault(m.dominio, []).append({"codice": m.codice, "nome": m.nome})
    domini = {}
    for d in catalogo.domini().values():
        domini[d.codice] = {
            "nome": d.nome, "assegna": bool(d.assegna), "modelli": modelli.get(d.codice, []),
            "campi": [{"nome": n, "etichetta": v[0]} for n, v in d.campi.items()],
            "esterni": [{"ruolo": r, "etichetta": v[0]} for r, v in d.esterni.items()],
            "interni": [{"ruolo": r, "etichetta": v[0]} for r, v in d.interni.items()],
            "condizioni": [{"nome": n, "etichetta": v[0], "tipo": v[1],
                            "scelte": [[str(k), str(t)] for k, t in v[3]] if len(v) > 3 else []} for n, v in d.condizioni.items()],
            "modificabili": [{"nome": n, "etichetta": e, "tipo": t, "scelte": s} for n, e, t, s in catalogo.modificabili(d)],
            "bottoni": [{"nome": n, "etichetta": e} for n, e in catalogo.bottoni(d)]}
    return {"gruppi": [{"nome": n, "eventi": v} for n, v in gruppi.items()], "domini": domini,
            "utenti": [{"id": u.pk, "nome": catalogo._nome(u)} for u in controlli.utenti_di(azienda)],
            "tipi": [{"id": t.pk, "nome": t.nome} for t in TipoAttivita.objects.all()]}


@login_required
@permission_required(CAMBIA, raise_exception=True)
def regola_form(request, pk=None):
    if pk is None and not request.user.has_perm("automazioni.add_regola"):
        raise PermissionDenied
    regola = _regola(request, pk) if pk else None
    iniziale = {"nome": regola.nome, "evento": regola.evento, "giorni": regola.giorni, "condizioni": regola.condizioni,
                "azioni": regola.azioni} if regola else {"nome": "", "evento": "", "giorni": "", "condizioni": [], "azioni": []}
    if request.method == "POST":
        try:
            valori = controlli.pulisci(request.POST, request.azienda)
        except ValidationError as e:
            for testo in e.messages:
                messages.error(request, testo)
            iniziale = {k: request.POST.get(k, "") for k in ("nome", "evento", "giorni")}
            iniziale.update(condizioni=_json_sicuro(request.POST.get("condizioni")), azioni=_json_sicuro(request.POST.get("azioni")))
        else:
            if regola is None:
                regola = Regola(azienda=request.azienda, creata_da=request.user)
            cambiato = regola.pk and (regola.evento, regola.giorni) != (valori["evento"], valori["giorni"])
            for campo, valore in valori.items():
                setattr(regola, campo, valore)
            if cambiato and regola.attiva:      # con un evento diverso le attese sono altre: si ricontrolla prima di riaccendere
                regola.attiva = False
                messages.warning(request, "Hai cambiato il quando: la regola è spenta, ricontrolla e riaccendila.")
            regola.save()
            messages.success(request, f"Regola «{regola}» salvata.")
            return redirect("automazioni:regola", pk=regola.pk)
    return render(request, "automazioni/regola_form.html", {"regola": regola, "iniziale": iniziale,
                                                            "dati": _dati_costruttore(request.azienda)})


def _json_sicuro(testo):
    try:
        return controlli._lista(testo, "")
    except ValidationError:
        return []


def _esempio(regola):
    """(record, extra) su cui provare: il primo in attesa, altrimenti l'ultimo record del tipo osservato."""
    evento = catalogo.evento(regola.evento)
    if evento is None:
        return None, {}
    if evento.a_tempo:
        attese = motore.in_attesa(regola)
        return (attese[0][0], attese[0][2]) if attese else (None, {})
    return apps.get_model(evento.modello).objects.filter(azienda=regola.azienda).order_by("-pk").first(), {}


@login_required
@permission_required(VEDI, raise_exception=True)
def regola(request, pk):
    r = _regola(request, pk)
    attese = motore.in_attesa(r) if not r.attiva else []
    return render(request, "automazioni/regola.html", {
        **_scheda(r), "attese": [{"record": a[0], "url": url_record(a[0])} for a in attese[:20]], "numero_attese": len(attese),
        "a_tempo": bool(catalogo.evento(r.evento) and catalogo.evento(r.evento).a_tempo),
        "esecuzioni": [{"e": e, "url": url_record(e.record) if e.record else None}
                       for e in r.esecuzioni.select_related("content_type")[:30]],
        "puo_cambiare": request.user.has_perm(CAMBIA)})


@login_required
@permission_required(VEDI, raise_exception=True)
def regola_prova(request, pk):
    """Che cosa succederebbe, senza mandare né scrivere nulla."""
    r = _regola(request, pk)
    record, extra = _esempio(r)
    return render(request, "automazioni/_prova.html", {"record": record, "passi": motore.simula(r, record, extra) if record else []})


@login_required
@permission_required(CAMBIA, raise_exception=True)
@require_POST
def regola_attiva(request, pk):
    r = _regola(request, pk)
    if catalogo.evento(r.evento) is None:
        messages.error(request, "Questa regola usa un modulo che non è più attivo.")
        return redirect("automazioni:regola", pk=pk)
    motore.accendi(r, anche_esistenti=request.POST.get("esistenti") == "si")
    messages.success(request, f"Regola «{r}» accesa.")
    return redirect("automazioni:regola", pk=pk)


@login_required
@permission_required(CAMBIA, raise_exception=True)
@require_POST
def regola_disattiva(request, pk):
    r = _regola(request, pk)
    r.attiva = False
    r.save(update_fields=["attiva"])
    messages.success(request, f"Regola «{r}» spenta.")
    return redirect("automazioni:regola", pk=pk)


@login_required
@permission_required("automazioni.delete_regola", raise_exception=True)
@require_POST
def regola_elimina(request, pk):
    r = _regola(request, pk)
    nome = str(r)
    r.delete()
    messages.success(request, f"Regola «{nome}» eliminata.")
    return redirect("automazioni:regole")


@login_required
@permission_required("automazioni.add_regola", raise_exception=True)
@require_POST
def ricetta(request, codice):
    voce = ricette.per_codice(codice)
    if voce is None:
        raise Http404
    r = ricette.crea(voce, request.azienda, request.user)
    messages.success(request, "Regola creata, ancora spenta: guardala e accendila quando sei pronto.")
    return redirect("automazioni:regola", pk=r.pk)


# ---------- storico

@login_required
@permission_required(VEDI, raise_exception=True)
def storico(request):
    qs = Esecuzione.objects.filter(regola__azienda=request.azienda).select_related("regola", "content_type")
    esito = request.GET.get("esito")
    if esito in dict(Esecuzione.ESITI):
        qs = qs.filter(esito=esito)
    pagina = Paginator(qs, 50).get_page(request.GET.get("pagina"))
    voci = [{"e": e, "url": url_record(e.record) if e.record else None} for e in pagina]
    return render(request, "automazioni/storico.html", {"pagina": pagina, "voci": voci, "esito": esito, "esiti": Esecuzione.ESITI,
                                                        "puo_cambiare": request.user.has_perm(CAMBIA)})


@login_required
@permission_required(CAMBIA, raise_exception=True)
@require_POST
def riprova(request, pk):
    esecuzione = get_object_or_404(Esecuzione.objects.select_related("regola"), pk=pk, regola__azienda=request.azienda)
    if esecuzione.esito == Esecuzione.FATTA:
        messages.error(request, "Questa esecuzione è già riuscita: rifarla manderebbe tutto una seconda volta.")
        return redirect("automazioni:storico")
    nuova = motore.riprova(esecuzione)
    if nuova is None:
        messages.warning(request, "Le condizioni non valgono più oppure il record non c'è più: nessuna azione.")
    else:
        messages.success(request, f"Fatto: {nuova.get_esito_display().lower()}.")
    return redirect("automazioni:storico")


# ---------- modelli delle email

def _voce_modello(request, codice):
    """Il modello visto dalla pagina: del modulo (con l'eventuale testo dell'azienda) o dell'azienda per le automazioni."""
    definizione = modelli_email.definizioni().get(codice)
    if definizione is not None:
        proprio = modelli_email.personalizzato(codice, request.azienda)
        return {"codice": codice, "nome": definizione["nome"], "gruppo": definizione.get("gruppo", ""), "campi": definizione["campi"],
                "obbligatori": definizione.get("obbligatori", []), "oggetto": proprio.oggetto if proprio else definizione["oggetto"],
                "corpo": proprio.corpo if proprio else definizione["corpo"], "proprio": proprio, "del_modulo": True}
    proprio = get_object_or_404(ModelloEmail, azienda=request.azienda, codice=codice)
    dominio = catalogo.domini().get(proprio.dominio)
    if dominio is None:
        raise Http404
    return {"codice": codice, "nome": proprio.nome, "gruppo": dominio.nome, "campi": _campi_dominio(dominio), "obbligatori": [],
            "oggetto": proprio.oggetto, "corpo": proprio.corpo, "proprio": proprio, "del_modulo": False}


def _campi_dominio(dominio):
    return {**modelli_email.CAMPI_SEMPRE, **{k: list(v) for k, v in dominio.campi.items()}}


def _esempi(campi):
    return {nome: voce[1] for nome, voce in campi.items()}


@login_required
@permission_required(VEDI, raise_exception=True)
def modelli_elenco(request):
    """Per il costruttore: un modello creato in un'altra scheda compare senza perdere la regola che si sta scrivendo."""
    voci = ModelloEmail.objects.filter(azienda=request.azienda).exclude(dominio="").order_by("nome")
    elenco = {}
    for m in voci:
        elenco.setdefault(m.dominio, []).append({"codice": m.codice, "nome": m.nome})
    return JsonResponse(elenco)


@login_required
@permission_required(VEDI_MODELLI, raise_exception=True)
def modelli(request):
    propri = {m.codice: m for m in ModelloEmail.objects.filter(azienda=request.azienda)}
    gruppi = {}
    for codice, d in sorted(modelli_email.definizioni().items(), key=lambda v: v[1]["nome"]):
        gruppi.setdefault(d.get("gruppo") or "Altro", []).append({"codice": codice, "nome": d["nome"], "oggetto": d["oggetto"],
                                                                 "proprio": propri.get(codice), "del_modulo": True})
    automazioni = [{"codice": m.codice, "nome": m.nome, "oggetto": m.oggetto, "proprio": m, "del_modulo": False,
                    "gruppo": catalogo.domini()[m.dominio].nome}
                   for m in propri.values() if m.dominio in catalogo.domini()]
    return render(request, "automazioni/modelli.html", {
        "gruppi": sorted(gruppi.items()), "automazioni": sorted(automazioni, key=lambda v: v["nome"]),
        "domini": catalogo.domini().values(), "puo_cambiare": request.user.has_perm(CAMBIA_MODELLI)})


def _salva(request, voce, dominio=""):
    oggetto, corpo = request.POST.get("oggetto", "").strip()[:250], request.POST.get("corpo", "").strip()
    problemi = modelli_email.errori(oggetto, corpo, voce["campi"], voce["obbligatori"])
    nome = request.POST.get("nome", "").strip()[:120] if not voce["del_modulo"] else ""
    if not voce["del_modulo"] and not nome:
        problemi.append("Dai un nome al modello.")
    if problemi:
        for testo in problemi:
            messages.error(request, testo)
        voce.update(oggetto=oggetto, corpo=corpo, nome=nome or voce["nome"])
        return False
    ModelloEmail.objects.update_or_create(azienda=request.azienda, codice=voce["codice"], defaults={
        "oggetto": oggetto, "corpo": corpo, "nome": nome, "dominio": dominio, "aggiornato_da": request.user})
    messages.success(request, "Modello salvato.")
    return True


@login_required
@permission_required(CAMBIA_MODELLI, raise_exception=True)
def modello_nuovo(request):
    dominio = catalogo.domini().get(request.POST.get("dominio") or request.GET.get("dominio"))
    if dominio is None:
        messages.error(request, "Scegli su che tipo di record si usa il modello.")
        return redirect("automazioni:modelli")
    voce = {"codice": f"personale.{uuid.uuid4().hex[:12]}", "nome": "", "gruppo": dominio.nome, "campi": _campi_dominio(dominio),
            "obbligatori": [], "oggetto": "", "corpo": "", "proprio": None, "del_modulo": False}
    if request.method == "POST" and _salva(request, voce, dominio.codice):
        return redirect("automazioni:modelli")
    return render(request, "automazioni/modello.html", {"voce": voce, "dominio": dominio.codice, "nuovo": True})


@login_required
@permission_required(VEDI_MODELLI, raise_exception=True)
def modello(request, codice):
    voce = _voce_modello(request, codice)
    if request.method == "POST":
        if not request.user.has_perm(CAMBIA_MODELLI):
            raise PermissionDenied
        dominio = voce["proprio"].dominio if voce["proprio"] else ""
        if _salva(request, voce, dominio):
            return redirect("automazioni:modello", codice=codice)
    return render(request, "automazioni/modello.html", {"voce": voce, "dominio": voce["proprio"].dominio if voce["proprio"] else "",
                                                        "puo_cambiare": request.user.has_perm(CAMBIA_MODELLI),
                                                        "usato_da": controlli.modelli_usati_da(request.azienda, codice)})


def _campi_richiesta(request):
    codice = request.POST.get("codice", "")
    if codice in modelli_email.definizioni():
        return _voce_modello(request, codice)["campi"]
    dominio = catalogo.domini().get(request.POST.get("dominio", ""))
    return _campi_dominio(dominio) if dominio else modelli_email.CAMPI_SEMPRE


@login_required
@permission_required(VEDI_MODELLI, raise_exception=True)
@require_POST
def modello_anteprima(request):
    """Il testo non ancora salvato, riempito con i valori di esempio."""
    campi = _campi_richiesta(request)
    oggetto, corpo = request.POST.get("oggetto", ""), request.POST.get("corpo", "")
    titolo, _, html = modelli_email.componi(oggetto, corpo, _esempi(campi), request.azienda)
    sconosciuti = sorted((modelli_email.segnaposto_in(oggetto) | modelli_email.segnaposto_in(corpo)) - set(campi))
    return JsonResponse({"oggetto": titolo, "html": html, "sconosciuti": sconosciuti})


@login_required
@permission_required(CAMBIA_MODELLI, raise_exception=True)
@require_POST
def modello_prova(request, codice):
    """Manda il testo non ancora salvato a chi sta scrivendo, e a nessun altro."""
    if not request.user.email:
        return JsonResponse({"ok": False, "errore": "Il tuo utente non ha un indirizzo email."})
    campi = _campi_richiesta(request)
    modelli_email.messaggio_da(request.POST.get("oggetto", ""), request.POST.get("corpo", ""), _esempi(campi), request.azienda,
                               [request.user.email]).send()
    return JsonResponse({"ok": True, "a": request.user.email})


@login_required
@permission_required("core.delete_modelloemail", raise_exception=True)
@require_POST
def modello_ripristina(request, codice):
    """Del modulo: torna al testo originale. Dell'azienda: si elimina, se nessuna regola lo usa."""
    proprio = get_object_or_404(ModelloEmail, azienda=request.azienda, codice=codice)
    usato = controlli.modelli_usati_da(request.azienda, codice)
    if usato:
        messages.error(request, f"Lo usa la regola «{usato[0]}»: cambiala prima di eliminare il modello.")
        return redirect("automazioni:modello", codice=codice)
    del_modulo = codice in modelli_email.definizioni()
    proprio.delete()
    messages.success(request, "Testo originale ripristinato." if del_modulo else "Modello eliminato.")
    return redirect("automazioni:modello", codice=codice) if del_modulo else redirect("automazioni:modelli")
