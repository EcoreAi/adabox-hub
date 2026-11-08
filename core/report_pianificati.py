"""Report pianificati (RPT-06): una lista filtrata in Excel/CSV o, se c'è Analisi, una pagina in PDF, mandata per email
ogni giorno, settimana o mese. Si calcola nel worker con i permessi del proprietario (regole per ruolo comprese): chi
riceve vede quello che vedrebbe lui, mai di più. I tipi oltre la lista li registrano i moduli (registra_tipo)."""
import datetime
import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.http import QueryDict
from django.utils import timezone

log = logging.getLogger("core.report_pianificati")
_TIPI = {}


class ErroreReport(Exception):
    pass


def registra_tipo(codice, etichetta, genera, scelte=None, formati=("pdf",)):
    """`genera(report, request)` → (nome_file, contenuto, mimetype); `scelte(request)` → [(riferimento, etichetta)]."""
    _TIPI[codice] = {"etichetta": etichetta, "genera": genera, "scelte": scelte, "formati": formati}


def tipi():
    return {"lista": {"etichetta": "Una lista filtrata", "genera": _genera_lista, "scelte": _scelte_liste, "formati": ("xlsx", "csv")}, **_TIPI}


def _vista(chiave):
    from core.viste import registry
    modulo, _, slug = (chiave or "").partition(".")
    return next((v for v in registry.viste_di(modulo) if v.slug == slug), None)


def _scelte_liste(request):
    from core.viste import interroga
    return [(f"{v.modulo}.{v.slug}", f"{v.modulo} · {str(v.verbose_name_plural).capitalize()}")
            for v in interroga.viste_accessibili(request, escluse=set())]


def _genera_lista(report, request):
    from core import esporta, regole
    vista = _vista(report.riferimento)
    if vista is None or not vista.has_view_permission(request):
        raise ErroreReport("la vista non c'è più o il proprietario non la vede più")
    request.GET = QueryDict(report.parametri or "")
    formato = report.formato if report.formato in ("xlsx", "csv") else "xlsx"
    qs = esporta.queryset(vista, request)
    tipo, estensione = esporta.FORMATI[formato]
    nome = f"{vista.slug}-{timezone.localdate():%Y%m%d}.{estensione}"
    return nome, esporta.contenuto(vista, qs, formato, regole.nascosti(vista, request)), tipo


def prossimo(report, dopo=None):
    """Il prossimo invio dopo `dopo` (adesso), all'ora scelta, nel fuso locale."""
    dopo = timezone.localtime(dopo or timezone.now())
    candidato = dopo.replace(hour=report.ora.hour, minute=report.ora.minute, second=0, microsecond=0)
    for _ in range(400):
        valido = (report.frequenza == "giorno" or (report.frequenza == "settimana" and candidato.weekday() == report.giorno_settimana)
                  or (report.frequenza == "mese" and candidato.day == min(max(report.giorno_mese, 1), 28)))
        if valido and candidato > dopo:
            return candidato
        candidato += datetime.timedelta(days=1)
    return None


def richiesta_per(report):
    from core.viste.interroga import richiesta_di
    return richiesta_di(report.utente, report.azienda)


def esegui(report, aggiorna=True):
    """Genera e manda il report. Restituisce l'esito in parole; un errore lo scrive nell'esito e lo dice al proprietario."""
    try:
        if not report.utente.is_active:
            raise ErroreReport("il proprietario non è più attivo")
        tipo = tipi().get(report.tipo)
        if tipo is None:
            raise ErroreReport(f"tipo «{report.tipo}» non disponibile (modulo spento?)")
        destinatari = report.elenco_destinatari()
        if not destinatari:
            raise ErroreReport("nessun destinatario")
        nome, contenuto, mimetype = tipo["genera"](report, richiesta_per(report))
        brand = settings.THEME.get("brand", "")
        email = EmailMessage(f"[{brand}] {report.nome}", f"In allegato «{report.nome}», aggiornato al {timezone.localtime():%d/%m/%Y %H:%M}.\n"
                             f"Lo manda {brand} per conto di {report.utente.get_full_name() or report.utente.username}.\n",
                             to=destinatari)
        email.attach(nome, contenuto, mimetype)
        email.send()
        esito = f"Inviato a {len(destinatari)} destinatar{'io' if len(destinatari) == 1 else 'i'}"
    except Exception as e:                                  # noqa: BLE001 - un report rotto non ferma gli altri
        log.exception("report pianificato %s", report.pk)
        esito = f"Errore: {e}"[:250]
        if report.utente.email:
            EmailMessage(f"Report «{report.nome}» non inviato", f"Il report pianificato «{report.nome}» non è partito: {e}.\n",
                         to=[report.utente.email]).send(fail_silently=True)
    if aggiorna:
        report.ultimo_invio, report.ultimo_esito = timezone.now(), esito
        report.prossimo_invio = prossimo(report)
        report.save(update_fields=["ultimo_invio", "ultimo_esito", "prossimo_invio"])
    return esito


def esegui_dovuti():
    """Lavoro pianificato (ogni 15 minuti): i report attivi il cui prossimo invio è passato."""
    from core.models import ReportPianificato
    n = 0
    for r in ReportPianificato.objects.filter(attivo=True, prossimo_invio__lte=timezone.now()).select_related("utente", "azienda"):
        esegui(r)
        n += 1
    return n
