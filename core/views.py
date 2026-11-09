from django import forms
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.migrations.recorder import MigrationRecorder
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from . import azienda as az
from . import moduli as mod
from . import attivita as attivita_servizio
from . import barra, due_fattori, lavori, licenza, parametri

from .forms import AziendaPredefinitaForm, CampoPersonalizzatoForm, ProfiloForm, TokenApiForm
from django.db.models import Q

from .models import LicenzaIstanza, RichiestaModulo
from .models import (Azienda, CampoPersonalizzato, EmailRicevuta, Lavoro, Modulo, Parametro, ProfiloUtente, RegistroModifica,
                     ModelloStampa, PermessoCampo, RegolaRiga, Ruolo, TokenApi,
                     CatenaApprovazione, DecisioneApprovazione, Delega, PassoApprovazione, ReportPianificato,
                     IscrizionePush, RichiestaApprovazione)
from .registry import hooks, modules, pacchetti, sincronia
from .signals import crea_profilo
from .viste import Inline, ModelView, register
from .viste import registry as registry_viste


def voci_kernel(user):
    """Pagine del kernel nel launcher, secondo i permessi."""
    voci = [{"label": "Dashboard", "url": reverse("core:dashboard"), "icon": "zap",
              "sub": "Gli indicatori di tutte le app"}]
    if attivita_servizio.mie(user).exists():
        voci.append({"label": "Le mie attività", "url": reverse("core:attivita"), "icon": "check",
                     "sub": f"Da fare oggi o scadute: {attivita_servizio.da_fare_oggi(user)}"})
    if user.has_perm("auth.change_user"):
        voci.append({"label": "Utenti e ruoli", "url": reverse("core:utenti"), "icon": "users",
                     "sub": "Chi entra, con quale ruolo e che cosa può fare in ogni modulo"})
    if user.has_perm("core.view_modulo"):
        voci.append({"label": "Applicazioni", "url": reverse("core:applicazioni"), "icon": "layout",
                     "sub": "Le app attive e quelle che si possono aggiungere"})
    if user.has_perm("core.view_registromodifica"):
        voci.append({"label": "Registro delle modifiche", "url": reverse("core:registro_lista"), "icon": "shield",
                     "sub": "Chi ha cambiato cosa, quando e da dove"})
    if user.has_perm("core.view_azienda"):
        voci.append({"label": "Aziende", "url": reverse("core:aziende_lista"), "icon": "tool",
                     "sub": "Anagrafica delle aziende dell'istanza"})
    if user.is_superuser:
        voci.append({"label": "Lavori", "url": reverse("core:lavoro_lista"), "icon": "zap",
                     "sub": "Coda dei lavori in background"})
        voci.append({"label": "Email ricevute", "url": reverse("core:email_lista"), "icon": "inbox",
                     "sub": "Risposte alle notifiche e loro abbinamento"})
        voci.append({"label": "Moduli", "url": reverse("core:moduli"), "icon": "download",
                     "sub": "Installa, aggiorna e disinstalla le app"})
    if user.has_perm("core.view_campopersonalizzato"):
        voci.append({"label": "Campi personalizzati", "url": reverse("core:campi_lista"), "icon": "edit",
                     "sub": "Campi aggiunti ai modelli senza programmare"})
    if user.has_perm("core.add_reportpianificato"):
        voci.append({"label": "Report pianificati", "url": reverse("core:report_pianificati_lista"), "icon": "inbox",
                     "sub": "Liste e pagine di Analisi per email, ogni giorno, settimana o mese"})
    voci.append({"label": "In tasca", "url": reverse("core:tasca"), "icon": "phone",
                 "sub": "La pagina per il telefono, con le notifiche sul dispositivo"})
    voci.append({"label": "Da approvare", "url": reverse("core:da_approvare"), "icon": "check",
                 "sub": "Le approvazioni che aspettano la tua decisione"})
    if user.has_perm("core.view_catenaapprovazione"):
        voci.append({"label": "Catene di approvazione", "url": reverse("core:catene_approvazione_lista"), "icon": "shield",
                     "sub": "Chi approva quali documenti, oltre quali soglie"})
    if user.has_perm("core.view_modellostampa"):
        voci.append({"label": "Modelli di stampa", "url": reverse("core:stampe_lista"), "icon": "edit",
                     "sub": "Intestazione, testi e colonne di preventivi, fatture, DDT e ordini"})
    if user.has_perm("core.change_parametro") and parametri.definizioni():
        voci.append({"label": "Impostazioni", "url": reverse("core:impostazioni"), "icon": "tool",
                     "sub": "Parametri delle app installate"})
    if user.is_staff:
        voci.append({"label": "Stile", "url": reverse("core:stile"), "icon": "eye",
                     "sub": "Catalogo dei componenti grafici"})
    return voci


@login_required
def home(request):
    """La prima pagina (anche dopo il login): la prima voce della barra in alto come la vede l'utente. Senza scelte
    è la prima app di NAV_APP_IN_TESTA (di norma la chat AI), altrimenti la Dashboard."""
    from .middleware import esterno
    if esterno(request.user):
        return redirect(settings.PORTALE_HOME)
    for nome in barra.prima_pagina(request.user, modules.app_visibili(request.user)):
        try:
            return redirect(reverse(nome))
        except NoReverseMatch:
            continue
    return redirect("core:dashboard")


@login_required
def dashboard(request):
    from . import dashboard as dash
    widget, schede = dash.catalogo(request)
    visibili, nascosti = dash.disposizione(request.user, widget)
    visibili = dash.carica(visibili)
    from .registry import hooks
    return render(request, "core/dashboard.html", {
        "widget": visibili, "nascosti": nascosti, "schede": schede, "personalizzata": dash.personalizzata(request.user),
        "ruoli": Ruolo.objects.order_by("ordine", "nome") if request.user.has_perm("core.change_ruolo") else None,
        "contesto_ada": dash.contesto_per_ada(visibili), "sezioni_dashboard": hooks.sezioni_dashboard(request)})


@login_required
@require_POST
def dashboard_layout(request):
    """Ordine, larghezze e widget tolti, dal client in JSON."""
    import json

    from . import dashboard as dash
    try:
        dati = json.loads(request.body or b"{}")
        salvato = dash.salva_layout(request.user, dati, dash.catalogo(request)[0])
    except (ValueError, TypeError):
        return JsonResponse({"errore": "disposizione non valida"}, status=400)
    return JsonResponse({"ok": True, **salvato})


@login_required
@require_POST
def dashboard_per_ruolo(request):
    """L'amministratore fa della sua dashboard quella di partenza di un ruolo (o la toglie): chi ha quel ruolo e non ha
    ancora disposto la sua parte da lì; ognuno vede solo i widget che i suoi permessi gli consentono."""
    from . import dashboard as dash
    if not request.user.has_perm("core.change_ruolo"):
        raise PermissionDenied
    ruolo = get_object_or_404(Ruolo, pk=request.POST.get("ruolo") or 0)
    if request.POST.get("azione") == "togli":
        ruolo.dashboard = {}
        messages.success(request, f"Il ruolo «{ruolo}» parte di nuovo dalla dashboard standard.")
    else:
        ruolo.dashboard = dash.layout_di(request.user)
        messages.success(request, f"Questa disposizione è ora la dashboard di partenza del ruolo «{ruolo}» "
                                  "per chi non ha ancora personalizzato la sua.")
    ruolo.save(update_fields=["dashboard"])
    return redirect("core:dashboard")


@login_required
@require_POST
def dashboard_reset(request):
    from .models import DashboardUtente
    DashboardUtente.objects.filter(utente=request.user).delete()
    messages.success(request, "Dashboard riportata a quella di partenza.")
    return redirect("core:dashboard")


@login_required
def launcher(request):
    try:
        url_moduli = reverse("core:moduli")
    except NoReverseMatch:
        url_moduli = ""
    return render(request, "core/launcher.html", {"kernel": voci_kernel(request.user), "url_moduli": url_moduli})


@login_required
def stile(request):
    return render(request, "core/stile.html")


CHIAVE_TOKEN_NUOVO = "token_api_chiaro"


@login_required
def profilo(request):
    form = ProfiloForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profilo aggiornato.")
        return redirect("core:profilo")
    form_azienda = None
    if len(az.consentite(request.user)) > 1:
        form_azienda = AziendaPredefinitaForm(instance=crea_profilo(request.user))
    return render(request, "core/profilo.html", {
        "form": form, "form_azienda": form_azienda, "due_fattori_attiva": due_fattori.attiva(request.user),
        "form_token": TokenApiForm(utente=request.user), "token": request.user.token_api.all(),
        "token_chiaro": request.session.pop(CHIAVE_TOKEN_NUOVO, None),   # mostrato una sola volta
    })


@require_POST
@login_required
def azienda_predefinita(request):
    form = AziendaPredefinitaForm(request.POST, instance=crea_profilo(request.user))
    if form.is_valid():
        form.save()
        messages.success(request, f"Azienda predefinita: {form.instance.azienda_predefinita}.")
    else:
        messages.error(request, "Azienda non consentita.")
    return redirect("core:profilo")


@require_POST
@login_required
def token_nuovo(request):
    form = TokenApiForm(request.POST, utente=request.user)
    if form.is_valid():
        _, chiaro = TokenApi.genera(request.user, form.cleaned_data["nome"], scadenza=form.scadenza(),
                                    sola_lettura=form.cleaned_data["sola_lettura"], moduli=form.cleaned_data["moduli"])
        request.session[CHIAVE_TOKEN_NUOVO] = chiaro
        messages.success(request, "Token creato: copialo ora, non sarà più mostrato.")
    else:
        messages.error(request, "Controlla il token: serve un nome e i moduli devono essere tra quelli che vedi.")
    return redirect("core:profilo")


@require_POST
@login_required
def token_revoca(request, pk):
    token = get_object_or_404(TokenApi, pk=pk, utente=request.user)
    token.attivo = False
    token.save(update_fields=["attivo"])
    messages.success(request, f"Token «{token.nome}» revocato.")
    return redirect("core:profilo")


@require_POST
@login_required
def cambia_azienda(request):
    pk = request.POST.get("azienda", "")
    scelta = get_object_or_404(Azienda, pk=int(pk) if pk.isdigit() else 0, attiva=True)
    if scelta not in az.consentite(request.user):
        raise PermissionDenied
    request.session[az.CHIAVE_SESSIONE] = scelta.pk
    messages.success(request, f"Azienda corrente: {scelta}.")
    prossima = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(prossima, {request.get_host()}, request.is_secure()):
        prossima = "/"
    return redirect(prossima)


@register
class AziendaView(ModelView):
    """Gestione delle aziende (/core/aziende/) e banco di prova delle viste generiche."""
    model = Azienda
    slug = "aziende"
    api = True
    api_fields = ["nome", "partita_iva", "codice_fiscale", "citta", "provincia", "email", "telefono", "attiva"]
    list_display = ["nome", "partita_iva", "citta", "attiva"]
    list_filter = ["attiva", "provincia"]
    search_fields = ["nome", "partita_iva"]
    ordering = ["nome"]
    per_page = 25
    form_layout = [
        ("Anagrafica", ["nome", ("partita_iva", "codice_fiscale"), ("indirizzo", "cap"), ("citta", "provincia")]),
        ("Contatti", [("email", "telefono"), "logo", "attiva"]),
    ]
    actions = ["disattiva"]
    buttons = ["attiva"]
    chatter = True
    tracked_fields = ["nome", "partita_iva", "attiva"]
    reports = [{"nome": "Scheda azienda", "template": "core/report/azienda.html"}]

    def col_citta(self, obj):
        return obj.citta.upper() if obj.citta else "—"
    col_citta.short_description = "Città"

    def disattiva(self, request, queryset):
        n = queryset.update(attiva=False)
        return f"Aziende disattivate: {n}."
    disattiva.short_description = "Disattiva"

    def attiva(self, request, obj):
        obj.attiva = True
        obj.save(update_fields=["attiva"])
        return f"Azienda «{obj}» attivata."
    attiva.short_description = "Attiva"


def solo_superuser(vista):
    """Login richiesto; poi 403 (non un altro redirect al login) per chi non è superuser."""
    @login_required
    @wraps(vista)
    def interna(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return interna


def _schede_moduli():
    righe = modules.sincronizza()
    info = modules.scopri()
    installati = modules.installati()
    # migrazioni ancora registrate = tabelle rimaste (disinstallato senza --elimina-dati)
    con_dati = set(MigrationRecorder.Migration.objects.values_list("app", flat=True).distinct())
    schede = []
    fuori = licenza.fuori_licenza()
    for r in righe:
        m = info[r.slug].manifest if r.slug in info else None
        installato = r.slug in installati
        ops = {
            Modulo.DISPONIBILE: ["installa"],
            Modulo.INSTALLATO: ["disinstalla"],
            Modulo.DA_AGGIORNARE: ["aggiorna", "disinstalla"],
            Modulo.MANCANTE: ["disinstalla"],
            Modulo.ERRORE: ["aggiorna", "disinstalla"] if installato else (["installa"] if m else []),
        }[r.stato]
        schede.append({"riga": r, "manifest": m, "ops": ops, "installato": installato,
                       "dati_presenti": not installato and r.slug in con_dati, "fuori_licenza": r.slug in fuori or not licenza.ammesso(r.slug),
                       "origine": pacchetti.origine(info[r.slug].cartella) if r.slug in info else None})
    return schede


def _pagina_moduli(request, log=None):
    from django.conf import settings
    ctx = {"schede": _schede_moduli(), "firma_obbligatoria": settings.MODULI_FIRMA_OBBLIGATORIA,
           "catalogo_configurato": bool(settings.MODULI_CATALOGO_URL), "licenza": licenza.attuale(),
           "licenza_obbligatoria": licenza.obbligatoria(), "riga_licenza": LicenzaIstanza.objects.first(),
           "portale": sincronia.configurata(), "richieste": RichiestaModulo.objects.filter(stato=RichiestaModulo.INVIATA)[:20],
           "utenti_attivi": licenza.utenti_attivi()}
    if settings.MODULI_CATALOGO_URL:
        try:
            ctx["catalogo"] = [v for v in pacchetti.leggi_catalogo() if v["stato"] != "presente"]
        except pacchetti.PacchettoNonValido as e:
            ctx["errore_catalogo"] = str(e)
    if log:
        ctx["log"], (ctx["coda"], ctx["stato"]) = log, mod.leggi(log)
    return render(request, "core/moduli.html", ctx)


@require_GET
@solo_superuser
def moduli(request):
    return _pagina_moduli(request)


@require_POST
@solo_superuser
def moduli_azione(request):
    op, slug = request.POST.get("op", ""), request.POST.get("slug", "")
    if op not in ("installa", "aggiorna", "disinstalla"):
        return HttpResponseBadRequest("operazione sconosciuta")
    if slug not in set(modules.scopri()) | set(modules.installati()):
        return HttpResponseBadRequest("modulo sconosciuto")
    log = mod.avvia(op, slug, demo=request.POST.get("demo") == "1",
                    elimina_dati=request.POST.get("elimina_dati") == "1")
    if not request.headers.get("HX-Request"):
        return _pagina_moduli(request, log)
    coda, stato = mod.leggi(log)
    return render(request, "core/partials/_moduli_stato.html", {"log": log, "coda": coda, "stato": stato})


@require_POST
@solo_superuser
def moduli_attivazione(request):
    """Accende o spegne un modulo installato, subito e senza riavvii (lo legge ogni richiesta)."""
    slug, attivo = request.POST.get("slug", ""), request.POST.get("attivo") == "1"
    if not modules.imposta_attivo(slug, attivo):
        messages.error(request, f"«{slug}» non è installato.")
        return redirect("core:moduli")
    nome = Modulo.objects.filter(slug=slug).values_list("nome", flat=True).first() or slug
    messages.success(request, f"{nome} riattivato: è di nuovo visibile." if attivo else
                     f"{nome} disattivato: nascosto a tutti, dati e installazione restano.")
    return redirect(f"{reverse('core:moduli')}#modulo-{slug}")


@require_POST
@solo_superuser
def moduli_carica(request):
    """Caricamento di un pacchetto zip: controlli, poi estrazione in addons/ (l'installazione resta un bottone)."""
    import tempfile
    file = request.FILES.get("pacchetto")
    if file is None:
        messages.error(request, "Scegli un pacchetto .zip.")
        return redirect("core:moduli")
    with tempfile.NamedTemporaryFile(suffix=".zip") as temporaneo:
        for blocco in file.chunks():
            temporaneo.write(blocco)
        temporaneo.flush()
        try:
            esito = pacchetti.carica(temporaneo.name, nome_pacchetto=file.name)
        except pacchetti.PacchettoNonValido as e:
            messages.error(request, "Pacchetto rifiutato: " + "; ".join(e.errori))
            return redirect("core:moduli")
    origine = f"firmato da {esito.firmato_da}" if esito.firmato_da else "non firmato"
    messages.success(request, f"{esito.nome} {esito.versione} caricato ({origine}): ora puoi installarlo o aggiornarlo.")
    return redirect(f"{reverse('core:moduli')}#modulo-{esito.slug}")


@require_POST
@solo_superuser
def moduli_scarica(request):
    """Scarica dal catalogo un modulo nuovo o aggiornato e lo carica in addons/."""
    try:
        esito = pacchetti.scarica(request.POST.get("slug", ""))
    except pacchetti.PacchettoNonValido as e:
        messages.error(request, "Download rifiutato: " + "; ".join(e.errori))
        return redirect("core:moduli")
    messages.success(request, f"{esito.nome} {esito.versione} scaricato dal catalogo: ora puoi installarlo o aggiornarlo.")
    return redirect(f"{reverse('core:moduli')}#modulo-{esito.slug}")


@require_POST
@solo_superuser
def moduli_licenza(request):
    """Carica un file di licenza (per le istanze senza portale)."""
    file = request.FILES.get("licenza")
    if file is None:
        messages.error(request, "Scegli un file di licenza.")
        return redirect("core:moduli")
    try:
        stato = licenza.salva(file.read().decode("utf-8", errors="replace"))
    except ValueError as e:
        messages.error(request, f"Licenza rifiutata: {e}")
        return redirect("core:moduli")
    messages.success(request, f"Licenza di {stato.cliente} caricata, valida fino al {stato.scadenza:%d/%m/%Y}.")
    return redirect("core:moduli")


@require_POST
@solo_superuser
def moduli_sincronizza(request):
    """Il giro col portale parte nel worker: installare moduli non è cosa da una richiesta web."""
    lavori.accoda("core.registry.sincronia.esegui")
    messages.success(request, "Sincronizzazione col portale avviata: l'esito compare qui tra poco.")
    return redirect("core:moduli")


@require_GET
@solo_superuser
def moduli_stato(request):
    log = request.GET.get("log", "")
    try:
        coda, stato = mod.leggi(log)
    except ValueError:
        return HttpResponseBadRequest("log non valido")
    return render(request, "core/partials/_moduli_stato.html", {"log": log, "coda": coda, "stato": stato})


@register
class ProfiloUtenteView(ModelView):
    """Profili utente: viste generiche senza API e fuori dai menu (si gestiscono anche dall'admin)."""
    model = ProfiloUtente
    slug = "profili"
    list_display = ["utente", "azienda_predefinita"]
    api = False


class SoloSuperuserView(ModelView):
    """Viste del kernel in sola lettura per il superuser (lavori, email ricevute, ...)."""

    def _perm(self, request, azione):
        return azione == "view" and request.user.is_superuser


@register
class LavoroView(SoloSuperuserView):
    model = Lavoro
    api = False                   # contiene segreti o credenziali: niente API
    storico = False
    list_display = ["funzione", "stato", "tentativi", "esegui_dopo", "finito"]
    list_filter = ["stato"]
    search_fields = ["funzione"]
    form_layout = [("Lavoro", ["funzione", "argomenti", ("stato", "tentativi", "max_tentativi")]),
                   ("Tempi", [("creato", "esegui_dopo"), ("iniziato", "finito")]),
                   ("Esito", ["risultato", "errore"])]
    readonly_fields = ["creato"]
    buttons = ["riprova"]

    def col_errore(self, obj):
        return format_html('<pre class="ui-log">{}</pre>', obj.errore) if obj.errore else "—"
    col_errore.short_description = "Errore"

    def riprova(self, request, obj):
        from . import lavori
        lavori.riprova(obj)
        return "Lavoro rimesso in coda."
    riprova.short_description = "Riprova"
    riprova.permission = "view"


@login_required
def impostazioni(request):
    """Una card per modulo con `settings` nel manifest; si salva un modulo alla volta."""
    if not request.user.has_perm("core.change_parametro"):
        raise PermissionDenied
    azienda = getattr(request, "azienda", None)
    manifest = modules.manifests_attivi()
    moduli_con = [slug for slug, m in manifest.items() if m.settings]
    inviato = request.POST.get("modulo") if request.method == "POST" else None
    if inviato == "sicurezza":
        if request.user.is_superuser and request.POST.get("obbligo") in dict(due_fattori.OBBLIGHI):
            due_fattori.scrivi_obbligo(request.POST["obbligo"])
            messages.success(request, "Regola della verifica in due passaggi salvata.")
        return redirect(f"{reverse('core:impostazioni')}#sicurezza")
    if inviato is not None and inviato not in moduli_con:
        return HttpResponseBadRequest("modulo sconosciuto")
    schede = []
    for slug in moduli_con:
        form = parametri.ImpostazioniForm(slug, azienda, request.POST if inviato == slug else None)
        if inviato == slug and form.is_valid():
            form.salva()
            messages.success(request, f"Impostazioni di {manifest[slug].name} salvate.")
            return redirect(f"{reverse('core:impostazioni')}#{slug}")
        schede.append({"slug": slug, "nome": manifest[slug].name, "form": form})
    return render(request, "core/impostazioni.html", {"schede": schede, "obblighi": due_fattori.OBBLIGHI,
                                                      "obbligo": due_fattori.leggi_obbligo()})


def _scelte_barra(request, tutte):
    """Gli slug spuntati nel form della barra, nell'ordine indicato."""
    scelte = []
    for indice, (slug, _) in enumerate(tutte):
        if request.POST.get(f"fissa_{slug}"):
            ordine = request.POST.get(f"ordine_{slug}", "")
            scelte.append((int(ordine) if ordine.lstrip("-").isdigit() else 999, indice, slug))
    return [slug for _, _, slug in sorted(scelte)]


def _liste_barra(tutte, scelta):
    """Le due liste come le mostra davvero l'header (la funzione è la stessa), con anche le voci nascoste, segnate."""
    manifest = modules.manifests_attivi()
    voci = [{"slug": slug, "nome": nome, "categoria": manifest[slug].category if slug in manifest else ""}
            for slug, nome in tutte if slug != barra.DASHBOARD]
    dashboard = {"slug": barra.DASHBOARD, "nome": "Dashboard", "categoria": "Direzione"}
    nascoste = set(scelta["nascoste"])
    barra_, altre = barra.componi(voci, dashboard, {**scelta, "nascoste": []})
    altre = [{**v, "colonna": g["titolo"]} for g in barra.gruppi(altre, "nome") for v in g["voci"]]      # come nel menu
    posizione = 0
    for i, r in enumerate(barra_, start=1):
        r["ordine"] = i
        if r["slug"] not in nascoste:
            posizione += 1
            r["posizione"] = posizione
    for r in [*barra_, *altre]:
        r["nascosta"] = r["slug"] in nascoste
    return {"barra": barra_, "altre": altre}


def _nascoste_barra(request, tutte):
    return [slug for slug, _ in tutte if request.POST.get(f"nascosta_{slug}")]


@login_required
def impostazioni_barra(request):
    """Quali voci stanno nella barra in alto, in che ordine e quali sono nascoste, per tutti; le altre vanno in "Altre"."""
    if not request.user.has_perm("core.change_parametro"):
        raise PermissionDenied
    manifest = modules.manifests_attivi()
    spenti = modules.disattivati()
    nomi = modules.etichette()
    dentro = hooks.parti_dashboard()
    tutte = [(barra.DASHBOARD, "Dashboard"), *((slug, nomi.get(slug) or m.nav_label or m.name) for slug, m in manifest.items()
                                              if m.application and slug not in spenti and slug not in dentro)]
    if request.method == "POST":
        if request.POST.get("ripristina"):
            Parametro.objects.filter(chiave=barra.CHIAVE, azienda__isnull=True).delete()
            messages.success(request, "Barra in alto riportata alla scelta automatica.")
            return redirect("core:impostazioni_barra")
        quante = request.POST.get("quante", "")
        barra.scrivi(_scelte_barra(request, tutte), int(quante) if quante.isdigit() else barra.leggi()["quante"], _nascoste_barra(request, tutte))
        messages.success(request, "Barra in alto salvata.")
        return redirect("core:impostazioni_barra")
    attuale = barra.leggi()
    return render(request, "core/impostazioni_barra.html", {
        **_liste_barra(tutte, attuale), "quante": attuale["quante"], "massimo": barra.MASSIMO, "aziendale": True,
        "personalizzata": Parametro.objects.filter(chiave=barra.CHIAVE, azienda__isnull=True).exists()})


@login_required
def le_mie_app(request):
    """Ognuno decide per sé: che cosa sta nella barra, in che ordine, che cosa nascondere. Le altre restano in «Altre»."""
    tutte = [(barra.DASHBOARD, "Dashboard"), *((a["slug"], a["nav_label"]) for a in modules.app_visibili(request.user)
                                              if a["slug"] not in hooks.parti_dashboard())]
    profilo = crea_profilo(request.user)
    if request.method == "POST":
        ripristina = bool(request.POST.get("ripristina"))
        profilo.barra = {} if ripristina else {"fisse": _scelte_barra(request, tutte), "nascoste": _nascoste_barra(request, tutte), "completa": True}
        profilo.save(update_fields=["barra"])
        messages.success(request, "Il tuo menu segue di nuovo quello dell'azienda." if ripristina else "Il tuo menu è salvato.")
        return redirect("core:le_mie_app")
    return render(request, "core/impostazioni_barra.html", {
        **_liste_barra(tutte, barra.per_utente(request.user)), "aziendale": False, "personalizzata": bool(profilo.barra)})


@register
class EmailRicevutaView(SoloSuperuserView):
    model = EmailRicevuta
    storico = False
    slug = "email"
    list_display = ["oggetto", "mittente", "stato", "ricevuta"]
    list_filter = ["stato"]
    search_fields = ["oggetto", "mittente", "message_id"]
    form_layout = [("Email", ["oggetto", ("mittente", "ricevuta"), "message_id"]),
                   ("Esito", [("stato", "messaggio"), "motivo"])]
    readonly_fields = ["ricevuta"]


@login_required
def attivita_mie(request):
    return render(request, "core/attivita_mie.html", {"gruppi": attivita_servizio.raggruppate(request.user)})


@register
class CampoPersonalizzatoView(ModelView):
    model = CampoPersonalizzato
    slug = "campi"
    list_display = ["label", "nome", "modello", "tipo", "azienda", "in_lista", "filtrabile"]
    list_filter = ["modello", "tipo", "azienda"]
    search_fields = ["label", "nome"]
    ordering = ["modello", "ordine", "pk"]
    form_class = CampoPersonalizzatoForm
    form_layout = [("Campo", ["modello", ("label", "nome"), ("tipo", "ordine"), "scelte", "collega_a", "aiuto"]),
                   ("Comportamento", [("obbligatorio", "in_lista", "filtrabile"), "azienda"])]


def salute(request):
    """Per il controllo delle istanze: risponde se l'applicazione gira e il database c'è. Nessun dettaglio all'esterno."""
    from django.db import DatabaseError, connection
    from django.http import JsonResponse
    try:
        connection.ensure_connection()
        with connection.cursor() as cursore:
            cursore.execute("SELECT 1")
    except DatabaseError:
        return JsonResponse({"stato": "errore"}, status=503)
    return JsonResponse({"stato": "ok"})


@register
class RegistroModificaView(ModelView):
    """Il registro delle modifiche: si legge e basta. Chi cambia i record di tutte le aziende compare solo al superuser."""
    model = RegistroModifica
    slug = "registro"
    storico = False
    tra_aziende = True
    list_display = ["creato", "oggetto", "content_type", "azione", "utente_nome", "origine"]
    list_filter = ["azione", "origine", "content_type", "utente", "creato"]
    search_fields = ["oggetto", "utente_nome"]
    ordering = ["-creato", "-pk"]
    form_layout = [("Modifica", [("creato", "azione"), ("oggetto", "content_type"), ("utente_nome", "origine"), "modifiche"])]
    readonly_fields = ["creato", "azione", "oggetto", "content_type", "utente_nome", "origine", "modifiche"]

    def get_queryset(self, request):
        azienda_id = getattr(getattr(request, "azienda", None), "pk", None)
        filtro = Q(azienda_id=azienda_id) if azienda_id is not None else Q(pk__in=[])
        if request.user.is_superuser:
            filtro |= Q(azienda__isnull=True)
        return super().get_queryset(request).filter(filtro)

    def _perm(self, request, azione):
        return azione == "view" and super()._perm(request, azione)


def _viste_scelte():
    from core.viste import registry
    return sorted(((f"{v.modulo}.{v.slug}", f"{v.modulo} · {str(v.verbose_name_plural).capitalize()}")
                   for vv in registry._viste.values() for v in vv), key=lambda x: x[1])


def _vista_da(chiave):
    from core.viste import registry
    modulo, _, slug = (chiave or "").partition(".")
    return next((v for v in registry.viste_di(modulo) if v.slug == slug), None)


class PermessoCampoForm(forms.ModelForm):
    class Meta:
        model = PermessoCampo
        fields = ["vista", "campo", "ruolo", "livello"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vista"] = forms.ChoiceField(label="vista", choices=_viste_scelte())

    def clean(self):
        dati = super().clean()
        vista = _vista_da(dati.get("vista"))
        if vista is None:
            return dati
        try:
            f = vista.opts.get_field(dati.get("campo") or "")
        except Exception:                                  # noqa: BLE001
            self.add_error("campo", f"{vista.verbose_name_plural} non ha il campo «{dati.get('campo')}».")
            return dati
        if (getattr(f, "concrete", False) and not f.blank and not f.has_default() and not f.null
                and dati.get("livello") == PermessoCampo.NASCOSTO and f.name in vista.campi_form()):
            self.add_error("livello", "È un campo obbligatorio del form: nascosto, chi ha il ruolo non potrebbe più creare record. "
                                      "Usa «Sola lettura».")
        return dati


class RegolaRigaForm(forms.ModelForm):
    class Meta:
        model = RegolaRiga
        fields = ["vista", "ruolo", "campo", "operatore", "valore", "attiva"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vista"] = forms.ChoiceField(label="vista", choices=_viste_scelte())

    def clean(self):
        from django.contrib.auth import get_user_model

        from core import regole
        dati = super().clean()
        vista = _vista_da(dati.get("vista"))
        if vista is None:
            return dati
        try:
            f = regole.campo_del_percorso(vista.model, dati.get("campo") or "")
        except Exception:                                  # noqa: BLE001
            self.add_error("campo", f"«{dati.get('campo')}» non è un campo (o un percorso) di {vista.verbose_name_plural}.")
            return dati
        if dati.get("operatore") == "utente" and not (f.is_relation and f.related_model is get_user_model()):
            self.add_error("operatore", "«è l'utente che guarda» vale per un campo che indica un utente (es. commerciale, responsabile).")
        if dati.get("operatore") in ("uguale", "diverso", "in", "contiene", "min", "max") and not dati.get("valore"):
            self.add_error("valore", "Indica il valore.")
        return dati


@register
class PermessoCampoView(ModelView):
    """Campi nascosti o in sola lettura per ruolo: in form, dettaglio, lista, export, API e per l'assistente."""
    model = PermessoCampo
    slug = "permessi_campo"
    list_display = ["vista", "campo", "ruolo", "livello"]
    list_filter = ["ruolo", "livello", "vista"]
    search_fields = ["vista", "campo"]
    form_class = PermessoCampoForm
    form_layout = [("Permesso", [("vista", "campo"), ("ruolo", "livello")])]
    api = False


@register
class RegolaRigaView(ModelView):
    """Quali record vede chi ha un ruolo: filtri sul queryset delle viste (liste, dettagli, API, export, assistente)."""
    model = RegolaRiga
    slug = "regole_righe"
    list_display = ["vista", "ruolo", "campo", "operatore", "valore", "attiva"]
    list_filter = ["ruolo", "vista", "attiva"]
    search_fields = ["vista", "campo", "valore"]
    form_class = RegolaRigaForm
    form_layout = [("Regola", [("vista", "ruolo"), ("campo", "operatore"), "valore", "attiva"])]
    api = False


class ModelloStampaForm(forms.ModelForm):
    """Il documento si sceglie tra i report delle viste; le colonne tra quelle che quel documento permette di nascondere."""
    class Meta:
        model = ModelloStampa
        fields = ["report", "azienda", "colore", "mostra_logo", "righe_intestazione", "testo_iniziale", "testo_finale",
                  "piede", "colonne_nascoste", "attivo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core import stampe
        self.disponibili = stampe.disponibili()
        self.fields["report"] = forms.ChoiceField(label="documento", choices=[(k, e) for k, e, _ in self.disponibili])
        colonne = sorted({(c, f"{e.split(' · ')[0]}: {n}") for k, e, cc in self.disponibili for c, n in cc}, key=lambda x: x[1])
        self.fields["colonne_nascoste"] = forms.MultipleChoiceField(
            label="colonne nascoste", required=False, widget=forms.CheckboxSelectMultiple,
            choices=sorted({(c, n.split(": ", 1)[1]) for c, n in colonne}, key=lambda x: x[1]),
            help_text="valgono solo se il documento ha quella colonna")
        self.fields["colore"].widget = forms.TextInput(attrs={"type": "color"})
        segnaposto = ", ".join(f"{{{{ {k} }}}} {v}" for k, v in stampe.SEGNAPOSTO.items())
        for campo in ("testo_iniziale", "testo_finale"):
            self.fields[campo].help_text = (self.fields[campo].help_text + " · " if self.fields[campo].help_text else "") + f"segnaposto: {segnaposto}"

    def clean(self):
        from core import stampe
        dati = super().clean()
        if dati.get("colore") and not stampe.COLORE.match(dati["colore"]):
            self.add_error("colore", "Un colore come #1e3a8a.")
        doppio = ModelloStampa.objects.filter(report=dati.get("report"), azienda=dati.get("azienda")).exclude(pk=self.instance.pk)
        if dati.get("report") and doppio.exists():
            self.add_error("report", "Per questo documento e questa azienda c'è già un modello: modifica quello.")
        consentite = {c for k, _, cc in self.disponibili if k == dati.get("report") for c, _ in cc}
        dati["colonne_nascoste"] = [c for c in dati.get("colonne_nascoste") or [] if c in consentite]
        return dati


@register
class ModelloStampaView(ModelView):
    """I modelli di stampa dei documenti per azienda; nella scheda l'anteprima sull'ultimo documento vero."""
    model = ModelloStampa
    slug = "stampe"
    list_display = ["report", "azienda", "attivo", "aggiornato"]
    list_filter = ["azienda", "attivo"]
    form_class = ModelloStampaForm
    form_layout = [("Documento", [("report", "azienda"), ("colore", "mostra_logo"), "attivo"]),
                   ("Testi", ["righe_intestazione", "testo_iniziale", "testo_finale", "piede"]),
                   ("Colonne", ["colonne_nascoste"])]
    buttons = ["originale", "riattiva"]
    api = False

    def col_report(self, obj):
        from core import stampe
        return stampe.etichetta(obj.report)
    col_report.short_description = "Documento"

    def get_buttons(self, request, obj):
        nomi = {"originale"} if obj.attivo else {"riattiva"}
        return [(n, e) for n, e in super().get_buttons(request, obj) if n in nomi]

    def originale(self, request, obj):
        obj.attivo = False
        obj.save(update_fields=["attivo", "aggiornato"])
        return "Il documento torna a stamparsi com'era in origine; il modello resta qui, spento."
    originale.short_description = "Torna all'originale"
    originale.permission = "change"

    def riattiva(self, request, obj):
        obj.attivo = True
        obj.save(update_fields=["attivo", "aggiornato"])
        return "Modello di nuovo in uso."
    riattiva.short_description = "Usa di nuovo questo modello"
    riattiva.permission = "change"


@login_required
def anteprima_stampa(request, pk):
    """Il PDF dell'ultimo documento di quel tipo (dell'azienda corrente) stampato con questo modello, anche se spento."""
    from core import report, stampe
    modello = get_object_or_404(ModelloStampa, pk=pk)
    if not request.user.has_perm("core.view_modellostampa"):
        raise PermissionDenied
    vista, indice = stampe.vista_e_indice(modello.report)
    if vista is None:
        raise Http404
    obj = vista.get_queryset(request).order_by("-pk").first()
    if obj is None:
        return HttpResponse("Non c'è ancora nessun documento di questo tipo da usare per l'anteprima.", content_type="text/plain; charset=utf-8")
    contenuto = report.html(vista, request, [obj], indice, modello=modello)
    if request.GET.get("html"):
        return HttpResponse(contenuto)
    try:
        dati = report.pdf(contenuto)
    except report.ReportNonDisponibile as e:
        return HttpResponse(str(e), status=503, content_type="text/plain; charset=utf-8")
    return HttpResponse(dati, content_type="application/pdf")


class CatenaApprovazioneForm(forms.ModelForm):
    class Meta:
        model = CatenaApprovazione
        fields = ["nome", "vista", "bottone", "campo", "soglia", "azienda", "attiva"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        scelte = [(k, e) for k, e in _viste_scelte() if (_vista_da(k) and _vista_da(k).buttons)]
        self.fields["vista"] = forms.ChoiceField(label="documento", choices=scelte)

    def clean(self):
        dati = super().clean()
        vista = _vista_da(dati.get("vista"))
        if vista is None:
            return dati
        if dati.get("bottone") not in vista.buttons:
            self.add_error("bottone", "Bottoni di questo documento: " + ", ".join(vista.buttons))
        campo = dati.get("campo") or ""
        if campo:
            from django.db import models as m

            from core import regole
            try:
                f = regole.campo_del_percorso(vista.model, campo)
                if not isinstance(f, (m.IntegerField, m.DecimalField, m.FloatField)):
                    self.add_error("campo", "Serve un campo numerico (es. totale, imponibile, righe__sconto).")
            except Exception:                              # noqa: BLE001
                self.add_error("campo", f"«{campo}» non è un campo di {vista.verbose_name_plural}.")
        return dati


@register
class CatenaApprovazioneView(ModelView):
    """Le catene di approvazione dei documenti: chi deve approvare, in che ordine, oltre quale soglia."""
    model = CatenaApprovazione
    slug = "catene_approvazione"
    list_display = ["nome", "vista", "bottone", "campo", "soglia", "azienda", "attiva"]
    list_filter = ["vista", "attiva"]
    form_class = CatenaApprovazioneForm
    form_layout = [("Quando", [("nome", "attiva"), ("vista", "bottone"), ("campo", "soglia"), "azienda"])]
    inlines = [Inline(PassoApprovazione, "catena", ["ordine", "ruolo", "utente", "giorni"], titolo="Passi", extra=2)]
    api = False


@register
class RichiestaApprovazioneView(ModelView):
    """Lo storico delle richieste di approvazione, con le decisioni."""
    model = RichiestaApprovazione
    slug = "richieste_approvazione"
    list_display = ["creata", "descrizione", "catena", "stato", "passo", "richiesta_da", "chiusa_il"]
    list_filter = ["stato", "catena"]
    search_fields = ["descrizione"]
    readonly_fields = ["catena", "descrizione", "valore", "stato", "passo", "scadenza", "richiesta_da", "creata", "chiusa_il"]
    form_layout = [("Richiesta", [("descrizione", "catena"), ("stato", "passo"), ("valore", "scadenza"), ("richiesta_da", "creata"), "chiusa_il"])]
    inlines = [Inline(DecisioneApprovazione, "richiesta", ["passo", "utente", "per_conto_di", "approvata", "nota", "il"], titolo="Decisioni", extra=0)]
    api = False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class DelegaForm(forms.ModelForm):
    class Meta:
        model = Delega
        fields = ["da", "a", "dal", "al"]
        widgets = {"dal": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), "al": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def clean(self):
        dati = super().clean()
        if dati.get("dal") and dati.get("al") and dati["al"] < dati["dal"]:
            self.add_error("al", "La fine viene dopo l'inizio.")
        if dati.get("da") and dati.get("da") == dati.get("a"):
            self.add_error("a", "Una persona non si delega da sola.")
        return dati


@register
class DelegaView(ModelView):
    """Le deleghe nelle approvazioni: ognuno vede quelle che ha dato o ricevuto; chi gestisce le catene, tutte."""
    model = Delega
    slug = "deleghe"
    list_display = ["da", "a", "dal", "al"]
    form_class = DelegaForm
    form_layout = [("Delega", [("da", "a"), ("dal", "al")])]
    api = False
    per_assistente = False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.has_perm("core.change_catenaapprovazione"):
            return qs
        return qs.filter(Q(da=request.user) | Q(a=request.user))

    def get_form_class(self, request=None):
        base = super().get_form_class(request)
        if request is None or request.user.has_perm("core.change_catenaapprovazione"):
            return base

        class Form(base):                                  # gli altri delegano solo per sé
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields["da"].queryset = self.fields["da"].queryset.filter(pk=request.user.pk)
                self.fields["da"].initial = request.user.pk
        return Form

    def has_add_permission(self, request):
        return request.user.is_authenticated

    def has_view_permission(self, request, obj=None):
        return request.user.is_authenticated

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("core.change_catenaapprovazione") or (obj is not None and obj.da_id == request.user.pk)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)


@login_required
def da_approvare(request):
    from core import approvazioni
    voci = []
    for r in approvazioni.da_decidere(request.user):
        obj = r.record
        vista = registry_viste.per_modello(type(obj)) if obj is not None else None
        voci.append({"r": r, "url": vista.url("dettaglio", pk=obj.pk) if vista else ""})
    return render(request, "core/approvazioni.html", {"voci": voci})


@login_required
@require_POST
def decidi_approvazione(request, pk):
    from core import approvazioni
    richiesta = get_object_or_404(RichiestaApprovazione, pk=pk)
    try:
        approvazioni.decidi(richiesta, request.user, request.POST.get("esito") == "approva", request.POST.get("nota", "").strip())
    except PermissionError as e:
        raise PermissionDenied(str(e))
    messages.success(request, "Decisione registrata.")
    prossimo = request.POST.get("da", "")
    return redirect(prossimo if prossimo and url_has_allowed_host_and_scheme(prossimo, {request.get_host()}) else "core:da_approvare")


class ReportPianificatoForm(forms.ModelForm):
    class Meta:
        model = ReportPianificato
        fields = ["nome", "tipo", "riferimento", "parametri", "formato", "frequenza", "giorno_settimana", "giorno_mese", "ora",
                  "destinatari", "attivo"]
        widgets = {"ora": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"), "destinatari": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        from core import report_pianificati as rp
        self.request = request
        tipi = rp.tipi()
        self.fields["tipo"] = forms.ChoiceField(label="che cosa", choices=[(k, v["etichetta"]) for k, v in tipi.items()])
        scelte = []
        for codice, voce in tipi.items():
            if voce.get("scelte") and request is not None:
                scelte += [(r, f"{voce['etichetta']}: {e}") for r, e in voce["scelte"](request)]
        self.fields["riferimento"] = forms.ChoiceField(label="vista o pagina", choices=scelte)
        if request is not None and not self.instance.pk:
            for campo in ("tipo", "riferimento", "parametri", "formato"):
                if request.GET.get(campo):
                    self.initial[campo] = request.GET[campo]
            self.initial.setdefault("destinatari", request.user.email)

    def clean(self):
        from core import report_pianificati as rp
        dati = super().clean()
        tipo = rp.tipi().get(dati.get("tipo"))
        if tipo and dati.get("formato") not in tipo["formati"]:
            self.add_error("formato", "Formati possibili: " + ", ".join(tipo["formati"]))
        if not 1 <= (dati.get("giorno_mese") or 1) <= 28:
            self.add_error("giorno_mese", "Da 1 a 28.")
        validi = [d for d in ReportPianificato(destinatari=dati.get("destinatari", "")).elenco_destinatari()]
        if not validi:
            self.add_error("destinatari", "Almeno un indirizzo email.")
        return dati


@register
class ReportPianificatoView(ModelView):
    """Gli invii periodici per email: ognuno vede i suoi; partono con i permessi di chi li ha creati."""
    model = ReportPianificato
    slug = "report_pianificati"
    list_display = ["nome", "tipo", "frequenza", "prossimo_invio", "ultimo_invio", "ultimo_esito", "attivo"]
    list_filter = ["tipo", "frequenza", "attivo"]
    search_fields = ["nome", "destinatari"]
    form_class = ReportPianificatoForm
    form_layout = [("Che cosa", [("nome", "attivo"), ("tipo", "riferimento"), "parametri", "formato"]),
                   ("Quando", [("frequenza", "ora"), ("giorno_settimana", "giorno_mese")]),
                   ("A chi", ["destinatari"])]
    readonly_fields = ["prossimo_invio", "ultimo_invio", "ultimo_esito"]
    buttons = ["invia_ora"]
    api = False
    per_assistente = False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(utente=request.user)

    def get_form_class(self, request=None):
        base = super().get_form_class(request)

        class Form(base):
            def __init__(self, *args, **kwargs):
                kwargs.setdefault("request", request)
                super().__init__(*args, **kwargs)
        return Form

    def save_model(self, request, obj, form, change):
        from core import report_pianificati as rp
        if not change:
            obj.utente, obj.azienda = request.user, getattr(request, "azienda", None)
        obj.prossimo_invio = rp.prossimo(obj) if obj.attivo else None
        super().save_model(request, obj, form, change)

    def invia_ora(self, request, obj):
        from core import report_pianificati as rp
        return rp.esegui(obj, aggiorna=False) + " (invio di prova: la pianificazione non cambia)."
    invia_ora.short_description = "Invia ora"
    invia_ora.permission = "view"


@login_required
def chiave_push(request):
    from core import push
    return JsonResponse({"chiave": push.chiave_pubblica()})


@login_required
@require_POST
def iscrivi_push(request):
    """Il browser manda la sua iscrizione push (endpoint e chiavi): da ora le notifiche arrivano anche lì."""
    import json as _json

    from core import rete
    try:
        dati = _json.loads(request.body or b"{}")
        endpoint, chiavi = dati["endpoint"], dati["keys"]
        rete.controlla(endpoint, solo_https=True)
    except (ValueError, KeyError, TypeError, rete.Rifiutato):
        return JsonResponse({"errore": "iscrizione non valida"}, status=400)
    if dati.get("disattiva"):
        IscrizionePush.objects.filter(endpoint=endpoint, utente=request.user).delete()
        return JsonResponse({"ok": True, "attiva": False})
    IscrizionePush.objects.update_or_create(endpoint=endpoint[:600], defaults={
        "utente": request.user, "p256dh": str(chiavi.get("p256dh", ""))[:200], "auth": str(chiavi.get("auth", ""))[:60],
        "dispositivo": request.headers.get("User-Agent", "")[:200]})
    return JsonResponse({"ok": True, "attiva": True})


@login_required
@require_POST
def prova_push(request):
    from core import push
    n = push.invia(request.user.pk, "Notifiche attive", "Da ora le notifiche arrivano anche qui.", reverse("core:tasca"))
    return JsonResponse({"inviate": n})


@login_required
def tasca(request):
    """«In tasca»: la pagina per il telefono, con le cose da fare in giro (solo quelle che l'utente può usare)."""
    from core import approvazioni
    voci = []

    def voce(etichetta, url_name, icona, permesso=None, conta=None, sotto=""):
        if permesso and not request.user.has_perm(permesso):
            return
        try:
            url = reverse(url_name)
        except NoReverseMatch:
            return
        voci.append({"etichetta": etichetta, "url": url, "icona": icona, "conta": conta, "sotto": sotto})
    da_fare = attivita_servizio.da_fare_oggi(request.user)
    voce("Le mie attività", "core:attivita", "check", conta=da_fare or None, sotto="da fare oggi" if da_fare else "")
    n = len(approvazioni.da_decidere(request.user))
    voce("Da approvare", "core:da_approvare", "shield", conta=n or None)
    if apps.is_installed("personale") and getattr(request.user, "dipendente", None) is not None:
        voce("Timbra", "personale:timbra_io", "check", sotto="entrata e uscita")
    voce("Nuova nota spese", "spese:note_nuovo", "plus", "spese.add_notaspese", sotto="con la foto dello scontrino")
    voce("Giacenze", "magazzino:giacenze", "search", "magazzino.view_movimento")
    voce("Reception", "reception:chiosco", "users", "reception.add_visita")
    voce("Chat con Ada", "ai:chat", "zap", "ai.add_conversazione")
    voce("Messaggi", "discuss:home", "inbox", "discuss.view_canale")
    voce("Dashboard", "core:dashboard", "home")
    return render(request, "core/tasca.html", {"voci": voci, "push": IscrizionePush.objects.filter(utente=request.user).count()})
