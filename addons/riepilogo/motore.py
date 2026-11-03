"""Mette insieme le voci dei moduli nell'ordine delle sezioni, solo per i moduli che l'utente vede."""
import datetime
import logging

from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.text import slugify

from core import attivita, parametri
from core import riepilogo as contratto
from core.generici import url_record
from core.lavori import risolvi
from core.registry import modules
from core.riepilogo import ATTENZIONE, NOVITA, OGGI, voce

log = logging.getLogger(__name__)
SCELTE = [("accesso", "dall'ultimo accesso"), ("ieri", "da ieri"), ("settimana", "dagli ultimi 7 giorni"), ("mese", "dagli ultimi 30 giorni")]


def saluto(utente, adesso=None):
    ora = timezone.localtime(adesso or timezone.now()).hour
    parola = "Buongiorno" if ora < 13 else "Buon pomeriggio" if ora < 18 else "Buonasera"
    return f"{parola}, {utente.first_name or utente.get_username()}"


def da_quando(preferenza, scelta="accesso", adesso=None):
    """(istante, descrizione). Mai oltre i giorni massimi: dopo le ferie il riepilogo non elenca mesi interi."""
    adesso = adesso or timezone.now()
    mezzanotte = timezone.localtime(adesso).replace(hour=0, minute=0, second=0, microsecond=0)
    giorni = {"ieri": 1, "settimana": 7, "mese": 30}
    if scelta in giorni:
        dal, testo = mezzanotte - datetime.timedelta(days=giorni[scelta]), dict(SCELTE)[scelta]
    elif preferenza.accesso_precedente is None:
        dal, testo = mezzanotte - datetime.timedelta(days=1), "da ieri: è il tuo primo accesso"
    else:
        locale = timezone.localtime(preferenza.accesso_precedente)
        dal, testo = preferenza.accesso_precedente, f"dal tuo ultimo accesso, {date_format(locale, 'l j F')} alle {locale:%H:%M}"
    massimo = int(parametri.leggi("riepilogo.giorni_massimi") or 30)
    limite = adesso - datetime.timedelta(days=massimo)
    if dal < limite:
        dal, testo = limite, f"{testo} (al massimo {massimo} giorni)"
    return dal, testo


def _kernel(request, dal, oggi):
    mie = attivita.mie(request.user)
    url = reverse("core:attivita")

    def righe(qs):
        return [(f"{a.tipo} · {a.riepilogo or a.record}", url_record(a.record) or "") for a in qs[:contratto.MAX_DETTAGLI]]

    nuove, di_oggi, tardi = mie.filter(creato__gte=dal).exclude(creato_da=request.user), mie.filter(scadenza=oggi), mie.filter(scadenza__lt=oggi)
    return [
        voce(NOVITA, nuove.count(), "attività pianificata nuova per te", "attività pianificate nuove per te", url, dettagli=righe(nuove)),
        voce(OGGI, di_oggi.count(), "attività pianificata per oggi", "attività pianificate per oggi", url, dettagli=righe(di_oggi)),
        voce(ATTENZIONE, tardi.count(), "attività pianificata in ritardo", "attività pianificate in ritardo", url, urgente=True, dettagli=righe(tardi)),
    ]


def chiave(slug, v):
    """Stabile finché il modulo non cambia nome alla voce: è quella che l'utente silenzia."""
    return f"{slug}:{v['sezione']}:{slugify(v['nome'])[:60]}"


def calcola(request, dal, oggi=None, rigoroso=False, silenziate=(), tutte=False):
    """{sezioni: [{codice, titolo, sottotitolo, voci}], totale, urgenti, voci}. Un modulo con un errore non ferma gli altri
    (salvo `rigoroso`, nei test). `silenziate`: le chiavi che l'utente non vuole vedere. Con `tutte` restano anche le voci a
    zero e quelle silenziate, segnate con `vuota` e `silenziata`: è il catalogo delle impostazioni."""
    oggi = oggi or timezone.localdate()
    raccolte = [("core", "Attività pianificate", v) for v in _kernel(request, dal, oggi)]
    spenti = modules.disattivati()
    visibili = {a["slug"] for a in modules.app_visibili(request.user)}
    for slug, m in modules.manifests_attivi().items():
        if not m.riepilogo or slug in spenti or (m.application and slug not in visibili):
            continue
        try:
            nuove = list(risolvi(m.riepilogo)(request, dal, oggi) or [])
        except Exception:
            if rigoroso:
                raise
            log.exception("riepilogo di %s non disponibile", slug)
            continue
        raccolte += [(slug, m.name, v) for v in nuove if v]
    silenziate, voci = set(silenziate), []
    for slug, modulo, v in raccolte:
        v["chiave"], v["modulo"] = chiave(slug, v), modulo
        v["silenziata"], v["vuota"] = v["chiave"] in silenziate, not v["numero"]
        if tutte or (v["numero"] and not v["silenziata"]):
            voci.append(v)
    mostrate = [v for v in voci if v["numero"] and not v["silenziata"]]
    sezioni = []
    for codice, titolo, sottotitolo in contratto.SEZIONI:
        mie = sorted((v for v in mostrate if v["sezione"] == codice), key=lambda v: (not v["urgente"], -v["numero"]))
        if mie:
            sezioni.append({"codice": codice, "titolo": titolo, "sottotitolo": sottotitolo, "voci": mie})
    return {"sezioni": sezioni, "totale": len(mostrate), "urgenti": sum(1 for v in mostrate if v["urgente"]), "voci": voci}
