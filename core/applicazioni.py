"""Le applicazioni viste dall'amministratore del cliente, senza passare dall'admin di Django.

Tre sezioni: quelle attive; quelle installate ma spente, che arrivano così dal portale e che accende lui, decidendo chi le
usa; quelle acquistabili, in grigio, con «Guarda la demo», «Richiedi una demo» e «Richiedi l'installazione». Di queste
ultime arriva dal portale solo la descrizione, mai il codice. Se il portale ammette l'acquisto diretto, quelle con un
prezzo si comprano da qui («Acquista»): entrano in licenza alla sincronizzazione che parte subito, senza approvazione.
Ciò che è stato comprato si disdice da qui («Disdici») per la fine dei 30 giorni in corso: il giorno lo dice il catalogo."""
import datetime
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import dipartimenti, lavori, licenza, ruoli
from .models import Dipartimento, LicenzaIstanza, Modulo, RichiestaModulo, Ruolo
from .registry import modules, sincronia
from .signals import crea_profilo

log = logging.getLogger("core.moduli")
PERMESSO = "core.view_modulo"
PERMESSO_ATTIVAZIONE = "core.change_modulo"
ICONA_AMMESSA = "data:image/svg+xml;base64,"
ATTIVA, NON_ATTIVA, IN_ARRIVO, RICHIESTA, DISPONIBILE = "attiva", "non_attiva", "in_arrivo", "richiesta", "disponibile"
ETICHETTE = {ATTIVA: "Attiva", NON_ATTIVA: "Non attiva", IN_ARRIVO: "In arrivo", RICHIESTA: "Installazione richiesta", DISPONIBILE: "Disponibile"}
ALTRE = "Altre"
SPIEGAZIONI = [("Nessuno", "Non vede l'app."), ("Lettura", "Consulta i dati, senza modificarli."),
               ("Lavoro", "Lavora nell'app: crea e modifica."), ("Responsabile", "Tutto, comprese approvazioni e configurazione dell'app.")]


def _voce(slug, nome, riassunto, categoria, icona="", statica=""):
    return {"slug": slug, "nome": nome, "riassunto": riassunto, "categoria": categoria or ALTRE, "descrizione": "", "funzioni": [], "url_demo": "",
            "demo_chiesta": False, "icona": icona if icona.startswith(ICONA_AMMESSA) else "", "statica": statica, "iniziale": (nome or slug)[:1].upper()}


def _prezzo(dal_catalogo):
    """Il prezzo al mese di una voce che il portale lascia comprare da qui, o None: senza «acquisto» resta la richiesta."""
    if dal_catalogo.get("acquisto") is not True:
        return None
    try:
        prezzo = Decimal(str(dal_catalogo.get("prezzo_mese")))
    except InvalidOperation:
        return None
    return prezzo.quantize(Decimal("0.01")) if prezzo.is_finite() and 0 < prezzo < 1_000_000 else None


def _giorno(valore):
    try:
        return datetime.date.fromisoformat(valore) if isinstance(valore, str) else None
    except ValueError:
        return None


def _disdetta(voce, dal_catalogo):
    """Dal catalogo: `disdetta_fine`, il giorno da cui varrebbe una disdetta di oggi (None = non si disdice da qui), e
    `termina`, il giorno di una disdetta già data. Gli `…_ultimo` sono l'ultimo giorno in cui l'app c'è e si paga."""
    un_giorno = datetime.timedelta(days=1)
    voce["disdetta_fine"], voce["termina"] = _giorno(dal_catalogo.get("disdetta")), _giorno(dal_catalogo.get("termina"))
    voce["disdetta_ultimo"] = voce["disdetta_fine"] - un_giorno if voce["disdetta_fine"] else None
    voce["termina_ultimo"] = voce["termina"] - un_giorno if voce["termina"] else None


def _scheda(voce, dal_catalogo):
    """La parte commerciale del catalogo: che cosa fa, che cosa offre, dove si vede la demo."""
    demo = str(dal_catalogo.get("url_demo") or "")
    voce.update(descrizione=str(dal_catalogo.get("descrizione") or ""), funzioni=list(dal_catalogo.get("funzioni") or []),
                url_demo=demo if demo.startswith(("https://", "http://")) else "", prezzo_mese=_prezzo(dal_catalogo))
    _disdetta(voce, dal_catalogo)


def voci():
    """Tutte le app che questa istanza può vedere, con il loro stato."""
    obbligatoria, stato = licenza.obbligatoria(), licenza.attuale()
    riga = LicenzaIstanza.objects.first()
    catalogo = riga.catalogo if riga else {}
    trovate = {}
    for v in [*catalogo.get("moduli", []), *catalogo.get("disponibili", [])]:
        if v.get("application", True):
            trovate[v["slug"]] = _voce(v["slug"], v.get("nome", v["slug"]), v.get("riassunto", ""), v.get("categoria", ""), v.get("icona", ""))
            _scheda(trovate[v["slug"]], v)
    installati = set(modules.installati())
    nomi = modules.etichette()
    for slug, info in modules.scopri().items():
        m = info.manifest
        if m is None or not m.application or (obbligatoria and slug not in stato.moduli):
            continue
        statica = (m.icon or "") if slug in installati and "/" in (m.icon or "") else ""
        dal_catalogo = trovate.get(slug, {})
        trovate[slug] = _voce(slug, nomi.get(slug) or m.nav_label or m.name, m.summary, m.category, dal_catalogo.get("icona", ""), statica)
        _scheda(trovate[slug], dal_catalogo)
        for chiave in ("prezzo_mese", "disdetta_fine", "disdetta_ultimo", "termina", "termina_ultimo"):
            trovate[slug][chiave] = dal_catalogo.get(chiave)                # già letti dal catalogo qui sopra
        trovate[slug]["nome_originale"] = m.nav_label or m.name
        trovate[slug]["funzioni"] = trovate[slug]["funzioni"] or [v["label"] for v in m.menu]    # senza scheda, le sue pagine
    spente = set(Modulo.objects.filter(disattivato=True).values_list("slug", flat=True))
    fuori = licenza.fuori_licenza()
    aperte = RichiestaModulo.objects.filter(stato=RichiestaModulo.INVIATA)
    chieste = set(aperte.filter(tipo=RichiestaModulo.INSTALLAZIONE).values_list("slug", flat=True))
    in_acquisto = set(aperte.filter(tipo=RichiestaModulo.INSTALLAZIONE, acquisto=True).values_list("slug", flat=True))
    in_disdetta = set(aperte.filter(tipo=RichiestaModulo.DISDETTA).values_list("slug", flat=True))
    demo = set(RichiestaModulo.objects.filter(tipo=RichiestaModulo.DEMO).values_list("slug", flat=True))
    for slug, v in trovate.items():
        if slug in installati and slug not in fuori:
            v["stato"] = NON_ATTIVA if slug in spente else ATTIVA
        elif slug in stato.moduli:
            v["stato"] = IN_ARRIVO
        else:
            v["stato"] = RICHIESTA if slug in chieste else DISPONIBILE
        v["etichetta"] = "Acquisto in corso" if v["stato"] == RICHIESTA and slug in in_acquisto else ETICHETTE[v["stato"]]
        v["demo_chiesta"] = slug in demo
        v["in_disdetta"] = slug in in_disdetta
    return sorted(trovate.values(), key=lambda v: (v["categoria"] == ALTRE, v["categoria"].lower(), v["nome"].lower()))


def suite():
    """Le suite del catalogo: pacchetti di app per dipartimento. [{slug, nome, descrizione, app, utenti, stato, posti}]
    con stato «comprata», «richiesta», «rifiutata» o «disponibile»; `prezzo_mese` se si compra da qui, `in_acquisto`
    se l'acquisto è partito e la suite deve ancora arrivare."""
    riga = LicenzaIstanza.objects.first()
    catalogo = riga.catalogo if riga else {}
    stato = licenza.attuale()
    comprate = {s["slug"] for s in stato.suite} if stato.valida else set()
    aperte = RichiestaModulo.objects.filter(tipo=RichiestaModulo.SUITE)
    chieste = set(aperte.filter(stato=RichiestaModulo.INVIATA).values_list("slug", flat=True))
    in_acquisto = set(aperte.filter(stato=RichiestaModulo.INVIATA, acquisto=True).values_list("slug", flat=True))
    in_disdetta = set(RichiestaModulo.objects.filter(tipo=RichiestaModulo.DISDETTA_SUITE, stato=RichiestaModulo.INVIATA).values_list("slug", flat=True))
    no = set(aperte.filter(stato=RichiestaModulo.RIFIUTATA).values_list("slug", flat=True)) - chieste
    posti = {r["slug"]: r for r in dipartimenti.posti_suite()} if comprate else {}
    voci = []
    for v in catalogo.get("suite") or []:
        if not isinstance(v, dict) or not v.get("slug"):
            continue
        slug = str(v["slug"])
        voce = {"slug": slug, "nome": str(v.get("nome") or slug), "descrizione": str(v.get("descrizione") or ""),
                "app": [str(m.get("nome") or m.get("slug")) for m in v.get("moduli") or [] if isinstance(m, dict)],
                "utenti": v.get("utenti") if isinstance(v.get("utenti"), int) else 0, "posti": posti.get(slug),
                "dipartimento": Dipartimento.objects.filter(suite=slug).first(), "prezzo_mese": _prezzo(v), "in_acquisto": slug in in_acquisto,
                "in_disdetta": slug in in_disdetta}
        _disdetta(voce, v)
        voce["stato"] = "comprata" if slug in comprate else "richiesta" if slug in chieste else "rifiutata" if slug in no else "disponibile"
        voci.append(voce)
    return sorted(voci, key=lambda v: (v["stato"] != "comprata", v["nome"].lower()))


@login_required
@permission_required(PERMESSO, raise_exception=True)
def pagina(request):
    tutte = voci()
    altre = [v for v in tutte if v["stato"] in (DISPONIBILE, RICHIESTA)]
    return render(request, "core/applicazioni.html", {
        "attive": [v for v in tutte if v["stato"] == ATTIVA], "ferme": [v for v in tutte if v["stato"] in (NON_ATTIVA, IN_ARRIVO)], "altre": altre,
        "categorie": sorted({v["categoria"] for v in altre}), "licenza": licenza.attuale(), "obbligatoria": licenza.obbligatoria(), "suite": suite(),
        "utenti_attivi": licenza.utenti_attivi(), "portale": sincronia.configurata(),
        "puo_comprare": sincronia.configurata() and request.user.has_perm(PERMESSO_ATTIVAZIONE)})


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def richiedi(request):
    """Installazione o demo: la richiesta va al portale e, se impostata, per email a chi vende."""
    slug = request.POST.get("slug", "")
    if request.POST.get("tipo") == RichiestaModulo.SUITE:
        return _richiedi_suite(request, slug)
    tipo = RichiestaModulo.DEMO if request.POST.get("tipo") == RichiestaModulo.DEMO else RichiestaModulo.INSTALLAZIONE
    voce = next((v for v in voci() if v["slug"] == slug and v["stato"] in (DISPONIBILE, RICHIESTA)), None)
    if voce is None or RichiestaModulo.objects.filter(slug=slug, tipo=tipo, stato=RichiestaModulo.INVIATA).exists():
        raise Http404
    nota = request.POST.get("nota", "").strip()[:2000]
    RichiestaModulo.objects.create(slug=slug, nome=voce["nome"], nota=nota, tipo=tipo, utente=request.user)
    lavori.accoda("core.registry.sincronia.invia_richieste")
    cosa = "una demo" if tipo == RichiestaModulo.DEMO else "l'installazione"
    if settings.LICENZA_EMAIL_RICHIESTE:
        send_mail(f"Richiesta di {cosa}: {voce['nome']}", f"{request.user} ha chiesto {cosa} di «{voce['nome']}» ({slug}) su {request.get_host()}.\n\n{nota}",
                  None, [settings.LICENZA_EMAIL_RICHIESTE], fail_silently=True)
    messages.success(request, f"Richiesta inviata: ti ricontatteremo per {cosa} di «{voce['nome']}».")
    return redirect("core:applicazioni")


@login_required
@permission_required(PERMESSO_ATTIVAZIONE, raise_exception=True)
@require_POST
def acquista(request):
    """L'acquisto diretto di un'app o di una suite al prezzo del catalogo: parte subito la sincronizzazione, il portale
    la mette in licenza e l'istanza la installa. Chi compra impegna l'azienda: serve il permesso di attivare le app, e
    il prezzo confermato deve essere quello mostrato (il portale lo ricontrolla con il suo)."""
    slug, di_suite = request.POST.get("slug", ""), request.POST.get("tipo") == RichiestaModulo.SUITE
    if di_suite:
        voce = next((v for v in suite() if v["slug"] == slug and v["stato"] in ("disponibile", "rifiutata")), None)
    else:
        voce = next((v for v in voci() if v["slug"] == slug and v["stato"] == DISPONIBILE), None)
    if voce is None or voce["prezzo_mese"] is None or not sincronia.configurata():
        raise Http404
    try:
        confermato = Decimal(request.POST.get("prezzo", ""))
    except InvalidOperation:
        confermato = None
    if confermato != voce["prezzo_mese"]:
        messages.error(request, f"Il prezzo di «{voce['nome']}» è cambiato: ora è {voce['prezzo_mese']} € al mese. Niente è stato comprato.")
        return redirect("core:applicazioni")
    if request.POST.get("conferma") != "1":
        messages.error(request, f"Per comprare «{voce['nome']}» conferma il prezzo con la spunta.")
        return redirect("core:applicazioni")
    tipo = RichiestaModulo.SUITE if di_suite else RichiestaModulo.INSTALLAZIONE
    with transaction.atomic():
        aperta = RichiestaModulo.objects.select_for_update().filter(slug=slug, tipo=tipo, stato=RichiestaModulo.INVIATA).first()
        if aperta is not None:                           # doppio clic, o una richiesta già in attesa di una persona
            raise Http404
        RichiestaModulo.objects.create(slug=slug, nome=voce["nome"], tipo=tipo, utente=request.user, acquisto=True, prezzo_mese=voce["prezzo_mese"])
    lavori.accoda("core.registry.sincronia.esegui")
    cosa = "della suite" if di_suite else "di"
    if settings.LICENZA_EMAIL_RICHIESTE:
        send_mail(f"Acquisto {cosa} {voce['nome']}", f"{request.user} ha comprato {'la suite ' if di_suite else ''}«{voce['nome']}» ({slug}) "
                  f"a {voce['prezzo_mese']} € al mese su {request.get_host()}.", None, [settings.LICENZA_EMAIL_RICHIESTE], fail_silently=True)
    messages.success(request, f"«{voce['nome']}» comprata a {voce['prezzo_mese']} € al mese: arriva tra pochi minuti"
                              + (" con il suo dipartimento." if di_suite else " tra le app installate, da attivare."))
    return redirect("core:applicazioni")


@login_required
@permission_required(PERMESSO_ATTIVAZIONE, raise_exception=True)
@require_POST
def disdici(request):
    """La disdetta di un'app o di una suite comprata, per la fine dei 30 giorni in corso: fino a quel giorno resta e
    si paga, poi il portale la toglie dalla licenza (i dati restano). Il giorno confermato deve essere quello mostrato;
    il portale lo ricontrolla con il suo, e l'esito torna nel catalogo («termina il…»)."""
    slug, di_suite = request.POST.get("slug", ""), request.POST.get("tipo") == RichiestaModulo.SUITE
    if di_suite:
        voce = next((v for v in suite() if v["slug"] == slug and v["stato"] == "comprata"), None)
    else:
        voce = next((v for v in voci() if v["slug"] == slug and v["stato"] in (ATTIVA, NON_ATTIVA, IN_ARRIVO)), None)
    if voce is None or voce["disdetta_fine"] is None or voce["in_disdetta"] or not sincronia.configurata():
        raise Http404
    if request.POST.get("fine") != voce["disdetta_fine"].isoformat():
        messages.error(request, f"La data è cambiata: disdicendo «{voce['nome']}» adesso resta fino al {voce['disdetta_ultimo']:%d/%m/%Y}. Niente è stato disdetto.")
        return redirect("core:applicazioni")
    if request.POST.get("conferma") != "1":
        messages.error(request, f"Per disdire «{voce['nome']}» conferma con la spunta.")
        return redirect("core:applicazioni")
    tipo = RichiestaModulo.DISDETTA_SUITE if di_suite else RichiestaModulo.DISDETTA
    with transaction.atomic():
        if RichiestaModulo.objects.select_for_update().filter(slug=slug, tipo=tipo, stato=RichiestaModulo.INVIATA).exists():
            raise Http404                                # doppio clic
        RichiestaModulo.objects.create(slug=slug, nome=voce["nome"], tipo=tipo, utente=request.user, fine=voce["disdetta_fine"])
    lavori.accoda("core.registry.sincronia.esegui")
    if settings.LICENZA_EMAIL_RICHIESTE:
        send_mail(f"Disdetta {'della suite' if di_suite else 'di'} {voce['nome']}", f"{request.user} ha disdetto {'la suite ' if di_suite else ''}«{voce['nome']}» ({slug}) "
                  f"su {request.get_host()}: termina il {voce['disdetta_fine']:%d/%m/%Y}.", None, [settings.LICENZA_EMAIL_RICHIESTE], fail_silently=True)
    messages.success(request, f"«{voce['nome']}» disdetta: resta attiva e si paga fino al {voce['disdetta_ultimo']:%d/%m/%Y}, poi viene tolta. I dati restano.")
    return redirect("core:applicazioni")


def _richiedi_suite(request, slug):
    """Una suite intera con una sola richiesta: la decide ICHNOBYTE, poi arrivano le app e il dipartimento."""
    voce = next((v for v in suite() if v["slug"] == slug and v["stato"] in ("disponibile", "rifiutata")), None)
    if voce is None:
        raise Http404
    nota = request.POST.get("nota", "").strip()[:2000]
    RichiestaModulo.objects.create(slug=slug, nome=voce["nome"], nota=nota, tipo=RichiestaModulo.SUITE, utente=request.user)
    lavori.accoda("core.registry.sincronia.invia_richieste")
    if settings.LICENZA_EMAIL_RICHIESTE:
        send_mail(f"Richiesta della suite {voce['nome']}", f"{request.user} ha chiesto la suite «{voce['nome']}» ({slug}) su {request.get_host()}.\n\n{nota}",
                  None, [settings.LICENZA_EMAIL_RICHIESTE], fail_silently=True)
    messages.success(request, f"Richiesta inviata: ti ricontatteremo per la suite «{voce['nome']}».")
    return redirect("core:applicazioni")


@login_required
@permission_required(PERMESSO_ATTIVAZIONE, raise_exception=True)
@require_POST
def attivazione(request):
    """Accende o spegne un'app installata e coperta dalla licenza. Accesa, si passa a decidere chi la usa."""
    slug, attivo = request.POST.get("slug", ""), request.POST.get("attivo") == "1"
    voce = next((v for v in voci() if v["slug"] == slug and v["stato"] in (ATTIVA, NON_ATTIVA)), None)
    if voce is None:
        raise Http404
    if not attivo and (servono := modules.dipendenti_attivi(slug)):
        messages.error(request, f"«{voce['nome']}» serve a {', '.join(servono)}: disattiva prima quelle.")
        return redirect("core:applicazioni")
    modules.imposta_attivo(slug, attivo)
    if attivo:
        messages.success(request, f"«{voce['nome']}» è attiva: decidi chi può usarla.")
        return redirect("core:applicazione", slug=slug)
    messages.success(request, f"«{voce['nome']}» disattivata: nascosta a tutti, i dati restano.")
    return redirect("core:applicazioni")


def _gestibile(slug):
    """(voce, manifest) di un'app installata e coperta dalla licenza."""
    voce = next((v for v in voci() if v["slug"] == slug and v["stato"] in (ATTIVA, NON_ATTIVA)), None)
    info = modules.scopri().get(slug)
    if voce is None or info is None or info.manifest is None:
        raise Http404
    return voce, info.manifest


@login_required
@permission_required(PERMESSO_ATTIVAZIONE, raise_exception=True)
def scheda(request, slug):
    """Chi può usare l'app e che cosa può farci: il livello di ogni ruolo e le eccezioni delle singole persone."""
    from .utenti import _cella
    voce, manifest = _gestibile(slug)
    righe_ruoli = [{"r": r, "scelto": r.livelli.get(slug, ""), "base": ruoli.ETICHETTE[r.livello_base], "tecnico": r.tecnico}
                   for r in Ruolo.objects.all()]
    persone = []
    for u in get_user_model().objects.filter(is_active=True).exclude(profilo__esterno=True).select_related("profilo", "profilo__ruolo").prefetch_related("groups"):
        persone.append({"u": u, "ruolo": getattr(crea_profilo(u).ruolo, "nome", ""), "cella": _cella(u, crea_profilo(u), slug, manifest)})
    return render(request, "core/applicazione.html", {
        "v": voce, "con_permessi": bool(manifest.groups), "righe_ruoli": righe_ruoli, "persone": persone, "livelli": ruoli.LIVELLI, "spiegazioni": SPIEGAZIONI,
        "comune": Modulo.objects.filter(slug=slug, comune=True).exists(), "applicazione": manifest.application,
        "voci_menu": _voci_menu(slug, manifest, request.GET.get("ruolo")), "ruoli_menu": Ruolo.objects.all(),
        "ruolo_menu": request.GET.get("ruolo", ""),
        "dipartimenti": [{"d": d, "scelto": d.tutte or slug in d.app, "tutte": d.tutte} for d in Dipartimento.objects.all()],
        "portata_da": [d for d in Dipartimento.objects.all() if not d.tutte and slug not in d.app and slug in dipartimenti.con_dipendenze(d.app)]})


@login_required
@permission_required("core.change_ruolo", raise_exception=True)
@require_POST
def ruolo(request, slug):
    """Il livello di un ruolo in quest'app: il segnale del ruolo lo applica subito a chi lo ha."""
    voce, _ = _gestibile(slug)
    valore = request.POST.get("livello", "")
    r = Ruolo.objects.filter(pk=request.POST.get("ruolo") if str(request.POST.get("ruolo", "")).isdigit() else None).first()
    if r is None or (valore and valore not in ruoli.ETICHETTE):
        return HttpResponseBadRequest("ruolo o livello non valido")
    if r.tecnico and not request.user.is_superuser:
        raise PermissionDenied
    if valore:
        r.livelli[slug] = valore
    else:
        r.livelli.pop(slug, None)
    r.save()
    messages.success(request, f"{r}: {ruoli.ETICHETTE.get(valore, 'come tutte le app')} in «{voce['nome']}».")
    return redirect(reverse("core:applicazione", args=[slug]))


@login_required
@permission_required(PERMESSO_ATTIVAZIONE, raise_exception=True)
@require_POST
def nome(request, slug):
    """Il nome dell'app nel menu, per tutta l'istanza. Vuoto, torna quello del modulo."""
    voce, _ = _gestibile(slug)
    nuovo = " ".join(request.POST.get("etichetta", "").split())[:40]
    Modulo.objects.filter(slug=slug).update(etichetta="" if nuovo == voce["nome_originale"] else nuovo)
    messages.success(request, f"Nel menu ora si chiama «{nuovo}»." if nuovo else f"Nel menu torna a chiamarsi «{voce['nome_originale']}».")
    return redirect("core:applicazione", slug=slug)



def _voci_menu(slug, manifest, ruolo):
    from .models import VoceMenu
    ruolo_id = int(ruolo) if ruolo and ruolo.isdigit() else None
    cambi = {v.url_name: v for v in VoceMenu.objects.filter(modulo=slug, ruolo_id=ruolo_id)}
    return [{"url_name": v["url_name"], "originale": v["label"], "cambio": cambi.get(v["url_name"]), "posizione": i * 10}
            for i, v in enumerate(manifest.menu)]


@login_required
@permission_required("core.change_modulo", raise_exception=True)
@require_POST
def menu_app(request, slug):
    """Nome, posizione e visibilità delle voci di menu interne dell'app, per tutti o per un ruolo."""
    from .models import VoceMenu
    voce, manifest = _gestibile(slug)
    ruolo = Ruolo.objects.filter(pk=request.POST.get("ruolo")).first() if request.POST.get("ruolo", "").isdigit() else None
    for i, v in enumerate(manifest.menu):
        chiave = v["url_name"]
        etichetta = " ".join(request.POST.get(f"nome_{i}", "").split())[:60]
        etichetta = "" if etichetta == v["label"] else etichetta
        nascosta = request.POST.get(f"nascosta_{i}") == "1"
        testo = request.POST.get(f"ordine_{i}", "").strip()
        ordine = int(testo) if testo.isdigit() and int(testo) != i * 10 else None
        if etichetta or nascosta or ordine is not None:
            VoceMenu.objects.update_or_create(modulo=slug, url_name=chiave, ruolo=ruolo,
                                              defaults={"etichetta": etichetta, "nascosta": nascosta, "ordine": ordine})
        else:
            VoceMenu.objects.filter(modulo=slug, url_name=chiave, ruolo=ruolo).delete()
    messages.success(request, "Voci di menu salvate" + (f" per il ruolo {ruolo}." if ruolo else " per tutti."))
    return redirect(f"{redirect('core:applicazione', slug=slug).url}{'?ruolo=' + str(ruolo.pk) if ruolo else ''}")


@login_required
@permission_required("core.change_dipartimento", raise_exception=True)
@require_POST
def dipartimenti_app(request, slug):
    """Comune a tutti, o solo per i dipartimenti spuntati: il segnale dei dipartimenti lo applica a chi ne fa parte."""
    voce, _ = _gestibile(slug)
    comune = request.POST.get("comune") == "1"
    scelti = set(request.POST.getlist("dipartimenti"))
    with transaction.atomic():
        prima = Modulo.objects.filter(slug=slug, comune=True).exists()
        if prima != comune:
            if not Modulo.objects.filter(slug=slug).exists():
                modules.sincronizza()
            Modulo.objects.filter(slug=slug).update(comune=comune)
        for d in Dipartimento.objects.filter(tutte=False):
            dentro = str(d.pk) in scelti
            if dentro != (slug in d.app):
                d.app = sorted(set(d.app) | {slug}) if dentro else [s for s in d.app if s != slug]
                d.save()
        if prima != comune:
            dipartimenti.riapplica_tutti()
    if comune:
        messages.success(request, f"«{voce['nome']}» è comune: la vedono tutti, in qualunque dipartimento.")
    else:
        messages.success(request, f"«{voce['nome']}»: la vedono i dipartimenti scelti e chi non ha dipartimenti.")
    return redirect("core:applicazione", slug=slug)
