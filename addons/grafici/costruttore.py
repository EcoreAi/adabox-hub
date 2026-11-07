"""Il costruttore: un grafico o un KPI senza scrivere una query. Si sceglie la vista, la misura, il raggruppamento
(o il campo data e il periodo per un KPI), i filtri della lista, la forma; l'anteprima si aggiorna a ogni scelta e
il salvataggio lo mette in una pagina. La specifica che ne esce è la stessa che scrive l'assistente."""
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.viste import filtri as filtri_lista
from core.viste import interroga
from core.viste.interroga import ErroreInterrogazione

from . import motore
from .models import Grafico
from .pagine import _metti


def _area_scelta(request, destinazione):
    """L'area di lavoro se si arriva dal «Nuovo grafico» della sua dashboard, così resta tra le scelte."""
    if not str(destinazione or "").startswith("area:"):
        return None
    return motore.area_visibile(request.user, getattr(request, "azienda", None), destinazione[5:])

TIPI = [(Grafico.BARRE, "Barre"), (Grafico.BARRE_ORIZZONTALI, "Barre orizzontali"), (Grafico.LINEE, "Linee"),
        (Grafico.AREA, "Area"), (Grafico.TORTA, "Torta"), (Grafico.KPI, "KPI")]
PERIODI = [("giorno", "Giorno"), ("settimana", "Settimana"), ("mese", "Mese"), ("anno", "Anno")]
PERIODI_PREVISIONE = [("mese", "Mese"), ("settimana", "Settimana"), ("giorno", "Giorno")]
ORIZZONTI = [("3", "3 periodi"), ("6", "6 periodi"), ("12", "12 periodi"), ("24", "24 periodi")]
MASSIMI = [("10", "Prime 10"), ("20", "Prime 20"), ("30", "Prime 30"), ("100", "Tutte (fino a 100)")]


def tipi_disponibili():
    """I tipi del costruttore: la previsione solo se il servizio c'è."""
    return TIPI + ([(Grafico.PREVISIONE, "Previsione")] if motore.previsioni_disponibili() else [])


def _viste_per_app(request):
    """[(app, [(nome, etichetta)])] delle viste che l'utente può interrogare, raggruppate per app."""
    from core.registry import modules
    etichette = {a["slug"]: a["label"] for a in modules.app_visibili(request.user)}
    etichette["core"] = "Sistema"
    gruppi = {}
    for v in interroga.viste_accessibili(request):
        gruppi.setdefault(v.modulo, []).append((interroga.id_vista(v), str(v.verbose_name_plural).capitalize()))
    return sorted(((etichette.get(m, m), sorted(voci, key=lambda x: x[1])) for m, voci in gruppi.items()),
                  key=lambda x: x[0].lower())


def parametri_di(request, grafico=None):
    """Lo stato del costruttore: dalla query string se c'è qualcosa, altrimenti dal grafico che si modifica."""
    p = {k: v for k, v in request.GET.items()}
    if not p and grafico is not None:
        spec = grafico.spec
        previsione = grafico.tipo == Grafico.PREVISIONE
        p = {"vista": spec.get("vista", ""), "misura": spec.get("misura", "count"), "per": "" if previsione else spec.get("per", ""),
             "data": spec.get("data", ""), "periodo": spec.get("per", "mese") if previsione else spec.get("periodo", "mese"),
             "orizzonte": str(spec.get("orizzonte") or 3), "tipo": grafico.tipo, "aggiorna_ogni": str(grafico.aggiorna_ogni),
             "massimo": str(spec.get("massimo") or 30), "ordine": spec.get("ordine", ""), "titolo": grafico.titolo,
             "obiettivo": str((grafico.opzioni or {}).get("obiettivo", "") or ""),
             **{k: v for k, v in (spec.get("lista") or {}).items()}}
    p.setdefault("tipo", Grafico.BARRE)
    p.setdefault("misura", "count")
    p.setdefault("periodo", "mese")
    p.setdefault("massimo", "30")
    p.setdefault("orizzonte", "3")
    p.setdefault("aggiorna_ogni", "0")
    return p


def obiettivo_di(p):
    """L'obiettivo (una linea sul grafico, una barra sul KPI) come numero, o None."""
    testo = str(p.get("obiettivo", "") or "").strip().replace(".", "").replace(",", ".") if "," in str(p.get("obiettivo", "")) else str(p.get("obiettivo", "") or "").strip()
    try:
        valore = float(testo)
    except ValueError:
        return None
    return valore if valore > 0 else None


def spec_di(p):
    """La specifica dal form (vuota se manca la vista)."""
    if not p.get("vista"):
        return {}
    spec = {"vista": p["vista"], "misura": p.get("misura") or "count"}
    if p.get("tipo") == Grafico.KPI:
        if p.get("data"):
            spec["data"], spec["periodo"] = p["data"], p.get("periodo") or "mese"
    elif p.get("tipo") == Grafico.PREVISIONE:
        periodo = p.get("periodo") if p.get("periodo") in dict(PERIODI_PREVISIONE) else "mese"
        orizzonte = int(p["orizzonte"]) if str(p.get("orizzonte", "")).isdigit() else 3
        spec.update(data=p.get("data", ""), per=periodo, orizzonte=max(1, min(orizzonte, 24)))
    else:
        spec["per"] = p.get("per", "")
        if p.get("massimo", "30") != "30" and p.get("massimo", "").isdigit():
            spec["massimo"] = int(p["massimo"])
        if p.get("ordine") == "valore":
            spec["ordine"] = "valore"
    lista = {k: v for k, v in p.items() if (k == "q" or k.startswith("f_")) and v != ""}
    if lista:
        spec["lista"] = lista
    return spec


def _anteprima(request, p, vista):
    """Il widget dell'anteprima: un grafico finto, non salvato, calcolato con i dati di adesso."""
    spec = spec_di(p)
    tipo = p.get("tipo", Grafico.BARRE)
    pronto = bool(spec) and (tipo == Grafico.KPI or (spec.get("data") if tipo == Grafico.PREVISIONE else spec.get("per")))
    finto = Grafico(utente=request.user, titolo=p.get("titolo") or motore.descrizione(spec, vista=vista, tipo=tipo), tipo=tipo, spec=spec,
                    opzioni={"obiettivo": obiettivo_di(p)} if obiettivo_di(p) else {})
    w = {"id": "anteprima", "tipo": "salvato", "titolo": finto.titolo, "grafico": finto, "dom": "wd-anteprima", "mio": True,
         "sotto": motore.descrizione(spec, vista=vista, tipo=tipo) if spec else "", "tipi": [], "errore": "",
         "serie": {"tipo": tipo, "vuoto": True, "righe": [], "etichette": [], "valori": []}, "pronto": pronto}
    if pronto:
        try:
            w["serie"] = motore.serie_di(finto, motore.dati_di(tipo, spec, request), vista)
        except ErroreInterrogazione as e:
            w["errore"] = str(e)
    return w


def _contesto(request, grafico=None):
    p = parametri_di(request, grafico)
    vista = motore.vista_di({"vista": p.get("vista", "")}, request) if p.get("vista") else None
    opzioni = interroga.opzioni_vista(vista) if vista else {"misure": [("count", "Numero di record")], "raggruppamenti": [], "date": []}
    if vista and p.get("tipo") != Grafico.KPI and not p.get("per") and opzioni["raggruppamenti"]:
        p["per"] = opzioni["raggruppamenti"][0][0]
    if vista and p.get("tipo") in (Grafico.KPI, Grafico.PREVISIONE) and not p.get("data") and opzioni["date"]:
        p["data"] = opzioni["date"][0][0]
    if p.get("tipo") == Grafico.PREVISIONE and p.get("periodo") not in dict(PERIODI_PREVISIONE):
        p["periodo"] = "mese"
    if p.get("misura") not in dict(opzioni["misure"]):
        p["misura"] = "count"
    if not request.GET:                                      # modifica di un grafico: i filtri della lista leggono f_* da GET
        request.GET = QueryDict(urlencode({k: v for k, v in p.items() if k == "q" or k.startswith("f_")}))
    return {"p": p, "vista": vista, "viste": _viste_per_app(request), "opzioni": opzioni, "tipi": tipi_disponibili(),
            "periodi": PERIODI, "periodi_previsione": PERIODI_PREVISIONE, "orizzonti": ORIZZONTI, "massimi": MASSIMI,
            "aggiornamenti": motore.AGGIORNAMENTI, "filtri": filtri_lista.specifiche(vista, request) if vista else [],
            "w": _anteprima(request, p, vista),
            "destinazioni": motore.destinazioni(request, p.get("vista", ""), area=_area_scelta(request, p.get("destinazione", ""))),
            "grafico": grafico, "ai": motore._ai_disponibile(),
            "scheda_attiva": ""}


def _salva(request, grafico=None):
    p = {k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"}
    spec = spec_di(p)
    tipo = p.get("tipo", Grafico.BARRE)
    if tipo not in dict(tipi_disponibili()):
        tipo = Grafico.BARRE
    vista = motore.vista_di(spec, request) if spec else None
    if vista is None:
        messages.error(request, "Scegli una vista che puoi consultare.")
        return None
    try:
        dati = motore.dati_di(tipo, spec, request)
    except ErroreInterrogazione as e:
        messages.error(request, f"Il grafico non si può calcolare: {e}")
        return None
    titolo = (p.get("titolo") or "").strip()[:200] or motore.descrizione(spec, vista=vista, tipo=tipo)[:200]
    if grafico is None:
        grafico = Grafico(utente=request.user, origine=Grafico.COSTRUTTORE)
    grafico.titolo, grafico.tipo, grafico.spec, grafico.dati, grafico.aggiornato = titolo, tipo, spec, dati, timezone.now()
    if str(p.get("aggiorna_ogni", "")).isdigit():
        grafico.aggiorna_ogni = min(int(p["aggiorna_ogni"]), 24 * 30)
    obiettivo = obiettivo_di(p)
    grafico.opzioni = {**{k: v for k, v in (grafico.opzioni or {}).items() if k != "obiettivo"}, **({"obiettivo": obiettivo} if obiettivo else {})}
    nuovo = grafico.pk is None
    grafico.save()
    grafico.dove, grafico.url_dove = _metti(request, grafico, p.get("destinazione"), p.get("titolo_nuova")) if nuovo else (None, None)
    return grafico


@login_required
@permission_required("grafici.add_grafico")
def costruttore(request, pk=None):
    grafico = get_object_or_404(Grafico, pk=pk, utente=request.user) if pk else None
    if request.method == "POST":
        salvato = _salva(request, grafico)
        if salvato is not None:
            messages.success(request, f"Grafico «{salvato.titolo}» aggiornato." if grafico else
                             f"Grafico «{salvato.titolo}» salvato" + (f" in «{salvato.dove}»." if salvato.dove else " in libreria."))
            return redirect(salvato.url_dove) if salvato.url_dove else redirect("grafici:grafico", pk=salvato.pk)
        request.GET = request.POST                       # il form si ripresenta com'era, con l'errore
    return render(request, "grafici/costruttore.html", _contesto(request, grafico))
