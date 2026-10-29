"""Attività pianificate dell'assistente: quando tocca, esecuzione nel worker, consegna del risultato.

Il worker del kernel è l'orologio: la voce `cron` del manifest accoda `esegui_scadute` ogni minuto (e non ne accoda
un'altra finché la precedente è in coda o in corso). Ogni esecuzione è un turno con il compito «pianificate», con
i permessi e l'azienda del proprietario, nella conversazione della pianificazione; il tetto di spesa vale come in
chat. Dopo MAX_ERRORI esecuzioni fallite di fila la pianificazione si spegne e il proprietario riceve un avviso."""
import datetime
import logging
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import connection, transaction
from django.urls import reverse
from django.utils import timezone

from .models import Conversazione, Pianificata, Turno

log = logging.getLogger("ai.pianificate")

UTENTE_ASSISTENTE = "assistente-ai"          # autore dei messaggi in Discuss (non attivo, senza password)
CONTROLLO_EVENTI = datetime.timedelta(minutes=5)
MAX_PER_GIRO = 20
LUNGHEZZA_DISCUSS = 1500
ORA_DEFAULT = datetime.time(8, 0)


# ---------- quando ----------

def _alle(data, ora):
    return timezone.make_aware(datetime.datetime.combine(data, ora))


def calcola_prossima(p, da=None):
    """La prima esecuzione dopo `da` (adesso se manca), secondo la ricorrenza."""
    da = da or timezone.now()
    if p.ricorrenza == Pianificata.ORE:
        return da + datetime.timedelta(hours=max(1, p.ogni_ore or 1))
    if p.ricorrenza == Pianificata.EVENTI:
        return da + CONTROLLO_EVENTI
    ora = p.alle or ORA_DEFAULT
    oggi = timezone.localtime(da).date()
    if p.ricorrenza == Pianificata.MESE:
        giorno = min(max(1, p.giorno_mese or 1), 28)
        candidata = _alle(oggi.replace(day=giorno), ora)
        if candidata <= da:
            mese = oggi.replace(day=1) + datetime.timedelta(days=32)
            candidata = _alle(mese.replace(day=giorno), ora)
        return candidata
    giorni = p.elenco_giorni() or list(range(7))
    for avanti in range(8):
        data = oggi + datetime.timedelta(days=avanti)
        if data.weekday() in giorni and (candidata := _alle(data, ora)) > da:
            return candidata
    return None                                      # non succede: 8 giorni coprono ogni settimana


# ---------- esecuzione ----------

def esegui_scadute():
    """Le pianificazioni scadute: la prossima esecuzione si sposta subito (nella stessa transazione, così con più
    worker ognuna parte una volta sola), poi si eseguono una alla volta."""
    adesso = timezone.now()
    with transaction.atomic():
        qs = Pianificata.objects.filter(attiva=True, prossima__lte=adesso).order_by("prossima")
        if connection.features.has_select_for_update_skip_locked:
            qs = qs.select_for_update(skip_locked=True)
        scadute = list(qs[:MAX_PER_GIRO])
        for p in scadute:
            p.prossima = calcola_prossima(p, adesso)
            p.save(update_fields=["prossima"])
    fatte = 0
    for p in scadute:
        if p.ricorrenza == Pianificata.EVENTI:
            for evento in eventi_imminenti(p, adesso):
                esegui(p, evento=evento)
                fatte += 1
        else:
            esegui(p)
            fatte += 1
    return f"pianificate eseguite: {fatte}"


def _conversazione(p):
    if p.conversazione_id is None or not Conversazione.objects.filter(pk=p.conversazione_id).exists():
        p.conversazione = Conversazione.objects.create(utente=p.utente, ambito=p.ambito,
                                                       titolo=f"Pianificata: {p.nome}"[:120], titolo_generato=True)
        p.save(update_fields=["conversazione"])
    return p.conversazione


def nota_per_il_modello(p, evento=None):
    nota = (f"Esecuzione pianificata «{p.nome}» ({p.frequenza()}): l'utente non è presente. Fai il lavoro con gli "
            "strumenti e scrivi il risultato completo e autosufficiente. Non preparare modifiche ai dati se le "
            "istruzioni non lo chiedono esplicitamente.")
    if evento is not None:
        nota += f" Evento: {evento['descrizione']}"
    return nota


def esegui_id(pianificata_id):
    """Per «Esegui ora» (lavoro in background): un'esecuzione subito, senza toccare la prossima."""
    p = Pianificata.objects.filter(pk=pianificata_id).select_related("utente", "azienda").first()
    if p is None:
        return "pianificata eliminata"
    if p.ricorrenza == Pianificata.EVENTI:
        eventi = eventi_imminenti(p) or [None]
        for evento in eventi:
            esegui(p, evento=evento)
        return f"eseguita {len(eventi)} volte"
    turno = esegui(p)
    return f"turno {getattr(turno, 'pk', None)}"


def esegui(p, evento=None):
    """Un'esecuzione della pianificazione (dal worker o da «Esegui ora»). Restituisce il turno."""
    from . import motore
    if not p.utente.is_active:
        _spegni(p, "Il proprietario non è più attivo.")
        return None
    conversazione = _conversazione(p)
    testo = p.istruzioni if evento is None else f"{p.istruzioni}\n\nEvento: {evento['titolo']}"
    turno = motore.avvia(conversazione, testo, p.utente, p.azienda, compito="pianificate", sincrono=True,
                         nota=nota_per_il_modello(p, evento))
    turno.refresh_from_db()
    p.ultima = timezone.now()
    if turno.compito != "pianificate":                 # l'utente stava scrivendo nella stessa chat: si riprova
        p.prossima = timezone.now() + CONTROLLO_EVENTI
        p.esito = "Rimandata: la conversazione era occupata."
        p.save(update_fields=["ultima", "prossima", "esito"])
        return turno
    if turno.stato == Turno.COMPLETATO:
        p.errori, p.esito = 0, f"Eseguita il {timezone.localtime(p.ultima):%d/%m/%Y alle %H:%M}."
        p.save(update_fields=["ultima", "errori", "esito"])
        consegna(p, turno)
    else:
        p.errori += 1
        p.esito = f"Non riuscita: {turno.errore or turno.get_stato_display()}"[:300]
        p.save(update_fields=["ultima", "errori", "esito"])
        if p.errori >= Pianificata.MAX_ERRORI:
            _spegni(p, f"{Pianificata.MAX_ERRORI} esecuzioni non riuscite di fila. Ultimo errore: {p.esito}")
    return turno


def _spegni(p, motivo):
    p.attiva, p.esito = False, f"Sospesa: {motivo}"[:300]
    p.save(update_fields=["attiva", "esito"])
    log.warning("pianificata %s sospesa: %s", p.pk, motivo)
    if p.utente.email:
        send_mail(f"Attività pianificata sospesa: {p.nome}",
                  f"L'attività pianificata «{p.nome}» è stata sospesa.\n\n{motivo}\n\n"
                  f"Puoi riattivarla da {settings.SITO_URL}{reverse('ai:pianificate_lista')}",
                  None, [p.utente.email], fail_silently=True)


# ---------- prima degli eventi del calendario ----------

def eventi_imminenti(p, adesso=None):
    """Gli eventi visibili al proprietario che iniziano entro `minuti_prima` minuti e non sono ancora stati
    preparati (se l'app calendario c'è). Segna come preparati quelli restituiti."""
    if "calendario" not in settings.ADDONS_ATTIVI:
        return []
    from .strumenti import Contesto, ErroreStrumento, richiesta
    from .strumenti.viste import vista_per
    adesso = adesso or timezone.now()
    contesto = Contesto(utente=p.utente, azienda=p.azienda)
    try:
        vista = vista_per(contesto, "calendario.eventi")
    except ErroreStrumento:
        return []
    limite = adesso + datetime.timedelta(minutes=p.minuti_prima or 30)
    qs = (vista.get_queryset(richiesta.per(contesto)).filter(inizio__gt=adesso, inizio__lte=limite)
          .exclude(pk__in=p.eventi_fatti or []).order_by("inizio"))
    mie = [e for e in qs[:10] if e.organizzatore_id == p.utente.pk or e.partecipanti.filter(pk=p.utente.pk).exists()]
    if not mie:
        return []
    p.eventi_fatti = (list(p.eventi_fatti or []) + [e.pk for e in mie])[-200:]
    p.save(update_fields=["eventi_fatti"])
    return [{"id": e.pk, "titolo": e.titolo,
             "descrizione": f"«{e.titolo}» il {timezone.localtime(e.inizio):%d/%m/%Y alle %H:%M}"
                            + (f", luogo {e.luogo}" if e.luogo else "")
                            + f" (calendario.eventi id {e.pk}, {vista.url('dettaglio', pk=e.pk)})"} for e in mie]


# ---------- consegna ----------

def _link(p):
    return f"{settings.SITO_URL}{reverse('ai:conversazione', args=[p.conversazione_id])}"


def _testo_semplice(testo):
    """Il Markdown della risposta in testo leggibile per Discuss ed email (link come «testo (url)»)."""
    testo = re.sub(r"\[([^\]\n]+)\]\((/[^\s)]*)\)", lambda m: f"{m.group(1)} ({settings.SITO_URL}{m.group(2)})", testo)
    testo = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", r"\1 (\2)", testo)
    testo = re.sub(r"^\|?\s*:?-{3,}.*$\n?", "", testo, flags=re.M)               # separatori delle tabelle
    return re.sub(r"^#{1,6}\s+", "", testo, flags=re.M).strip()


def consegna(p, turno):
    testo = _testo_semplice(turno.testo)
    if p.in_discuss and "discuss" in settings.ADDONS_ATTIVI:
        try:
            _in_discuss(p, testo)
        except Exception:                            # la consegna in più non deve far fallire l'esecuzione
            log.exception("pianificata %s: consegna in Discuss", p.pk)
    if p.per_email and p.utente.email:
        send_mail(f"{p.nome}", f"{testo}\n\n—\nRisultato completo (con grafici e tabelle): {_link(p)}\n"
                               f"Attività pianificata {p.frequenza()}.", None, [p.utente.email], fail_silently=True)


def utente_assistente():
    """L'autore dei messaggi dell'assistente in Discuss: un utente non attivo e senza password (non entra mai)."""
    assistente, creato = get_user_model().objects.get_or_create(
        username=UTENTE_ASSISTENTE, defaults={"first_name": "Assistente", "is_active": False})
    if creato:
        assistente.set_unusable_password()
        assistente.save(update_fields=["password"])
    return assistente


def _in_discuss(p, testo):
    from discuss import servizi
    estratto = testo if len(testo) <= LUNGHEZZA_DISCUSS else testo[:LUNGHEZZA_DISCUSS].rsplit("\n", 1)[0] + "\n…"
    canale = servizi.diretto([utente_assistente(), p.utente])
    servizi.invia(canale, utente_assistente(), f"**{p.nome}**\n\n{estratto}\n\nRisultato completo: {_link(p)}")
