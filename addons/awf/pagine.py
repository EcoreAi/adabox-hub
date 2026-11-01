"""Pagine di AWF: stato e collegamento, catalogo e richieste di squadre, agenti, operazioni ammesse, approvazioni in
attesa.

Non sono `ModelView` di proposito: così non compaiono fra le viste che l'assistente AI (e quindi gli agenti) può
leggere o modificare. L'elenco delle operazioni ammesse si cambia solo da qui, da una persona."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from core import cifratura
from core.models import Azienda

from . import agenti, fabbrica, operazioni, osservazione, squadre
from .models import Agente, Approvazione, Chiamata, Collegamento, OperazioneAmmessa, RichiestaAgenti

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


# ---------- catalogo e richieste di squadre (§7 del contratto) ----------

@never_cache
@login_required
@permission_required("awf.change_collegamento", raise_exception=True)
def catalogo(request):
    c = Collegamento.attuale()
    if request.method == "POST":
        azione = request.POST.get("azione")
        if azione == "fabbrica":
            _imposta_fabbrica(request, c)
        elif azione == "richiedi":
            return _richiedi(request)
        return redirect("awf:catalogo")
    reparto = request.GET.get("reparto", "").strip().lower()[:60]
    forge, gruppi, errore = fabbrica.indirizzo_fabbrica(), [], ""
    if forge:
        try:
            gruppi = squadre.per_reparto(fabbrica.catalogo(reparto))
        except fabbrica.ErroreFabbrica as e:
            errore = str(e)
    return render(request, "awf/catalogo.html", {
        "c": c, "forge": forge, "gruppi": gruppi, "errore": errore, "reparto": reparto, "passi": squadre.PASSI,
        "aperte": RichiestaAgenti.objects.filter(stato__in=RichiestaAgenti.APERTE).count(),
        "base_url_proposta": c.base_url or _url_base(request)})


def _imposta_fabbrica(request, c):
    if c.collegato:
        messages.error(request, "Istanza già collegata: l'indirizzo della fabbrica è quello del collegamento.")
        return
    try:
        c.forge_url = fabbrica.controlla_url(request.POST.get("forge_url", ""), "della fabbrica")
    except fabbrica.ErroreFabbrica as e:
        messages.error(request, str(e)[:1].upper() + str(e)[1:] + ".")
        return
    c.save(update_fields=["forge_url"])
    messages.success(request, "Indirizzo della fabbrica salvato.")


def _richiedi(request):
    try:
        r = fabbrica.richiedi(request.POST.get("team", ""), request.POST.get("versione"),
                              request.POST.get("settimane"), request.POST.get("note", ""), request.user,
                              getattr(request, "azienda", None), base_url=request.POST.get("base_url", "").strip())
    except fabbrica.ErroreFabbrica as e:
        messages.error(request, f"Richiesta non inviata: {e}.")
        return redirect("awf:catalogo")
    messages.success(request, f"Richiesta per «{r.team_nome}» inviata ad Agentlia. Ora prepara adabox per la squadra "
                              "(i due passi qui sotto); quando il contratto è pronto lo approvate nella console di "
                              "Agate e adabox si collega da solo.")
    return redirect("awf:richieste")


@never_cache
@login_required
@permission_required("awf.change_collegamento", raise_exception=True)
def richieste(request):
    if request.method == "POST":
        r = RichiestaAgenti.objects.filter(pk=request.POST.get("pk") or 0).first()
        if r is None:
            messages.error(request, "Richiesta inesistente.")
            return redirect("awf:richieste")
        azione = request.POST.get("azione")
        if azione == "bearer":
            return _bearer_per_agate(request, r)
        try:
            if azione == "ritira":
                fabbrica.ritira(r)
                messages.success(request, f"Richiesta per «{r.team_nome}» ritirata.")
            elif azione == "aggiorna":
                fabbrica.aggiorna(r)
                messages.success(request, "Stato della richiesta aggiornato.")
            elif azione == "ammetti":
                _ammetti(request, r)
        except fabbrica.ErroreFabbrica as e:
            messages.error(request, f"{str(e)[:1].upper()}{str(e)[1:]}.")
        return redirect("awf:richieste")
    errori = fabbrica.aggiorna_aperte(piu_vecchie_di=AGGIORNA_DOPO)
    return _pagina_richieste(request, errori=errori)


IN_CORSO = (RichiestaAgenti.INVIATA, RichiestaAgenti.DA_APPROVARE, RichiestaAgenti.COLLEGATA)


def _ammetti(request, r):
    if r.stato not in IN_CORSO:
        messages.error(request, "La richiesta è chiusa: le sue operazioni non si ammettono più da qui.")
        return
    righe = squadre.ammetti(r, request.user)
    nuove = [x for x in righe if x["stato"] == squadre.DA_AMMETTERE]
    assenti = [x for x in righe if x["stato"] == squadre.NON_DISPONIBILE]
    if Collegamento.attuale().collegato:
        try:
            fabbrica.battito()                          # la versione dichiarata cambia con l'elenco
        except fabbrica.ErroreFabbrica:
            pass
    testo = f"Operazioni ammesse: {len(nuove)} aggiunt{'a' if len(nuove) == 1 else 'e'}" if nuove else \
        "Le operazioni della squadra erano già tutte ammesse"
    if assenti:
        testo += f"; {len(assenti)} non disponibil{'e' if len(assenti) == 1 else 'i'} in questa istanza"
    messages.success(request, testo + ". Gli agenti hanno i permessi che servono; se Agate aveva già importato gli "
                                      "strumenti, reimportali.")


def _bearer_per_agate(request, r):
    """Il bearer si vede solo in questa risposta, come in «Stato e collegamento»."""
    c = Collegamento.attuale()
    if r.stato not in IN_CORSO:
        messages.error(request, "La richiesta è chiusa: non serve collegare adabox in Agate per questa squadra.")
        return redirect("awf:richieste")
    bearer = fabbrica.rigenera_bearer(c)
    return _pagina_richieste(request, bearer=bearer)


def _tappe(r):
    """La linea del tempo della richiesta: [(etichetta, fatto | attuale | futuro | errore | chiuso)]."""
    if r.stato == RichiestaAgenti.RITIRATA:
        return [("Inviata", "fatto"), ("Ritirata", "chiuso")]
    if r.stato == RichiestaAgenti.RIFIUTATA:
        return [("Inviata", "fatto"), ("Rifiutata", "errore")]
    ordine = [RichiestaAgenti.INVIATA, RichiestaAgenti.DA_APPROVARE, RichiestaAgenti.COLLEGATA]
    attuale = ordine.index(r.stato)
    if r.collegata_il is not None:
        attuale += 1
    return [(etichetta, "fatto" if n < attuale else "attuale" if n == attuale else "futuro")
            for n, etichetta in enumerate(["Inviata", "Da approvare in Agate", "Collegata"])]


def _pagina_richieste(request, **extra):
    c = Collegamento.attuale()
    elenco = list(RichiestaAgenti.objects.select_related("creata_da")[:50])
    # i passi per preparare adabox valgono per la richiesta più recente in corso (o collegata): servono già prima
    # della proposta, perché Agate accetta il contratto solo con gli strumenti della squadra attivi
    ultima = next((r for r in elenco if r.stato in IN_CORSO), None)
    voci = [{"r": r, "tappe": _tappe(r), "prossimo": squadre.prossimo_passo(r, c),
             "operazioni": squadre.stato_operazioni(r) if r is ultima else None} for r in elenco]
    for v in voci:
        if v["operazioni"] is not None:
            v["da_ammettere"] = any(x["stato"] == squadre.DA_AMMETTERE for x in v["operazioni"])
    return render(request, "awf/richieste.html", {"voci": voci, "c": c, **extra})
