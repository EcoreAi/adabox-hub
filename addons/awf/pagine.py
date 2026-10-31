"""Pagine di AWF: stato e collegamento, agenti, operazioni ammesse, approvazioni in attesa.

Non sono `ModelView` di proposito: così non compaiono fra le viste che l'assistente AI (e quindi gli agenti) può
leggere o modificare. L'elenco delle operazioni ammesse si cambia solo da qui, da una persona."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from core import cifratura
from core.models import Azienda

from . import agenti, fabbrica, operazioni, osservazione
from .models import Agente, Approvazione, Chiamata, Collegamento, OperazioneAmmessa

AGGIORNA_DOPO = 60                                      # secondi: all'apertura della pagina, battito se più vecchio
STATI = {"proposed": "proposto", "active": "attivo", "paused": "in pausa", "suspended": "sospeso",
         "uninstalled": "disinstallato", "rejected": "rifiutato"}


def _url_base(request):
    return request.build_absolute_uri("/").rstrip("/")


def _contesto_stato(request, c, **extra):
    ingaggio = c.ingaggio
    console = ingaggio.get("agate_console_url")
    console = console if isinstance(console, str) and console.startswith(("https://", "http://")) else ""
    return {"c": c, "ingaggio": ingaggio, "stato_ingaggio": STATI.get(ingaggio.get("status"), ingaggio.get("status")),
            "console_ingaggio": console, "agenti_ingaggio": [a for a in ingaggio.get("agents") or []
                                                             if isinstance(a, dict)], "bloccato": ingaggio.get("blocked") if isinstance(
                ingaggio.get("blocked"), dict) else None,
            "motivo_osservazione": osservazione.motivo(c), "aziende": Azienda.objects.filter(attiva=True),
            "segreto": bool(c.segreto_webhook_cifrato), "base_url_proposta": c.base_url or _url_base(request),
            "agenti": Agente.objects.select_related("utente").filter(attivo=True),
            "chiamate": Chiamata.objects.select_related("agente")[:20],
            "in_attesa": Approvazione.objects.filter(stato=Approvazione.IN_ATTESA).count(),
            "versione": operazioni.versione(), **extra}


@never_cache
@login_required
@permission_required("awf.change_collegamento", raise_exception=True)
def stato(request):
    c = Collegamento.attuale()
    if request.method == "POST":
        azione = request.POST.get("azione")
        if azione == "collega":
            return _collega(request, c)
        if azione == "rigenera":
            if not c.collegato:
                messages.error(request, "Prima collega l'istanza alla fabbrica.")
                return redirect("awf:stato")
            bearer = fabbrica.rigenera_bearer(c)
            return _mostra_bearer(request, Collegamento.attuale(), bearer)
        if azione == "segreto":
            segreto = request.POST.get("segreto", "").strip()
            c.segreto_webhook_cifrato = cifratura.cifra(segreto)
            c.save(update_fields=["segreto_webhook_cifrato"])
            messages.success(request, "Segreto dei webhook salvato." if segreto else "Segreto dei webhook tolto.")
        elif azione == "impostazioni":
            azienda = Azienda.objects.filter(attiva=True, pk=request.POST.get("azienda") or 0).first()
            c.azienda, c.agate_url = azienda, request.POST.get("agate_url", "").strip()[:200]
            c.save(update_fields=["azienda", "agate_url"])
            if azienda is not None:
                agenti.riallinea_tutti(azienda)
            messages.success(request, "Impostazioni salvate.")
        elif azione == "aggiorna":
            _aggiorna(request, c)
        return redirect("awf:stato")
    if c.collegato and (c.stato_il is None or (timezone.now() - c.stato_il).total_seconds() > AGGIORNA_DOPO):
        _aggiorna(request, c, silenzioso=True)
        c = Collegamento.attuale()
    return render(request, "awf/stato.html", _contesto_stato(request, c))


def _aggiorna(request, c, silenzioso=False):
    try:
        fabbrica.battito()
        if not silenzioso:
            messages.success(request, "Stato dell'ingaggio aggiornato.")
    except fabbrica.ErroreFabbrica as e:
        messages.error(request, f"Battito non riuscito: {e}")


def _collega(request, c):
    azienda = Azienda.objects.filter(attiva=True, pk=request.POST.get("azienda") or 0).first()
    try:
        c, bearer = fabbrica.collega(request.POST.get("codice", ""), request.POST.get("forge_url", ""),
                                     request.POST.get("base_url", ""), azienda)
    except fabbrica.ErroreFabbrica as e:
        messages.error(request, f"Collegamento non riuscito: {e}")
        return redirect("awf:stato")
    messages.success(request, "Collegato alla fabbrica.")
    return _mostra_bearer(request, c, bearer)


def _mostra_bearer(request, c, bearer):
    """Il bearer si vede solo in questa risposta: non va in sessione né nei messaggi, e la pagina non si salva
    nella cache del browser."""
    return render(request, "awf/stato.html", _contesto_stato(request, c, bearer=bearer))


@login_required
@permission_required("awf.view_agente", raise_exception=True)
def elenco_agenti(request):
    return render(request, "awf/agenti.html", {
        "agenti": Agente.objects.select_related("utente").all(),
        "gruppo": agenti.GRUPPO, "permessi": sorted(str(p) for p in operazioni.permessi_derivati()),
        "azienda": Collegamento.attuale().azienda})


@login_required
@permission_required("awf.view_operazioneammessa", raise_exception=True)
def elenco_operazioni(request):
    esponibili = operazioni.esponibili()
    if request.method == "POST":
        _modifica_operazioni(request, esponibili)
        return redirect("awf:operazioni")
    esposte = {e.nome: e for e in operazioni.esposte()}
    voci = [{"voce": o, "strumento": esponibili.get(o.strumento),
             "effetto": esposte[o.strumento].effetto if o.strumento in esposte else None}
            for o in OperazioneAmmessa.objects.all()]
    return render(request, "awf/operazioni.html", {
        "voci": voci, "esposte": list(esposte.values()),
        "strumenti": sorted(esponibili.values(), key=lambda s: (s.rischio != "lettura", s.nome)),
        "viste": sorted(operazioni.viste()),
        "puo_modificare": request.user.has_perm("awf.change_operazioneammessa")})


def _modifica_operazioni(request, esponibili):
    azione = request.POST.get("azione")
    if azione == "aggiungi":
        if not request.user.has_perm("awf.add_operazioneammessa"):
            messages.error(request, "Non hai il permesso di aggiungere operazioni.")
            return
        nome, vista = request.POST.get("strumento", ""), request.POST.get("vista", "").strip()
        strumento = esponibili.get(nome)
        if strumento is None:
            messages.error(request, "Strumento sconosciuto o non ammissibile.")
        elif vista and (not operazioni.ha_vista(strumento) or vista not in operazioni.viste()):
            messages.error(request, "Vista inesistente o non adatta a questo strumento.")
        elif OperazioneAmmessa.objects.filter(strumento=nome, vista=vista).exists():
            messages.error(request, "Questa operazione è già nell'elenco.")
        else:
            OperazioneAmmessa.objects.create(strumento=nome, vista=vista, creato_da=request.user)
            messages.success(request, "Operazione aggiunta. Rimetti gli strumenti in Agate (vedi Stato e "
                                      "collegamento): uno schema cambiato resta in quarantena finché non lo rivedi.")
        return
    voce = OperazioneAmmessa.objects.filter(pk=request.POST.get("pk") or 0).first()
    if voce is None:
        return
    if azione == "alterna" and request.user.has_perm("awf.change_operazioneammessa"):
        voce.attiva = not voce.attiva
        voce.save(update_fields=["attiva"])
        messages.success(request, f"«{voce}» {'attivata' if voce.attiva else 'disattivata'}.")
    elif azione == "elimina" and request.user.has_perm("awf.delete_operazioneammessa"):
        nome = str(voce)
        voce.delete()
        messages.success(request, f"«{nome}» tolta dall'elenco.")
    else:
        messages.error(request, "Non hai il permesso di cambiare l'elenco.")


@login_required
@permission_required("awf.view_approvazione", raise_exception=True)
def elenco_approvazioni(request):
    adesso = timezone.now()
    console = Collegamento.attuale().console_agate()
    attesa = Approvazione.objects.filter(stato=Approvazione.IN_ATTESA)
    return render(request, "awf/approvazioni.html", {
        "in_attesa": [{"a": a, "scaduta": a.scade is not None and a.scade < adesso,
                       "link": f"{console}/console/approvals/{a.approval_id}/" if console else ""} for a in attesa],
        "decise": Approvazione.objects.exclude(stato=Approvazione.IN_ATTESA)[:20], "console": console})
