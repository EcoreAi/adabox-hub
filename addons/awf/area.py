"""L'area «Agenti AI» (dal menu del profilo, per chi gestisce AWF): Negozio, scheda dell'agente, «Assumi» su una
pagina sola (Conferma con la password), la pagina della richiesta che si aggiorna da sola fino a «Il tuo agente è al
lavoro», Richieste (come un ordine da seguire), I miei agenti, Da approvare (la pagina del modulo `agate`) e Avanzate
(le pagine tecniche).

Come le altre pagine di AWF non sono `ModelView`: non compaiono fra le viste che l'assistente (e gli agenti) può
leggere o modificare."""
import math

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache

from . import assunzione, contratto, fabbrica, operazioni, squadre
from .models import Agente, Approvazione, Chiamata, Collegamento, RichiestaAgenti

PERMESSO = "awf.change_collegamento"
AGGIORNA_DOPO = 60                                      # secondi: all'apertura della pagina, stato se più vecchio
AGGIORNA_SUBITO = 3                                     # secondi: la pagina della richiesta, mentre si prepara
RICARICA, RICARICA_PERSONE = 5, 30                      # secondi: passi automatici; in attesa di persone
SCHEDE = [("negozio", "Negozio", "awf:negozio"), ("miei", "I miei agenti", "awf:miei"),
          ("richieste", "Richieste", "awf:richieste"), ("avanzate", "Avanzate", "awf:avanzate")]
IN_CORSO = (RichiestaAgenti.INVIATA, RichiestaAgenti.DA_APPROVARE, RichiestaAgenti.COLLEGATA)
PROVA, LAVORO, PAUSA, CONCLUSO = "prova", "lavoro", "pausa", "concluso"
FASI = {PROVA: ("in prova", "ui-pill-info"), LAVORO: ("al lavoro", "ui-pill-ok"), PAUSA: ("in pausa", "ui-pill-warn"),
        CONCLUSO: ("scaduto", "ui-pill-neutral")}


def agate_attivo():
    from core.registry.modules import disattivati
    return "agate" in settings.ADDONS_ATTIVI and "agate" not in disattivati()


def da_approvare_url():
    """«Da approvare» (pagina del modulo agate) vista dall'area Agenti AI, se il modulo c'è."""
    return f"{reverse('agate:da_approvare')}?da=awf" if agate_attivo() else ""


def schede(request, attiva):
    """Le schede dell'area nella barra dell'app (la stessa delle app con la voce in alto)."""
    impostazioni = f"{reverse('core:impostazioni')}#awf" if request.user.has_perm("core.change_parametro") else None
    voci = [{"label": etichetta, "url": reverse(nome), "attiva": chiave == attiva}
            for chiave, etichetta, nome in SCHEDE]
    if url := da_approvare_url():
        voci.insert(3, {"label": "Da approvare", "url": url, "attiva": attiva == "da_approvare"})
    return {"app_corrente": {"slug": "awf", "label": "Agenti AI", "url": reverse("awf:negozio"),
                             "settings_url": impostazioni},
            "menu_app": voci}


def configura_url():
    """Dove si fa il passaggio una volta sola: il Controllo AI con un codice, o (senza il modulo) Avanzate."""
    return reverse("agate:impostazioni") if agate_attivo() else f"{reverse('awf:avanzate')}#agate"


def pronto():
    """Il percorso semplice è pronto: il Controllo AI collegato con un codice (o, senza il modulo agate, il passaggio
    tecnico già fatto in Avanzate)."""
    if agate_attivo():
        return contratto.garante() is not None
    return bool(Collegamento.attuale().mcp_impronta)


def incluso_possibile():
    """Agate incluso (§8.6): il Controllo AI c'è ma l'azienda non ha ancora un Agate (nessun indirizzo salvato, nemmeno
    a mano), e la fabbrica non ha appena detto che il servizio non c'è. Allora la conferma lo attiva da sola."""
    if not agate_attivo() or pronto():
        return False
    try:
        from agate.models import Collegamento as CollegamentoAgate
        a = CollegamentoAgate.attuale()
    except Exception:                                   # modulo non migrato o rotto: il percorso di prima
        return False
    return (a is None or not a.gateway_url) and fabbrica.incluso_disponibile()


PASSI_INCLUSO = ["Apriamo il vostro Agate…", "Colleghiamo adabox…", "Chiediamo il contratto…"]


def passi_incluso(fatti, errore=False):
    """[(testo, fatto | attuale | errore | futuro)]: i primi `fatti` riusciti, il seguente in corso (o non riuscito)."""
    return [(t, "fatto" if n < fatti else ("errore" if errore else "attuale") if n == fatti else "futuro")
            for n, t in enumerate(PASSI_INCLUSO)]


def _email_sbagliata(email):
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email
    try:
        validate_email(email)
    except ValidationError:
        return True
    return False


def _url_base(request):
    return request.build_absolute_uri("/").rstrip("/")


def _maiuscola(testo):
    return testo[:1].upper() + testo[1:]


def fase(c=None):
    """La fase del contratto collegato, dall'ultimo stato ricevuto: in prova, al lavoro, in pausa, scaduto."""
    c = c or Collegamento.attuale()
    ingaggio = c.ingaggio
    stato = ingaggio.get("status")
    if ingaggio.get("blocked") or stato == "paused":
        return PAUSA
    if stato in ("suspended", "uninstalled", "rejected"):
        return CONCLUSO
    grezzo = ingaggio.get("observe_until")
    try:
        fino = parse_datetime(grezzo) if isinstance(grezzo, str) else None
    except ValueError:
        fino = None
    if fino is not None and timezone.is_naive(fino):
        fino = timezone.make_aware(fino)
    if (fino is not None and fino > timezone.now()) or stato == "proposed":
        return PROVA
    return LAVORO


def _console(c):
    link = c.ingaggio.get("agate_console_url")
    return link if isinstance(link, str) and link.startswith(("https://", "http://")) else ""


def _squadra_o_404(slug):
    try:
        s = fabbrica.squadra(slug)
    except fabbrica.ErroreFabbrica:
        s = None
    if s is None:
        raise Http404("Agente non più nel negozio")
    return squadre.descrivi(s)


# ---------- Negozio ----------

@never_cache
@login_required
@permission_required(PERMESSO, raise_exception=True)
def negozio(request):
    c = Collegamento.attuale()
    if request.method == "POST":
        _imposta_fabbrica(request, c)
        return redirect("awf:negozio")
    forge, elenco, errore = fabbrica.indirizzo_fabbrica(), [], ""
    if forge:
        try:
            elenco = fabbrica.catalogo()
        except fabbrica.ErroreFabbrica as e:
            errore = str(e)
    tutte = operazioni.viste()
    descritte = [squadre.descrivi(s, tutte) for s in elenco]
    reparto = request.GET.get("reparto", "").strip().lower()[:60]
    reparti = sorted({s["reparto"] for s in descritte}, key=squadre.nome_reparto)
    return render(request, "awf/negozio.html", {
        **schede(request, "negozio"), "c": c, "forge": forge, "errore": errore, "reparto": reparto,
        "reparti": [(r, squadre.nome_reparto(r)) for r in reparti],
        "squadre": [s for s in descritte if not reparto or s["reparto"] == reparto],
        "aperte": RichiestaAgenti.objects.filter(stato__in=RichiestaAgenti.APERTE).count()})


def _imposta_fabbrica(request, c):
    if c.collegato:
        messages.error(request, "adabox è già collegato: l'indirizzo è quello del contratto in corso.")
        return
    try:
        c.forge_url = fabbrica.controlla_url(request.POST.get("forge_url", ""), "del negozio")
    except fabbrica.ErroreFabbrica as e:
        messages.error(request, _maiuscola(str(e)) + ".")
        return
    c.save(update_fields=["forge_url"])
    messages.success(request, "Indirizzo salvato: ecco gli agenti del negozio.")


# ---------- Scheda dell'agente ----------

DOMANDE_BASE = [
    {"domanda": "Chi decide cosa può fare?",
     "risposta": "Tu. Prima di inviare la richiesta scegli, per ogni azione, «Sì», «Con il tuo ok» o «Mai»; puoi "
                 "cambiarlo quando vuoi da I miei agenti."},
    {"domanda": "Cosa succede nei giorni di prova?",
     "risposta": "L'agente legge e prepara il lavoro, ma non cambia nulla: le modifiche si registrano soltanto, così "
                 "vedi cosa farebbe prima di lasciarlo lavorare davvero."},
    {"domanda": "Posso fermarlo?",
     "risposta": "Sì, quando vuoi: metterlo in pausa, rinnovarlo o disdirlo si decide in Agate, il garante che "
                 "controlla ogni sua azione."}]
MAI_BASE = ["Non entra in adabox come una persona: niente accesso alle pagine, niente password",
            "Non fa nulla oltre a quello che scegli in «Cosa può fare»"]


def _settimane(valore, altrimenti=4):
    try:
        n = int(valore)
    except (TypeError, ValueError):
        return altrimenti
    return min(max(n, 1), 52)


def costo(s, settimane):
    """Il costo in parole per la scheda e il riepilogo: fisso stimato e i modelli AI (chi li paga, il credito a prezzo
    e a costo: `squadre.modelli_ai`)."""
    p = s["prezzo"]
    stima = squadre.stima(p, settimane)
    m = squadre.modelli_ai(p)
    periodo, giorni = squadre.decimale(p.get("period_eur")), squadre.decimale(p.get("period_days"))
    return {"stima": squadre.euro(stima) if stima is not None else "",
            "periodo": squadre.euro(periodo) if periodo else "", "giorni": squadre.numero(giorni) if giorni else "",
            "consumo": m["breve"], "credito": m["credito"], "spiega": m["spiega"]}


@login_required
@permission_required(PERMESSO, raise_exception=True)
def scheda(request, slug):
    s = _squadra_o_404(slug)
    righe = squadre.righe_operazioni(s["operazioni"])
    settimane = _settimane(request.GET.get("settimane"))
    return render(request, "awf/scheda.html", {
        **schede(request, "negozio"), "s": s, "settimane": settimane, "costo": costo(s, settimane),
        "puo": [x for x in righe if x["stato"] != squadre.NON_DISPONIBILE],
        "mai": [*s["mai"], *MAI_BASE], "domande": s["domande"] or DOMANDE_BASE,
        "viste": squadre.viste_lette(s["operazioni"]), "app_mancanti": squadre.app_mancanti(righe),
        "non_qui": [x for x in righe if x["stato"] == squadre.NON_DISPONIBILE and not x["app_mancante"]]})


# ---------- Assumi: una pagina sola, già compilata ----------

def leggi_scelte(dati, righe, utente):
    """Legge i campi della pagina (tutti facoltativi: mancano → valori proposti). Restituisce (scelte, errori).
    Serve anche a «Cambia persone»."""
    errori = []
    try:
        settimane = int(dati.get("settimane") or assunzione.SETTIMANE)
    except ValueError:
        settimane = 0
    if not 1 <= settimane <= 52:
        errori.append("Per quante settimane? Un numero da 1 a 52.")
    note = dati.get("note", "").strip()
    if len(note) > assunzione.MAX_NOTE:
        errori.append(f"Le note sono troppo lunghe: al massimo {assunzione.MAX_NOTE} caratteri.")
    reparto = dati.get("reparto", "").strip()
    if len(reparto) > 80:
        errori.append("Il nome del reparto è troppo lungo: al massimo 80 caratteri.")
    possibili = set(assunzione.persone_possibili().values_list("pk", flat=True))
    grezzo = dati.get("responsabile") or str(utente.pk)
    responsabile = int(grezzo) if grezzo.isdigit() else None
    if responsabile not in possibili:
        errori.append("Scegli chi segue gli agenti (il responsabile).")
    persone = sorted({int(p) for p in dati.getlist("persone") if p.isdigit() and int(p) in possibili})
    return {"settimane": settimane, "note": note, "reparto": reparto, "responsabile": responsabile,
            "persone": persone, "base_url": dati.get("base_url", "").strip()[:200],
            "scelte": squadre.scelte(righe, {x["chiave"]: dati.get(f"op-{n}") for n, x in enumerate(righe)})}, errori


@never_cache
@login_required
@permission_required(PERMESSO, raise_exception=True)
def assumi(request, slug):
    """La cassa: tutto già scelto con valori prudenti, un bottone «Conferma»; chi vuole apre «Personalizza»."""
    s = _squadra_o_404(slug)
    righe = squadre.righe_operazioni(s["operazioni"])
    if request.method != "POST":
        b = {"settimane": assunzione.SETTIMANE, "note": "", "reparto": "", "responsabile": request.user.pk,
             "persone": [], "base_url": "", "scelte": squadre.scelte(righe)}
        return _pagina_assumi(request, s, b, righe, [])
    b, errori = leggi_scelte(request.POST, righe, request.user)
    incluso = incluso_possibile()
    b["email"] = request.POST.get("email", "").strip()[:254] if incluso and not request.user.email else ""
    if incluso and not request.user.email and _email_sbagliata(b["email"]):
        errori.append("Scrivi la tua email: lì arriva l'invito al Controllo AI (Agate).")
    if errori:
        return _pagina_assumi(request, s, b, righe, errori)
    if not request.user.check_password(request.POST.get("password", "")):
        return _pagina_assumi(request, s, b, righe, [], password_sbagliata=True)
    utenti = {u.pk: u for u in assunzione.persone_possibili()}
    azienda = getattr(request, "azienda", None)
    attivato, non_incluso = False, ""
    if incluso:                                         # Agate incluso (§8.6): apri, collega, poi la richiesta
        try:
            assunzione.includi_agate(request.user, azienda, b["base_url"] or Collegamento.attuale().base_url
                                     or _url_base(request), email=b["email"])
        except assunzione.InclusoNonDisponibile as e:
            non_incluso = str(e)                        # come prima: la richiesta parte, poi il codice a mano
        except assunzione.ErroreIncluso as e:
            return _pagina_assumi(request, s, b, righe, [], incluso_errore=e)
        else:
            attivato = True
    consenso = contratto.consenso(request.user, s["slug"], s["versione"], b["settimane"], s.get("tetti"),
                                  s["prezzo"], s["giorni_prova"])
    if attivato:
        consenso["agate_incluso"] = True
    try:
        r = assunzione.invia(s["slug"], s["versione"], b["settimane"], b["note"], request.user, azienda,
                             base_url=b["base_url"], scelte=b["scelte"], reparto=b["reparto"],
                             responsabile=utenti.get(b["responsabile"]),
                             persone=[utenti[p] for p in b["persone"] if p in utenti], consenso=consenso)
    except fabbrica.ErroreFabbrica as e:
        if attivato:
            return _pagina_assumi(request, s, b, righe, [f"Il Controllo AI è attivo ✓, ma la richiesta non è partita: "
                                                         f"{e}. Puoi riprovare."])
        return _pagina_assumi(request, s, b, righe, [f"Richiesta non inviata: {e}. Non è cambiato nulla."])
    if attivato:
        messages.success(request, f"Il Controllo AI (Agate) è attivo ✓: riceverai un invito a {request.user.email} "
                                  "per vedere il registro quando vuoi.")
    elif non_incluso:
        messages.warning(request, f"{_maiuscola(non_incluso)}: per questa volta il Controllo AI (Agate) non si attiva "
                                  "da solo. La richiesta è partita; per farla proseguire collega il Controllo AI con "
                                  "un codice di Agate.")
    return redirect("awf:richiesta", r.pk)


def _pagina_assumi(request, s, b, righe, errori, password_sbagliata=False, incluso_errore=None):
    utenti = list(assunzione.persone_possibili())
    per_pk = {u.pk: u for u in utenti}
    scelte = b["scelte"]
    disponibili = [x for x in righe if x["stato"] != squadre.NON_DISPONIBILE]
    gruppi = [(titolo, spiegazione, [x["parole"] for x in disponibili if scelte[x["chiave"]] == valore])
              for valore, titolo, spiegazione in ((squadre.SI, "Sì", "lo fa da solo"),
                                                  (squadre.OK, "Con il tuo ok", "prima chiede a una persona"),
                                                  (squadre.MAI, "Mai", "non lo farà"))]
    c = Collegamento.attuale()
    personalizzato = bool(errori) or b["settimane"] != assunzione.SETTIMANE or bool(b["note"] or b["reparto"]
                                                                                    or b["persone"])
    return render(request, "awf/assumi.html", {
        **schede(request, "negozio"), "s": s, "b": b, "errori": errori, "aperto": personalizzato,
        "righe": [{**x, "scelta": scelte[x["chiave"]]} for x in righe], "scelte_possibili": RichiestaAgenti.SCELTE,
        "utenti": utenti, "reparti": assunzione.reparti_suggeriti(getattr(request, "azienda", None)),
        "responsabile": per_pk.get(b["responsabile"]), "persone": [per_pk[p] for p in b["persone"] if p in per_pk],
        "costo": costo(s, b["settimane"]), "gruppi": gruppi, "con_ok": len(gruppi[1][2]),
        "app_mancanti": squadre.app_mancanti(righe), "c": c,
        "base_url_proposta": b["base_url"] or c.base_url or _url_base(request),
        "password_sbagliata": password_sbagliata, "tetti": contratto.tetti_in_parole(s.get("tetti"), s["prezzo"]),
        "pronto": pronto(), "configura": configura_url(), "agate": agate_attivo(),
        "incluso": incluso_possibile(), "incluso_errore": incluso_errore, "chiedi_email": not request.user.email,
        "passi_avvio": passi_incluso(0),
        "passi_errore": passi_incluso(0 if incluso_errore.passo == assunzione.APRI else 1, errore=True)
        if incluso_errore else []})


# ---------- Richieste: il contratto passo per passo ----------

TAPPE = ["Richiesta inviata", "Contratto pronto", "Periodo di prova", "Al lavoro"]


def _tappe(r, ultima, f):
    """[(etichetta, fatto | attuale | futuro | errore | chiuso)] della richiesta."""
    if r.stato == RichiestaAgenti.RITIRATA:
        return [("Richiesta inviata", "fatto"), ("Ritirata", "chiuso")]
    if r.stato == RichiestaAgenti.RIFIUTATA:
        return [("Richiesta inviata", "fatto"), ("Rifiutata", "errore")]
    if r.stato == RichiestaAgenti.COLLEGATA and r.collegata_il is not None and r != ultima:
        return [("Richiesta inviata", "fatto"), ("Contratto pronto", "fatto"),
                ("Sostituita da una più recente", "chiuso")]
    etichette = list(TAPPE)
    if r.stato == RichiestaAgenti.INVIATA:
        attuale = 0
    elif r.stato == RichiestaAgenti.DA_APPROVARE or r.collegata_il is None:
        attuale = 1
    else:
        attuale = 2 if f == PROVA else 3
        if f in (PAUSA, CONCLUSO):
            etichette[3] = "In pausa" if f == PAUSA else "Concluso"
    return [(e, "fatto" if n < attuale else "attuale" if n == attuale else "futuro") for n, e in enumerate(etichette)]


def _azione(r, c, ultima):
    """L'unica azione che serve ora: {etichetta, link, esterno, titolo, perche}, o None."""
    if r.stato not in IN_CORSO or (r.stato == RichiestaAgenti.COLLEGATA and r.collegata_il and r != ultima):
        return None
    if not c.mcp_impronta and agate_attivo():
        return {"etichetta": "Collega il Controllo AI", "link": configura_url(), "esterno": False,
                "titolo": "Un passaggio da fare una volta sola.",
                "perche": "Serve perché gli agenti possano lavorare in adabox sotto le regole dell'azienda: incolli "
                          "un codice e al resto pensa adabox."}
    if not c.mcp_impronta:
        return {"etichetta": "Collega adabox ad Agate", "link": f"{reverse('awf:avanzate')}#agate", "esterno": False,
                "titolo": "Collega adabox ad Agate (una volta sola).",
                "perche": "Serve perché gli agenti possano lavorare in adabox: un indirizzo e una chiave per il "
                          "garante che li controlla."}
    if r.stato == RichiestaAgenti.DA_APPROVARE and r.decisione == RichiestaAgenti.DA_CONFERMARE:
        return {"etichetta": "Rivedi e conferma il contratto", "link": reverse("awf:richiesta", args=[r.pk]),
                "esterno": False, "perche": "Il contratto proposto è diverso da quello che hai confermato: guarda "
                                            "cosa è cambiato e confermalo con la tua password."}
    if r.stato in (RichiestaAgenti.INVIATA, RichiestaAgenti.DA_APPROVARE) and contratto.garante() is not None:
        return {"etichetta": "Segui", "link": reverse("awf:richiesta", args=[r.pk]), "esterno": False}
    if r.stato == RichiestaAgenti.DA_APPROVARE and r.approve_url:
        return {"etichetta": "Conferma il contratto", "link": r.approve_url, "esterno": True,
                "perche": "Si apre la pagina del garante che controlla gli agenti: una conferma e il contratto parte."}
    if r.stato == RichiestaAgenti.COLLEGATA and r.collegata_il is None:
        return {"etichetta": "Collega con il codice di Agentlia", "link": reverse("awf:stato"), "esterno": False,
                "perche": "Il collegamento non è arrivato da solo: chiedi ad Agentlia un codice e incollalo qui."}
    if r.stato == RichiestaAgenti.COLLEGATA:
        return {"etichetta": "Vedi i tuoi agenti", "link": reverse("awf:miei"), "esterno": False}
    return None


@never_cache
@login_required
@permission_required(PERMESSO, raise_exception=True)
def richieste(request):
    if request.method == "POST":
        r = RichiestaAgenti.objects.filter(pk=request.POST.get("pk") or 0).first()
        if r is None:
            messages.error(request, "Richiesta inesistente.")
            return redirect("awf:richieste")
        try:
            if request.POST.get("azione") == "ritira":
                fabbrica.ritira(r)
                messages.success(request, f"Richiesta per «{r.team_nome}» ritirata.")
            elif request.POST.get("azione") == "aggiorna":
                fabbrica.aggiorna(r)
                messages.success(request, "Stato della richiesta aggiornato.")
        except fabbrica.ErroreFabbrica as e:
            messages.error(request, f"{_maiuscola(str(e))}.")
        return redirect("awf:richieste")
    errori = fabbrica.aggiorna_aperte(piu_vecchie_di=AGGIORNA_DOPO)
    c = Collegamento.attuale()
    elenco = list(RichiestaAgenti.objects.select_related("creata_da", "responsabile").prefetch_related("persone")[:50])
    ultima = max((r for r in elenco if r.collegata_il), key=lambda r: r.collegata_il, default=None)
    f = fase(c) if c.collegato else PROVA
    voci = [{"r": r, "tappe": _tappe(r, ultima, f), "azione": _azione(r, c, ultima),
             "prossimo": squadre.prossimo_passo(r, c)} for r in elenco]
    return render(request, "awf/richieste.html", {**schede(request, "richieste"), "voci": voci, "c": c,
                                                  "errori": errori})


# ---------- la richiesta: dalla conferma a «al lavoro», da sola ----------

def giorni_di_prova(c, r):
    """I giorni di prova che restano (dall'ultimo stato del contratto), o quelli previsti."""
    grezzo = c.ingaggio.get("observe_until")
    try:
        fino = parse_datetime(grezzo) if isinstance(grezzo, str) else None
    except ValueError:
        fino = None
    if fino is not None:
        if timezone.is_naive(fino):
            fino = timezone.make_aware(fino)
        return max(math.ceil((fino - timezone.now()).total_seconds() / 86400), 0)
    return int((r.consenso or {}).get("giorni_prova") or (r.proposta or {}).get("observe_days") or 0)


def avanzamento(r, c):
    """Dove è la richiesta, per la persona: {titolo, testo, pill, ricarica (secondi, 0 = no), azione, conferma}."""
    R = RichiestaAgenti
    nome = (r.consenso or {}).get("nome") or "chi l'ha confermato"
    preparando = "Stiamo preparando il tuo agente…"
    if r.stato == R.RITIRATA:
        return {"titolo": "Richiesta ritirata", "testo": r.messaggio, "pill": "ui-pill-neutral", "ricarica": 0}
    if r.stato == R.RIFIUTATA:
        return {"titolo": "Non è andata a buon fine", "testo": r.messaggio or "La richiesta è stata rifiutata.",
                "pill": "ui-pill-danger", "ricarica": 0}
    if r.stato == R.COLLEGATA and r.collegata_il is None:
        return {"titolo": "Manca un ultimo passaggio", "testo": r.messaggio, "pill": "ui-pill-warn", "ricarica": 0,
                "azione": {"etichetta": "Collega con il codice di Agentlia", "link": reverse("awf:stato")}}
    if r.stato == R.COLLEGATA:
        prova = fase(c) == PROVA if c.collegato else False
        giorni = giorni_di_prova(c, r) if prova else 0
        titolo = "Il tuo agente è al lavoro" + (f" (in prova per {giorni} giorn{'o' if giorni == 1 else 'i'})"
                                                if prova and giorni else " (in prova)" if prova else "")
        return {"titolo": titolo + " ✓", "pill": "ui-pill-ok", "ricarica": 0, "fatto": True,
                "testo": ("Nei giorni di prova legge e prepara, ma non cambia nulla: le modifiche si registrano "
                          "soltanto." if prova else "Trovi quello che fa ogni giorno in I miei agenti."),
                "azione": {"etichetta": "Vedi i tuoi agenti", "link": reverse("awf:miei")}}
    if not pronto():
        return {"titolo": "Manca un passaggio, una volta sola", "pill": "ui-pill-warn", "ricarica": 0,
                "testo": "Collega il Controllo AI: incolli un codice e al resto pensa adabox. Poi il contratto parte "
                         "da solo.", "azione": {"etichetta": "Collega il Controllo AI", "link": configura_url()}}
    if r.stato == R.INVIATA:
        return {"titolo": preparando, "pill": "ui-pill-info", "ricarica": RICARICA,
                "testo": r.messaggio or "Agentlia prepara il contratto con quello che hai confermato: di solito ci "
                                        "vuole un minuto."}
    garante = contratto.garante()
    if garante is None:                                 # collegato a mano: il contratto si conferma in Agate
        return {"titolo": "Il contratto è pronto", "pill": "ui-pill-info", "ricarica": 0,
                "testo": "Si apre la pagina del garante che controlla gli agenti: una conferma e il contratto parte.",
                "azione": {"etichetta": "Conferma il contratto", "link": r.approve_url, "esterno": True}
                if r.approve_url else None}
    if r.decisione == R.IN_CONFERMA:
        return {"titolo": "Manca la conferma dei responsabili", "pill": "ui-pill-warn", "ricarica": RICARICA_PERSONE,
                "testo": "Abbiamo mandato un'email di conferma ai responsabili: il contratto parte appena "
                         "confermano."}
    if r.decisione == R.DA_CONFERMARE:
        return {"titolo": "Il contratto è cambiato: confermalo tu", "pill": "ui-pill-warn", "ricarica": 0,
                "testo": "Agentlia ha proposto un contratto diverso da quello che hai confermato:",
                "conferma": {"differenze": contratto.differenze(r.consenso, r.proposta),
                             "settimane": r.proposta.get("weeks"),
                             "tetti": contratto.tetti_in_parole(r.proposta.get("caps"), r.proposta.get("price") or {}),
                             "prezzo": squadre.prezzo(r.proposta.get("price") or {})}}
    if r.decisione == R.RIFIUTATA_QUI:
        return {"titolo": "Contratto rifiutato", "pill": "ui-pill-neutral", "ricarica": RICARICA_PERSONE,
                "testo": "Hai rifiutato il contratto in adabox: non parte nulla."}
    if r.decisione == R.APPROVATA:
        return {"titolo": preparando, "pill": "ui-pill-info", "ricarica": RICARICA,
                "testo": f"Contratto confermato a nome di {nome}: stiamo collegando l'agente."}
    if r.decisione == R.ERRORE:
        return {"titolo": preparando, "pill": "ui-pill-info", "ricarica": RICARICA,
                "testo": "La conferma del contratto non è ancora arrivata a destinazione: riproviamo da soli."}
    return {"titolo": preparando, "pill": "ui-pill-info", "ricarica": RICARICA,
            "testo": "Il contratto è pronto: lo stiamo confermando con quello che hai scelto."}


@never_cache
@login_required
@permission_required(PERMESSO, raise_exception=True)
def richiesta(request, pk):
    """La pagina dopo «Conferma»: si ricarica da sola ogni pochi secondi mentre adabox e Agentlia preparano l'agente
    (e a ogni ricarica legge lo stato dalla fabbrica), finché diventa «Il tuo agente è al lavoro»."""
    r = get_object_or_404(RichiestaAgenti, pk=pk)
    if request.method == "POST":
        azione = request.POST.get("azione")
        try:
            if azione == "conferma":
                if not request.user.check_password(request.POST.get("password", "")):
                    messages.error(request, "Password sbagliata: riscrivila per confermare il contratto. Non è "
                                            "cambiato nulla.")
                else:
                    r = contratto.conferma(r, request.user)
                    if r.decisione == RichiestaAgenti.ERRORE:
                        messages.error(request, "La conferma non è arrivata a destinazione: riproviamo da soli.")
                    else:
                        messages.success(request, "Contratto confermato a tuo nome.")
            elif azione == "rifiuta":
                contratto.rifiuta(r, request.user, request.POST.get("motivo", ""))
                messages.success(request, "Contratto rifiutato: non parte nulla.")
            elif azione == "ritira":
                fabbrica.ritira(r)
                messages.success(request, "Richiesta ritirata.")
        except (ValueError, fabbrica.ErroreFabbrica) as e:
            messages.error(request, f"{_maiuscola(str(e))}.")
        return redirect("awf:richiesta", r.pk)
    errore = ""
    vecchia = r.letta_il is None or (timezone.now() - r.letta_il).total_seconds() >= AGGIORNA_SUBITO
    if r.aperta and vecchia:
        try:
            r = fabbrica.aggiorna(r)
        except fabbrica.ErroreFabbrica as e:
            errore = str(e)
    c = Collegamento.attuale()
    elenco = list(RichiestaAgenti.objects.filter(collegata_il__isnull=False).order_by("-collegata_il")[:1])
    ultima = elenco[0] if elenco else None
    f = fase(c) if c.collegato else PROVA
    R = RichiestaAgenti
    in_corso = r.stato == R.INVIATA or (r.stato == R.DA_APPROVARE and r.decisione in ("", R.ERRORE))
    return render(request, "awf/richiesta.html", {
        **schede(request, "richieste"), "r": r, "a": avanzamento(r, c), "tappe": _tappe(r, ultima, f),
        "errore": errore,
        "passi_incluso": passi_incluso(2) if (r.consenso or {}).get("agate_incluso") and in_corso else []})


# ---------- I miei agenti ----------

def _oggi():
    adesso = timezone.localtime()
    return adesso.replace(hour=0, minute=0, second=0, microsecond=0)


def conteggi_di_oggi():
    """{agente_id: {letture, modifiche, in_prova, rifiutate}} dal registro delle chiamate di oggi."""
    conti = {}
    for riga in (Chiamata.objects.filter(creato__gte=_oggi()).values("agente_id", "effetto", "esito")
                 .annotate(n=Count("pk"))):
        c = conti.setdefault(riga["agente_id"], {"letture": 0, "modifiche": 0, "in_prova": 0, "rifiutate": 0})
        if riga["esito"] == Chiamata.ESEGUITA:
            c["letture" if riga["effetto"] == "read" else "modifiche"] += riga["n"]
        elif riga["esito"] == Chiamata.OSSERVAZIONE:
            c["in_prova"] += riga["n"]
        else:
            c["rifiutate"] += riga["n"]
    return conti


@never_cache
@login_required
@permission_required(PERMESSO, raise_exception=True)
def miei(request):
    c = Collegamento.attuale()
    r = (RichiestaAgenti.objects.filter(stato=RichiestaAgenti.COLLEGATA, collegata_il__isnull=False)
         .select_related("responsabile").prefetch_related("persone").order_by("-collegata_il").first())
    agenti = list(Agente.objects.filter(attivo=True, tecnico=False)) if c.collegato else []
    f = fase(c) if c.collegato else None
    vuoti = {"letture": 0, "modifiche": 0, "in_prova": 0, "rifiutate": 0}
    conti = conteggi_di_oggi() if agenti else {}
    console = c.console_agate()
    return render(request, "awf/miei.html", {
        **schede(request, "miei"), "c": c, "r": r, "ingaggio": c.ingaggio, "fase": FASI.get(f), "in_prova": f == PROVA,
        "agenti": [{"a": a, **conti.get(a.pk, vuoti)} for a in agenti], "console_contratto": _console(c),
        "in_attesa": Approvazione.objects.filter(stato=Approvazione.IN_ATTESA).count(),
        "decidi_qui": contratto.garante() is not None,
        "link_attesa": (da_approvare_url() if contratto.garante() is not None else
                        f"{console}/console/approvals/" if console else reverse("awf:approvazioni")),
        "aperte": RichiestaAgenti.objects.filter(stato__in=RichiestaAgenti.APERTE).count()})


def _richiesta_in_corso(pk):
    r = get_object_or_404(RichiestaAgenti, pk=pk)
    if r.stato not in IN_CORSO:
        raise Http404("Richiesta chiusa")
    return r


@never_cache
@login_required
@permission_required(PERMESSO, raise_exception=True)
def cosa_puo_fare(request, pk):
    r = _richiesta_in_corso(pk)
    righe = squadre.stato_operazioni(r)
    if request.method == "POST":
        nuove, spente = assunzione.salva_scelte(r, {x["chiave"]: request.POST.get(f"op-{n}")
                                                    for n, x in enumerate(righe)}, request.user)
        messages.success(request, f"Salvato: {len(nuove)} cos{'a' if len(nuove) == 1 else 'e'} in più, {len(spente)} "
                                  f"in meno. Le azioni «Con il tuo ok» le conferma una persona in Agate.")
        return redirect("awf:miei")
    scelte = squadre.scelte(righe, r.scelte) if r.scelte else squadre.scelte_attuali(righe)
    return render(request, "awf/cosa_puo_fare.html", {
        **schede(request, "miei"), "r": r, "righe": [{**x, "scelta": scelte[x["chiave"]]} for x in righe],
        "scelte_possibili": RichiestaAgenti.SCELTE})


@never_cache
@login_required
@permission_required(PERMESSO, raise_exception=True)
def persone(request, pk):
    r = _richiesta_in_corso(pk)
    if request.method == "POST":
        b, errori = leggi_scelte(request.POST, [], request.user)
        if not errori:
            r.reparto_azienda, r.responsabile_id = b["reparto"], b["responsabile"]
            r.save(update_fields=["reparto_azienda", "responsabile", "aggiornata"])
            r.persone.set(b["persone"])
            messages.success(request, "Persone salvate.")
            return redirect("awf:miei")
        for e in errori:
            messages.error(request, e)
    return render(request, "awf/persone.html", {
        **schede(request, "miei"), "r": r, "utenti": assunzione.persone_possibili(),
        "reparti": assunzione.reparti_suggeriti(getattr(request, "azienda", None)),
        "scelte_persone": set(r.persone.values_list("pk", flat=True))})


# ---------- Avanzate ----------

@never_cache
@login_required
@permission_required(PERMESSO, raise_exception=True)
def avanzate(request):
    c = Collegamento.attuale()
    if request.method == "POST":
        azione = request.POST.get("azione")
        if azione == "fabbrica":
            _imposta_fabbrica(request, c)
        elif azione == "base_url":
            try:
                c.base_url = fabbrica.controlla_url(request.POST.get("base_url", ""), "di adabox")
                c.save(update_fields=["base_url"])
                messages.success(request, "Indirizzo di adabox salvato.")
            except fabbrica.ErroreFabbrica as e:
                messages.error(request, _maiuscola(str(e)) + ".")
        elif azione == "bearer":
            if not c.base_url:
                messages.error(request, "Prima indica l'indirizzo pubblico di adabox, qui sotto.")
            else:
                return _pagina_avanzate(request, c, bearer=fabbrica.rigenera_bearer(c))
        return redirect("awf:avanzate")
    return _pagina_avanzate(request, c)


def _pagina_avanzate(request, c, **extra):
    """La chiave per Agate si vede solo nella risposta che la genera: non va in sessione né nei messaggi, e la pagina
    non si salva nella cache del browser."""
    return render(request, "awf/avanzate.html", {
        **schede(request, "avanzate"), "c": c, "forge": fabbrica.indirizzo_fabbrica(),
        "base_url_proposta": c.base_url or _url_base(request),
        "impostazioni": request.user.has_perm("core.change_parametro"), "agate": agate_attivo(), **extra})
