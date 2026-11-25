"""Le previsioni salvate: il calcolo per azienda, il lavoro della notte e «Aggiorna».

Di notte (voce `cron` del manifest) e con «Aggiorna» (in un lavoro in background: ogni chiamata al servizio può durare
fino a due minuti) si ricalcolano le previsioni del magazzino di un'azienda, con l'accesso all'intera azienda, e si
salvano in `PrevisioneArticolo`. Le righe si sostituiscono solo se il servizio ha risposto per tutte le serie;
altrimenti restano quelle dell'ultimo calcolo riuscito, e `StatoCalcolo` dice quando e perché non è andata."""
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.apps import apps
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from core.models import Azienda
from core.registry import modules
from core.viste.interroga import richiesta_di

from . import motore, servizio
from .models import PrevisioneArticolo, StatoCalcolo
from .servizio import ErrorePrevisione

log = logging.getLogger("previsioni.calcolo")

ORIZZONTE = {"mese": 12, "settimana": 52}          # periodi previsti, dal periodo in corso
NESSUN_UTENTE = "nessun utente con cui calcolare"
ERRORE_INTERNO = "Errore interno durante il calcolo: i dettagli sono nel registro del server."


def request_per(azienda):
    """La richiesta con cui si calcola per l'intera azienda, di notte e con «Aggiorna»: l'utente è il primo superuser
    attivo. None se non ce n'è nessuno."""
    utente = User.objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
    return richiesta_di(utente, azienda) if utente is not None else None


def _con_stato(azienda, cosa, calcola):
    """`calcola(request)` con la richiesta dell'intera azienda, annotando l'esito in StatoCalcolo: le righe salvate.
    Gli errori del servizio non risalgono (0 righe, restano quelle di prima); gli altri sì, dopo averli annotati."""
    stato, _ = StatoCalcolo.objects.get_or_create(azienda=azienda, cosa=cosa)
    stato.ultimo_tentativo = timezone.now()
    request = request_per(azienda)
    if request is None:
        stato.errore = NESSUN_UTENTE
        stato.save(update_fields=["ultimo_tentativo", "errore"])
        return 0
    try:
        righe = calcola(request)
    except ErrorePrevisione as e:
        log.warning("previsioni di %s non calcolate per l'azienda %s: %s", cosa, azienda.pk, e)
        stato.errore = str(e)
        stato.save(update_fields=["ultimo_tentativo", "errore"])
        return 0
    except Exception:
        stato.errore = ERRORE_INTERNO
        stato.save(update_fields=["ultimo_tentativo", "errore"])
        raise
    stato.errore, stato.ultimo_ok = "", timezone.now()
    stato.save(update_fields=["ultimo_tentativo", "errore", "ultimo_ok"])
    return righe


# ---- magazzino -------------------------------------------------------------------------------------------------

def magazzino(azienda):
    """Ricalcola e salva le previsioni del magazzino di `azienda`: le righe salvate (0 anche se il servizio non ha
    risposto: allora restano quelle di prima)."""
    if not apps.is_installed("magazzino"):
        return 0
    return _con_stato(azienda, StatoCalcolo.MAGAZZINO, _salva_magazzino)


def _periodi_completi(primo, per, attuale):
    """I periodi completi dal primo movimento a quello in corso escluso (gli ultimi MAX_PERIODI)."""
    periodi, p = [], motore.inizio(primo, per) if primo else attuale
    while p < attuale:
        periodi.append(p)
        p = motore.avanti(p, per)
    return periodi[-motore.MAX_PERIODI:]


def _salva_magazzino(request):
    """Una serie per chiave con soglie e consumo, dal primo movimento dell'azienda (zeri dove non c'è consumo); con
    meno di MIN_PERIODI periodi completi nessuna riga. Le righe dell'azienda si sostituiscono tutte insieme."""
    from . import magazzino as pm

    azienda, oggi = request.azienda, timezone.localdate()
    per = pm.per_della_storia(azienda)
    attuale = motore.inizio(oggi, per)
    periodi = _periodi_completi(pm.primo_movimento(azienda), per, attuale)
    righe = []
    if len(periodi) >= motore.MIN_PERIODI:
        consumi, soglie = pm.consumi(azienda, per), pm.chiavi_e_soglie(azienda)
        storie = {chiave: [(p, consumi[chiave].get(p, 0.0)) for p in periodi] for chiave in soglie if chiave in consumi}
        if storie:
            righe = _righe(azienda, storie, soglie, pm.partenze(azienda), per, attuale, oggi)
    with transaction.atomic():
        PrevisioneArticolo.objects.filter(azienda=azienda).delete()
        PrevisioneArticolo.objects.bulk_create(righe)
    return len(righe)


def _righe(azienda, storie, soglie, partenze, per, attuale, oggi):
    """Le righe da salvare: il servizio per tutte le serie (a blocchi di MAX_SERIE; se un blocco non risponde, solleva
    e non si salva nulla), poi la proiezione di ognuna dalla sua partenza. Nomi e codici si copiano adesso."""
    from magazzino.models import Magazzino
    from prodotti.models import Prodotto

    from . import magazzino as pm

    orizzonte = ORIZZONTE[per]
    futuri, modello = motore.prevedi_molte(storie, orizzonte)
    prodotti = {pk: (nome, codice) for pk, nome, codice in Prodotto.objects.filter(
        azienda=azienda, pk__in={p for p, _ in storie}).values_list("pk", "nome", "codice")}
    magazzini = dict(Magazzino.objects.filter(azienda=azienda, pk__in={m for _, m in storie if m}).values_list("pk", "nome"))
    adesso, righe = timezone.now(), []
    for chiave, storia in storie.items():
        futuro, partenza = futuri[chiave], partenze.get(chiave, Decimal(0))
        riordina_sotto, riporta_a = soglie[chiave]
        mediana = sum(q[1] for q in futuro) / len(futuro)
        (prodotto, codice), magazzino_pk = prodotti[chiave[0]], chiave[1]
        righe.append(PrevisioneArticolo(
            azienda=azienda, prodotto_pk=chiave[0], prodotto=prodotto, codice=codice, magazzino_pk=magazzino_pk,
            magazzino=magazzini.get(magazzino_pk, ""), per=per, partenza=partenza,
            futuro=[[motore.etichetta(motore.avanti(attuale, per, i), per), *q] for i, q in enumerate(futuro)],
            consumo_mensile=_millesimi(mediana if per == "mese" else mediana * 52 / 12),
            affidabilita=motore.affidabilita(storia, futuro, orizzonte, per, prova=False),
            modello=modello[:120], calcolata_il=adesso,
            **pm.proietta(partenza, futuro, per, attuale, riordina_sotto, riporta_a, oggi)))
    return righe


def _millesimi(valore):
    return Decimal(str(valore)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


# ---- lavori ----------------------------------------------------------------------------------------------------

CALCOLI = {StatoCalcolo.MAGAZZINO: magazzino}       # che cosa si può aggiornare


def notturno():
    """Il lavoro della notte: ricalcola le previsioni salvate di ogni azienda attiva con movimenti di magazzino e con
    le app Previsioni e Magazzino, se il modulo è attivo, in licenza e con il servizio configurato, e se c'è Magazzino.
    Un'azienda che fallisce non ferma le altre: si riprova la notte dopo."""
    if not servizio.attivo() or not apps.is_installed("magazzino"):
        return "Previsioni spente o senza Magazzino: niente da calcolare."
    from magazzino.models import Movimento

    aziende = [a for a in Azienda.objects.filter(attiva=True, pk__in=Movimento.objects.values("azienda")).order_by("pk")
               if modules.per_azienda("previsioni", a) and modules.per_azienda("magazzino", a)]
    righe = 0
    for azienda in aziende:
        try:
            righe += magazzino(azienda)
        except Exception:
            log.exception("previsioni della notte: calcolo del magazzino fallito per l'azienda %s", azienda.pk)
    return f"{righe} previsioni del magazzino per {len(aziende)} aziende."


notturno.senza_transazione = True       # niente transazione aperta durante le chiamate al servizio


def aggiorna(azienda_id, cosa):
    """«Aggiorna», in background: ricalcola subito le previsioni `cosa` dell'azienda."""
    azienda = Azienda.objects.filter(pk=azienda_id).first()
    if azienda is None:
        return None
    return f"{CALCOLI[cosa](azienda)} previsioni salvate."


aggiorna.senza_transazione = True
