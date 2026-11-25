"""Le previsioni salvate: il calcolo per azienda, il lavoro della notte e «Aggiorna».

Di notte (voce `cron` del manifest) e con «Aggiorna» (in un lavoro in background: ogni chiamata al servizio può durare
fino a due minuti) si ricalcolano, con l'accesso all'intera azienda, le previsioni del magazzino di un'azienda
(salvate in `PrevisioneArticolo`) e le previsioni pronte di Vendite (in `PrevisionePronta`). Le righe si sostituiscono
solo se il servizio ha risposto per tutte le serie; altrimenti restano quelle dell'ultimo calcolo riuscito, e
`StatoCalcolo` dice quando e perché non è andata."""
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.apps import apps
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from core.models import Azienda
from core.viste.interroga import richiesta_di

from . import motore, pronte, servizio
from .models import PrevisioneArticolo, PrevisionePronta, StatoCalcolo
from .servizio import ErrorePrevisione, ErroreServizio

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


def _sostituisci(azienda, cosa, vecchie, nuove):
    """Le righe salvate `vecchie` (un queryset dell'azienda) lasciano il posto alle `nuove`, tutte insieme. Due
    sostituzioni della stessa azienda (la notte e «Aggiorna», un doppio clic) si mettono in fila sulla riga di
    StatoCalcolo: altrimenti la seconda non vedrebbe le righe appena scritte dalla prima e le raddoppierebbe."""
    StatoCalcolo.objects.get_or_create(azienda=azienda, cosa=cosa)
    with transaction.atomic():
        StatoCalcolo.objects.filter(azienda=azienda, cosa=cosa).select_for_update().get()
        vecchie.delete()
        vecchie.model.objects.bulk_create(nuove)


def _errore(azienda, cosa):
    """L'errore dell'ultimo tentativo di `cosa` per l'azienda ("" se è riuscito o non c'è stato)."""
    return StatoCalcolo.objects.filter(azienda=azienda, cosa=cosa).values_list("errore", flat=True).first() or ""


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
    _sostituisci(azienda, StatoCalcolo.MAGAZZINO, PrevisioneArticolo.objects.filter(azienda=azienda), righe)
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


# ---- vendite ---------------------------------------------------------------------------------------------------

def vendite(azienda):
    """Ricalcola e salva le previsioni pronte di Vendite di `azienda` (pronte.py): quelle con dati (0 anche se il
    servizio non ha risposto: allora restano quelle di prima)."""
    if not apps.is_installed("vendite"):
        return 0
    return _con_stato(azienda, StatoCalcolo.VENDITE, _salva_vendite)


def _salva_vendite(request):
    """Una riga per previsione pronta di Vendite. Se la storia non basta (pochi mesi, nessun dato) la riga ne dice il
    motivo; se il servizio non risponde a una sola di esse non si salva nulla. Al servizio solo i numeri (motore)."""
    azienda, adesso, righe = request.azienda, timezone.now(), []
    elenco = pronte.di_app("vendite")
    for pronta in elenco:
        spec = pronta.spec(azienda)
        try:
            dati = {"spec": spec, "risultato": pronte.calcola_pronta(pronta, spec, request)}
        except ErroreServizio:
            raise
        except ErrorePrevisione as e:
            dati = {"spec": spec, "errore": str(e)}
        righe.append(PrevisionePronta(azienda=azienda, chiave=pronta.chiave, dati=dati, calcolata_il=adesso,
                                      modello=str(dati.get("risultato", {}).get("modello", ""))[:120]))
    vecchie = PrevisionePronta.objects.filter(azienda=azienda, chiave__in=[p.chiave for p in elenco])
    _sostituisci(azienda, StatoCalcolo.VENDITE, vecchie, righe)
    return sum(1 for r in righe if "risultato" in r.dati)


# ---- lavori ----------------------------------------------------------------------------------------------------

CALCOLI = {StatoCalcolo.MAGAZZINO: magazzino, StatoCalcolo.VENDITE: vendite}    # che cosa si può aggiornare


def eseguibile(cosa, azienda):
    """Le previsioni `cosa` si calcolano per l'azienda: Previsioni e l'app omonima (Magazzino, Vendite) sono
    installate, accese e valgono per lei."""
    return cosa in CALCOLI and pronte.app_attiva("previsioni", azienda) and pronte.app_attiva(cosa, azienda)


def notturno():
    """Il lavoro della notte, se il modulo è attivo, in licenza e con il servizio configurato: per ogni azienda attiva
    ricalcola le previsioni del magazzino (se ha movimenti) e quelle pronte di Vendite, dove si possono calcolare
    (`eseguibile`). Un'azienda o un calcolo che fallisce non ferma gli altri: si riprova la notte dopo."""
    if not servizio.attivo():
        return "Previsioni spente: niente da calcolare."
    con_movimenti = set()
    if apps.is_installed("magazzino"):
        from magazzino.models import Movimento
        con_movimenti = set(Azienda.objects.filter(pk__in=Movimento.objects.values("azienda"))
                            .values_list("pk", flat=True))
    salvate, aziende, fallite = dict.fromkeys(CALCOLI, 0), set(), set()
    for azienda in Azienda.objects.filter(attiva=True).order_by("pk"):
        for cosa, calcola in CALCOLI.items():
            if not eseguibile(cosa, azienda) or (cosa == StatoCalcolo.MAGAZZINO and azienda.pk not in con_movimenti):
                continue
            aziende.add(azienda.pk)
            try:
                salvate[cosa] += calcola(azienda)
            except Exception:
                log.exception("previsioni della notte: calcolo di %s fallito per l'azienda %s", cosa, azienda.pk)
                fallite.add(azienda.pk)
                continue
            if _errore(azienda, cosa):
                fallite.add(azienda.pk)
    return (f"Previsioni salvate: {salvate[StatoCalcolo.MAGAZZINO]} del magazzino e {salvate[StatoCalcolo.VENDITE]} "
            f"di Vendite, per {len(aziende)} aziende ({len(fallite)} con errori).")


notturno.senza_transazione = True       # niente transazione aperta durante le chiamate al servizio


def aggiorna(azienda_id, cosa):
    """«Aggiorna», in background: ricalcola subito le previsioni `cosa` dell'azienda; se non è andata, il perché."""
    azienda = Azienda.objects.filter(pk=azienda_id).first()
    if azienda is None:
        return None
    salvate = CALCOLI[cosa](azienda)
    errore = _errore(azienda, cosa)
    return f"Previsioni non aggiornate: {errore}" if errore else f"{salvate} previsioni salvate."


aggiorna.senza_transazione = True
