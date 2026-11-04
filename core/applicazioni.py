"""Il catalogo delle applicazioni per l'amministratore del cliente: quelle attive e quelle che si possono aggiungere.
Delle app non comprate arriva dal portale solo la descrizione, mai il codice; «Richiedi» avvisa ICHNOBYTE, che le
abilita sul portale, e al giro successivo l'istanza le scarica e le installa."""
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.mail import send_mail
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import lavori, licenza
from .models import LicenzaIstanza, RichiestaModulo
from .registry import modules, sincronia

log = logging.getLogger("core.moduli")
PERMESSO = "core.view_modulo"
ICONA_AMMESSA = "data:image/svg+xml;base64,"
ATTIVA, SOSPESA, IN_ARRIVO, RICHIESTA, DISPONIBILE = "attiva", "sospesa", "in_arrivo", "richiesta", "disponibile"
ETICHETTE = {ATTIVA: "Attiva", SOSPESA: "Sospesa", IN_ARRIVO: "In arrivo", RICHIESTA: "Richiesta inviata", DISPONIBILE: "Disponibile"}
ALTRE = "Altre"


def _voce(slug, nome, riassunto, categoria, icona="", statica=""):
    return {"slug": slug, "nome": nome, "riassunto": riassunto, "categoria": categoria or ALTRE,
            "icona": icona if icona.startswith(ICONA_AMMESSA) else "", "statica": statica, "iniziale": (nome or slug)[:1].upper()}


def voci():
    """Tutte le app che questa istanza può vedere, con il loro stato."""
    obbligatoria, stato = licenza.obbligatoria(), licenza.attuale()
    riga = LicenzaIstanza.objects.first()
    catalogo = riga.catalogo if riga else {}
    trovate = {}
    for v in [*catalogo.get("moduli", []), *catalogo.get("disponibili", [])]:
        if v.get("application", True):
            trovate[v["slug"]] = _voce(v["slug"], v.get("nome", v["slug"]), v.get("riassunto", ""), v.get("categoria", ""), v.get("icona", ""))
    installati = set(modules.installati())
    for slug, info in modules.scopri().items():
        m = info.manifest
        if m is None or not m.application or (obbligatoria and slug not in stato.moduli):
            continue
        statica = (m.icon or "") if slug in installati and "/" in (m.icon or "") else ""
        icona = trovate.get(slug, {}).get("icona", "")
        trovate[slug] = _voce(slug, m.nav_label or m.name, m.summary, m.category, icona, statica)
    spenti, chieste = modules.disattivati(), set(RichiestaModulo.objects.filter(stato=RichiestaModulo.INVIATA).values_list("slug", flat=True))
    for slug, v in trovate.items():
        if slug in installati:
            v["stato"] = SOSPESA if slug in spenti else ATTIVA
        elif slug in stato.moduli:
            v["stato"] = IN_ARRIVO
        else:
            v["stato"] = RICHIESTA if slug in chieste else DISPONIBILE
        v["etichetta"] = ETICHETTE[v["stato"]]
    return sorted(trovate.values(), key=lambda v: (v["categoria"] == ALTRE, v["categoria"].lower(), v["nome"].lower()))


@login_required
@permission_required(PERMESSO, raise_exception=True)
def pagina(request):
    tutte = voci()
    return render(request, "core/applicazioni.html", {
        "attive": [v for v in tutte if v["stato"] in (ATTIVA, SOSPESA, IN_ARRIVO)],
        "altre": [v for v in tutte if v["stato"] in (DISPONIBILE, RICHIESTA)],
        "categorie": sorted({v["categoria"] for v in tutte if v["stato"] in (DISPONIBILE, RICHIESTA)}),
        "licenza": licenza.attuale(), "obbligatoria": licenza.obbligatoria(), "utenti_attivi": licenza.utenti_attivi(),
        "portale": sincronia.configurata()})


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def richiedi(request):
    slug = request.POST.get("slug", "")
    voce = next((v for v in voci() if v["slug"] == slug and v["stato"] == DISPONIBILE), None)
    if voce is None:
        raise Http404
    RichiestaModulo.objects.create(slug=slug, nome=voce["nome"], nota=request.POST.get("nota", "").strip()[:2000], utente=request.user)
    lavori.accoda("core.registry.sincronia.invia_richieste")
    if settings.LICENZA_EMAIL_RICHIESTE:
        send_mail(f"Richiesta del modulo {voce['nome']}", f"{request.user} ha chiesto «{voce['nome']}» ({slug}) su {request.get_host()}.\n\n{request.POST.get('nota', '')}",
                  None, [settings.LICENZA_EMAIL_RICHIESTE], fail_silently=True)
    messages.success(request, f"Richiesta di «{voce['nome']}» inviata: ti ricontatteremo per attivarla.")
    return redirect("core:applicazioni")
