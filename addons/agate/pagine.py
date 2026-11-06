"""Pagine del modulo, montate sotto /agate/: «Controllo AI» (dal menu del profilo, per chi gestisce Agate) con lo
stato della protezione, il registro delle azioni AI, «Da approvare» e le impostazioni (la prima volta: un codice da
incollare; a mano, in tre passi, sotto Avanzate); il webhook di Agate."""
import datetime
import json
import logging
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core import cifratura

from . import applicazione, cliente, decisioni
from .guardia import decisa
from .models import Collegamento, Valutazione

log = logging.getLogger("agate.pagine")

PERMESSO = "agate.change_collegamento"
SCHEDE = [("stato", "Stato", "agate:stato"), ("da_approvare", "Da approvare", "agate:da_approvare"),
          ("registro", "Registro delle azioni AI", "agate:valutazioni"),
          ("impostazioni", "Impostazioni", "agate:impostazioni")]
PASSI = ["Indirizzo e chiave", "Prova", "Modalità"]
V = Valutazione
GRUPPI = {"consentite": [V.CONSENTITA, V.APPROVATA], "in_attesa": [V.IN_ATTESA], "bloccate": [V.NEGATA, V.RIFIUTATA],
          "prova": [V.OSSERVATA], "errori": [V.ERRORE]}
FILTRI_ESITO = [("", "Tutte"), ("consentite", "Consentite"), ("in_attesa", "In attesa dell'ok"),
                ("bloccate", "Bloccate"), ("prova", "Solo registrate (prova)"), ("errori", "Agate non ha risposto")]
PERIODI = [("", "Sempre"), ("oggi", "Oggi"), ("7", "Ultimi 7 giorni"), ("30", "Ultimi 30 giorni")]
ESITI = {V.CONSENTITA: ("consentita ed eseguita", "ui-pill-ok", "check"),
         V.APPROVATA: ("approvata in Agate ed eseguita", "ui-pill-ok", "check"),
         V.IN_ATTESA: ("in attesa dell'ok in Agate", "ui-pill-warn", "info"),
         V.RIFIUTATA: ("non approvata in Agate (o scaduta)", "ui-pill-danger", "x"),
         V.NEGATA: ("bloccata dalle regole", "ui-pill-danger", "x"),
         V.OSSERVATA: ("solo registrata (prova): eseguita comunque", "ui-pill-info", "eye"),
         V.ERRORE: ("Agate non ha risposto", "ui-pill-danger", "alert-triangle")}
VERDETTI = {"allow": "consentirla", "deny": "bloccarla", "require_approval": "chiedere l'ok di una persona",
            "modify": "metterle un limite"}


def schede(request, attiva):
    """Le schede di «Controllo AI» nella barra dell'app (la stessa delle app con la voce in alto)."""
    return {"app_corrente": {"slug": "agate", "label": "Controllo AI", "url": reverse("agate:stato"),
                             "settings_url": None},
            "menu_app": [{"label": etichetta, "url": reverse(nome), "attiva": chiave == attiva}
                         for chiave, etichetta, nome in SCHEDE if chiave != "registro"
                         or request.user.has_perm("agate.view_valutazione")]}


def _oggi():
    return timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)


def configurato(c):
    return c is not None and bool(c.chiave_cifrata)


def riuscita(c):
    return bool(c and c.esito_controllo.startswith("Agate risponde"))


def _salva(request, collegamento):
    collegamento.gateway_url = request.POST.get("gateway_url", "").strip()
    collegamento.console_url = request.POST.get("console_url", "").strip()
    collegamento.prefisso = request.POST.get("prefisso", "").strip() or "adabox"
    collegamento.modalita = request.POST.get("modalita", Collegamento.OSSERVAZIONE)
    if chiave := request.POST.get("chiave", "").strip():
        collegamento.imposta_chiave(chiave)
    if segreto := request.POST.get("segreto", "").strip():
        collegamento.imposta_segreto(segreto)
    collegamento.full_clean(exclude=["chiave_cifrata", "segreto_cifrato"])
    collegamento.save()


def _prova(collegamento):
    try:
        nomi = [m.get("id") for m in cliente.modelli(collegamento)]
        collegamento.esito_controllo = f"Agate risponde: modelli {', '.join(n for n in nomi if n) or 'nessuno'}"
    except cliente.ErroreAgate as e:
        collegamento.esito_controllo = f"Agate non accetta: {e}"[:300]
    collegamento.ultimo_controllo = timezone.now()
    collegamento.save(update_fields=["esito_controllo", "ultimo_controllo"])
    return collegamento.esito_controllo


def usa_agate_per_i_modelli(collegamento):
    """Un provider «Agate» compatibile OpenAI (`/v1/llm`) con i modelli scelti dall'azienda in Agate: le
    chiavi dei fornitori restano in Agate, i dati personali vengono mascherati lì, il costo si conta lì."""
    from ai.models import Modello, Provider

    nomi = [m.get("id") for m in cliente.modelli(collegamento) if m.get("id")]
    provider, _ = Provider.objects.get_or_create(nome="Agate", defaults={"tipo": Provider.OPENAI_COMPAT})
    provider.tipo = Provider.OPENAI_COMPAT
    provider.base_url = collegamento.gateway_url.rstrip("/") + "/v1/llm"
    provider.chiave_cifrata = collegamento.chiave_cifrata
    provider.locale = False
    provider.attivo = True
    provider.save()
    for nome in nomi:
        Modello.objects.get_or_create(provider=provider, id_api=nome, defaults={"etichetta": f"Agate · {nome}"})
    return provider, nomi


# ---------- Stato ----------

def protezione(c):
    """(titolo, pill, spiegazione) della protezione ora."""
    if not configurato(c) or c.modalita == Collegamento.SPENTO:
        return ("Spenta", "ui-pill-neutral", "Le modifiche dell'assistente AI si eseguono senza passare da Agate.")
    if c.modalita == Collegamento.OSSERVAZIONE:
        return ("In prova (registra soltanto)", "ui-pill-info",
                "Agate valuta e registra ogni modifica dell'assistente, ma non ferma nulla: guarda il registro per "
                "vedere cosa cambierebbe, poi attivala.")
    return ("Protezione attiva", "ui-pill-ok",
            "Ogni modifica dell'assistente AI passa dalle regole di Agate: si esegue, aspetta l'ok di una persona "
            "o si ferma con il motivo.")


@login_required
@permission_required(PERMESSO, raise_exception=True)
def stato(request):
    c = Collegamento.attuale()
    conti = dict(Valutazione.objects.filter(creata__gte=_oggi()).values_list("stato").annotate(n=Count("pk")))
    oggi = {nome: sum(conti.get(s, 0) for s in stati) for nome, stati in GRUPPI.items()}
    return render(request, "agate/stato.html", {
        **schede(request, "stato"), "c": c, "configurato": configurato(c), "protezione": protezione(c),
        "semplice": applicazione.semplice(c), "da_approvare": decisioni.conteggio(request.user),
        "oggi": oggi, "controllate": sum(conti.values()),
        "in_attesa": Valutazione.objects.filter(stato=Valutazione.IN_ATTESA).count(),
        "attiva": configurato(c) and c.modalita == Collegamento.ATTIVO})


# ---------- Registro delle azioni AI ----------

def frase(v):
    """La valutazione detta in parole: chi, cosa ha chiesto all'assistente, com'è andata."""
    chi = (v.utente.get_full_name() or v.utente.get_username()) if v.utente else "Qualcuno"
    esito, pill, icona = ESITI.get(v.stato, (v.get_stato_display(), "ui-pill-neutral", "info"))
    motivo = v.motivo
    if v.stato == V.OSSERVATA and v.verdetto in VERDETTI:
        motivo = f"Con la protezione attiva Agate avrebbe scelto di {VERDETTI[v.verdetto]}."
    return {"v": v, "chi": chi, "cosa": v.proposta.titolo, "esito": esito, "pill": pill, "icona": icona,
            "motivo": motivo}


@login_required
@permission_required("agate.view_valutazione", raise_exception=True)
def valutazioni(request):
    filtri = {"esito": request.GET.get("esito", ""), "periodo": request.GET.get("periodo", ""),
              "utente": request.GET.get("utente", "")}
    righe = Valutazione.objects.select_related("proposta", "utente")
    if filtri["esito"] in GRUPPI:
        righe = righe.filter(stato__in=GRUPPI[filtri["esito"]])
    if filtri["periodo"] == "oggi":
        righe = righe.filter(creata__gte=_oggi())
    elif filtri["periodo"] in ("7", "30"):
        righe = righe.filter(creata__gte=timezone.now() - datetime.timedelta(days=int(filtri["periodo"])))
    if filtri["utente"].isdigit():
        righe = righe.filter(utente_id=int(filtri["utente"]))
    c = Collegamento.attuale()
    console = c.console_url.rstrip("/") if c and c.console_url else ""
    return render(request, "agate/valutazioni.html", {
        **schede(request, "registro"), "righe": [frase(v) for v in righe[:200]], "console": console,
        "semplice": applicazione.semplice(c),
        "filtri": filtri, "esiti": FILTRI_ESITO, "periodi": PERIODI,
        "utenti": get_user_model().objects.filter(pk__in=Valutazione.objects.values("utente")).order_by("username")})


# ---------- Impostazioni ----------

def _passo(valore):
    try:
        return min(max(int(valore), 1), 3)
    except (TypeError, ValueError):
        return 1


def _base_adabox(request):
    """L'indirizzo pubblico di adabox (dove Agate raggiunge il server MCP e il webhook): quello già noto agli agenti,
    altrimenti quello da cui si sta usando adabox."""
    if applicazione.awf_attivo():
        from awf.models import Collegamento as CollegamentoAwf
        if base := CollegamentoAwf.attuale().base_url:
            return base
    return request.build_absolute_uri("/").rstrip("/")


def _agate_proposto(c):
    return (c.gateway_url if c else "") or getattr(settings, "AGATE_URL", "") or os.environ.get("AGATE_URL", "")


def _codice(request, c, ripeti=False):
    """Il collegamento con un codice (§8.1): la prima volta è la pagina delle impostazioni; poi, in Avanzate, per
    ricollegarsi con un codice nuovo."""
    dati = {"gateway_url": request.POST.get("gateway_url", "").strip() or _agate_proposto(c),
            "codice": request.POST.get("codice", "").strip(),
            "base_url": request.POST.get("base_url", "").strip() or _base_adabox(request)}
    errore = ""
    if request.method == "POST":
        try:
            applicazione.collega(dati["gateway_url"], dati["codice"], dati["base_url"])
        except applicazione.ErroreCollegamento as e:
            errore = str(e)
        else:
            messages.success(request, "Fatto ✓ — Controllo AI attivo, gli agenti si possono assumere.")
            return redirect("agate:stato")
        if ripeti:
            messages.error(request, errore)
            return redirect("agate:impostazioni")
    return render(request, "agate/codice.html", {
        **schede(request, "impostazioni"), "c": c, "dati": dati, "errore": errore, "awf": applicazione.awf_attivo()})


@never_cache
@login_required
@permission_required(PERMESSO, raise_exception=True)
def impostazioni(request):
    attuale = Collegamento.attuale()
    sorgente = request.POST if request.method == "POST" else request.GET
    if request.POST.get("azione") == "codice":
        return _codice(request, attuale, ripeti=configurato(attuale))
    if "passo" in sorgente:                             # a mano, in tre passi (Avanzate)
        return _procedura(request, attuale, _passo(sorgente.get("passo")) if configurato(attuale) else 1)
    if not configurato(attuale):                        # la prima volta: il codice
        return _codice(request, attuale)
    if request.method == "POST":
        azione = request.POST.get("azione", "salva")
        try:
            if azione == "sincronizza":
                if applicazione.sincronizza(attuale):
                    messages.success(request, f"Strumenti risincronizzati: {attuale.esito_sincronizzazione}.")
                else:
                    messages.error(request, f"Risincronizzazione {attuale.esito_sincronizzazione}. Si riprova da sola "
                                            "ogni minuto.")
            elif azione == "salva":
                _salva(request, attuale)
                messages.success(request, f"Impostazioni salvate. {_prova(attuale)}")
            elif azione == "prova":
                messages.info(request, _prova(attuale))
            elif azione == "modelli":
                provider, nomi = usa_agate_per_i_modelli(attuale)
                messages.success(request, f"Provider «{provider.nome}» pronto con {len(nomi)} modelli: sceglili nei "
                                          "Profili dell'assistente.")
        except cliente.ErroreAgate as e:
            messages.error(request, str(e))
        except Exception as e:                           # validazione del modello
            messages.error(request, f"Dati non validi: {e}")
        return redirect("agate:impostazioni")
    return render(request, "agate/impostazioni.html", {
        **schede(request, "impostazioni"), "c": attuale, "modalita": _modalita(),
        "chiave": cifratura.mascherato(attuale.chiave()), "segreto": bool(attuale.segreto_cifrato),
        "webhook_url": request.build_absolute_uri(reverse("agate:webhook")), "riuscita": riuscita(attuale),
        "semplice": applicazione.semplice(attuale)})


def _modalita():
    return [(valore, etichetta, Collegamento.SPIEGAZIONI[valore]) for valore, etichetta in Collegamento.MODALITA]


def _procedura(request, c, passo):
    """La prima volta, tre passi: 1 indirizzo e chiave (il collegamento nasce spento) → 2 prova → 3 modalità."""
    if request.method == "POST":
        if passo == 1:
            c = c or Collegamento(modalita=Collegamento.SPENTO)
            c.gateway_url = request.POST.get("gateway_url", "").strip()
            c.console_url = request.POST.get("console_url", "").strip()
            if chiave := request.POST.get("chiave", "").strip():
                c.imposta_chiave(chiave)
            try:
                if not c.chiave_cifrata:
                    raise ValueError("serve la chiave di Agate")
                c.full_clean(exclude=["chiave_cifrata", "segreto_cifrato"])
            except Exception as e:                       # validazione del modello
                messages.error(request, f"Dati non validi: {e}")
                return redirect(f"{reverse('agate:impostazioni')}?passo=1")
            c.save()
            _prova(c)
            return redirect(f"{reverse('agate:impostazioni')}?passo=2")
        if passo == 2 and c is not None:
            _prova(c)
            return redirect(f"{reverse('agate:impostazioni')}?passo=2")
        if passo == 3 and c is not None:
            scelta = request.POST.get("modalita")
            if scelta in dict(Collegamento.MODALITA):
                c.modalita = scelta
                c.save(update_fields=["modalita"])
                messages.success(request, f"Controllo AI: {protezione(c)[0].lower()}.")
                return redirect("agate:stato")
            messages.error(request, "Scegli una modalità.")
        return redirect(f"{reverse('agate:impostazioni')}?passo={passo}")
    return render(request, "agate/procedura.html", {
        **schede(request, "impostazioni"), "c": c, "passo": passo, "riuscita": riuscita(c),
        "passi": [(n, nome, "fatto" if n < passo else "attuale" if n == passo else "futuro")
                  for n, nome in enumerate(PASSI, 1)], "modalita": _modalita(),
        "chiave": cifratura.mascherato(c.chiave()) if configurato(c) else ""})


# ---------- Da approvare ----------

@never_cache
@login_required
def da_approvare(request):
    """Quello che aspetta una persona, deciso qui a nome di chi clicca (le azioni degli agenti, le proposte
    dell'assistente, i contratti da rivedere). Per chi gestisce il Controllo AI o gli agenti."""
    if not decisioni.puo_vedere(request.user):
        raise PermissionDenied
    indietro = request.get_full_path()
    if request.method == "POST":
        approva = request.POST.get("decisione") == "approva"
        try:
            messaggio = decisioni.decidi(request.user, request.POST.get("tipo", ""), request.POST.get("pk") or 0,
                                         approva, request.POST.get("motivo", ""), request.POST.get("password", ""))
        except decisioni.Rifiutata as e:
            messages.error(request, str(e))
        else:
            messages.success(request, messaggio)
        return redirect(indietro)
    c = Collegamento.attuale()
    console = c.console_url.rstrip("/") if c and c.console_url else ""
    if (request.GET.get("da") == "awf" or not request.user.has_perm(PERMESSO)) and decisioni.vede_agenti(request.user):
        from awf.area import schede as schede_awf
        barra = schede_awf(request, "da_approvare")
    else:
        barra = schede(request, "da_approvare")
    return render(request, "agate/da_approvare.html", {
        **barra, "voci": decisioni.voci(request.user, console), "semplice": applicazione.semplice(c),
        "console": console})


@csrf_exempt
@require_POST
def webhook(request):
    """Eventi di Agate firmati col segreto. È l'unico indirizzo registrato dal collegamento con un codice: le
    approvazioni dell'assistente (`approval.decided` esegue o chiude la proposta in attesa) restano qui, quelle degli
    agenti e del loro contratto passano al modulo `awf`."""
    c = Collegamento.attuale()
    if c is None or not c.segreto_cifrato:
        return HttpResponse(status=404)
    try:
        cliente.verifica_firma(c.segreto(), request.headers.get("X-Agate-Signature"), request.body)
        evento = json.loads(request.body)
    except (ValueError, cifratura.SegretoIlleggibile):
        return HttpResponse(status=401)
    tipo = evento.get("type") if isinstance(evento, dict) else None
    dati = evento.get("data") if isinstance(evento, dict) else None
    if tipo not in ("approval.requested", "approval.decided") or not isinstance(dati, dict):
        return JsonResponse({"ricevuto": True})
    approval_id = str(dati.get("approval_id") or "")
    valutazione = Valutazione.objects.filter(approval_id=approval_id).first() if approval_id else None
    if valutazione is not None or str(dati.get("tool") or "").startswith(f"{c.prefisso}."):
        if tipo == "approval.decided" and valutazione is not None:
            decisa(valutazione, str(dati.get("decision", "")), motivo=str(dati.get("reason") or ""))
        return JsonResponse({"ricevuto": True})
    if applicazione.awf_attivo():
        from awf import webhook as webhook_awf
        return webhook_awf.gestisci(tipo, dati)
    return JsonResponse({"ricevuto": True})
