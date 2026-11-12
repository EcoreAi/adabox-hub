"""Prima di ogni turno: licenza valida, utenti entro il limite, spesa del mese entro il tetto dell'azienda.

Con una formula della licenza diversa da «propria» (ai.licenza) c'è anche la quota: il costo del mese sui provider
forniti con il piano, per utente e per tutta l'istanza. A quota finita quei modelli escono dalla catena (`ammessi`):
la chat continua sui modelli propri o locali, se ci sono. Il tetto di spesa dell'azienda resta un budget in più, che
il cliente si dà da solo."""
import logging
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db.models import Sum
from django.utils import timezone

from core import parametri

from . import licenza
from .gateway import ErroreModello

log = logging.getLogger("ai.limiti")
SERVIZIO = "servizio"                     # compito dei lavori chiesti dal sistema (la chat del sito): non sono consumo di una persona
AVVISO_QUOTA = Decimal("0.8")             # da questa parte della quota in su la chat avvisa


def spesa_mese(azienda):
    oggi = timezone.localdate()
    from .models import Turno
    return Turno.objects.filter(azienda=azienda, iniziato__year=oggi.year, iniziato__month=oggi.month).aggregate(
        t=Sum("costo"))["t"] or Decimal(0)


def tetto(azienda):
    valore = parametri.leggi("ai.tetto_mensile", azienda)
    return Decimal(str(valore or 0))


def utenti_del_mese():
    from .models import Turno
    oggi = timezone.localdate()
    return set(Turno.objects.filter(iniziato__year=oggi.year, iniziato__month=oggi.month, compito="chat")
               .values_list("utente_id", flat=True))


def _del_mese():
    from .models import Turno
    oggi = timezone.localdate()
    return Turno.objects.filter(iniziato__year=oggi.year, iniziato__month=oggi.month)


def consumo_fornito(utente=None):
    """Il costo del mese sui provider forniti con il piano: di tutta l'istanza, o di una persona (senza i lavori di
    servizio intestati a lei)."""
    turni = _del_mese() if utente is None else _del_mese().filter(utente=utente).exclude(compito=SERVIZIO)
    return turni.aggregate(t=Sum("costo_fornito"))["t"] or Decimal(0)


def consumo_per_utente(quanti=20):
    """[(utente, costo)] di chi ha consumato di più questo mese sui provider forniti con il piano (pagina della licenza)."""
    from django.contrib.auth import get_user_model
    righe = (_del_mese().filter(utente__isnull=False, costo_fornito__gt=0).exclude(compito=SERVIZIO)
             .values("utente").annotate(t=Sum("costo_fornito")).order_by("-t")[:quanti])
    utenti = get_user_model().objects.in_bulk([r["utente"] for r in righe])
    return [(utenti[r["utente"]], r["t"]) for r in righe if r["utente"] in utenti]


def quota(utente=None, stato=None):
    """[(consumo, quota, di chi)] delle quote della licenza che valgono per questa persona, nell'ordine in cui si
    controllano: prima l'istanza, poi la persona (solo con la formula «inclusa»)."""
    stato = stato or licenza.attuale()
    if not stato.valida or stato.formula == licenza.PROPRIA:
        return []
    voci = []
    if stato.quota_istanza:
        voci.append((consumo_fornito(), stato.quota_istanza, "istanza"))
    if stato.formula == licenza.INCLUSA and stato.quota_utente and utente is not None:
        voci.append((consumo_fornito(utente), stato.quota_utente, "utente"))
    return voci


def _finita(voci, stato):
    for consumo, limite, di_chi in voci:
        if consumo >= limite:
            if di_chi == "utente":
                return f"Hai esaurito la tua quota mensile dell'assistente ({limite} $)."
            if stato.formula == licenza.CONSUMO:
                return f"Raggiunto il tetto mensile dell'assistente previsto dal piano ({limite} $)."
            return f"La quota mensile dell'assistente compresa nel piano è esaurita ({limite} $)."
    return ""


def quota_finita(utente=None, stato=None):
    """Perché questo mese i modelli forniti con il piano non si usano più, o "" se si può."""
    stato = stato or licenza.attuale()
    return _finita(quota(utente, stato), stato)


def avviso_quota(utente=None, stato=None):
    """Il testo per la chat quando una quota della licenza è finita o quasi, "" altrimenti."""
    stato = stato or licenza.attuale()
    voci = quota(utente, stato)
    if motivo := _finita(voci, stato):
        return f"{motivo} I modelli compresi nel piano tornano il primo del mese."
    for consumo, limite, di_chi in voci:
        if consumo >= limite * AVVISO_QUOTA:
            di = "della tua quota mensile" if di_chi == "utente" else "della quota mensile del piano"
            return f"Assistente: usati {consumo:.2f} $ su {limite} $ {di}."
    return ""


def ammessi(catena, utente=None):
    """La catena [(modello, chiave)] senza i modelli forniti con il piano, se la loro quota del mese è finita. Se non
    resta nessun modello: LIMITE, con il motivo per l'utente."""
    if not any(modello.provider.gestito for modello, _ in catena):
        return catena
    motivo = quota_finita(utente)
    if not motivo:
        return catena
    restanti = [anello for anello in catena if not anello[0].provider.gestito]
    if not restanti:
        raise ErroreModello("LIMITE", f"{motivo} L'assistente riprende il primo del mese: per continuare prima, "
                                      "chiedi all'amministratore di ampliare il piano.")
    return restanti


def verifica(azienda=None, utente=None, funzione="chat"):
    stato = licenza.attuale()
    if not stato.valida:
        raise ErroreModello("LIMITE", f"L'assistente non è attivo: {stato.motivo} Contatta l'amministratore.")
    if funzione != "chat" and stato.funzioni is not None and funzione not in stato.funzioni:
        raise ErroreModello("LIMITE", "Questa funzione dell'assistente non è compresa nella licenza.")
    if stato.utenti and utente is not None:
        attivi = utenti_del_mese()
        if utente.pk not in attivi and len(attivi) >= stato.utenti:
            raise ErroreModello("LIMITE", f"Raggiunto il numero di utenti della licenza ({stato.utenti} al mese).")
    if azienda is None:
        return
    limite = tetto(azienda)
    if limite <= 0:
        return
    spesa = spesa_mese(azienda)
    if spesa >= limite:
        raise ErroreModello("LIMITE", f"Raggiunto il tetto di spesa mensile dell'assistente ({limite} $): "
                                      "l'amministratore può alzarlo nelle impostazioni.")
    if spesa >= limite * Decimal(parametri.leggi("ai.avviso_percentuale", azienda) or 80) / 100:
        _avvisa(azienda, spesa, limite)


def _avvisa(azienda, spesa, limite):
    """Una volta al mese per azienda: email agli amministratori dell'assistente."""
    chiave = f"avviso_{timezone.localdate():%Y_%m}"
    from core.models import Parametro
    _, nuovo = Parametro.objects.get_or_create(chiave=f"ai.{chiave}", azienda=azienda, defaults={"valore": True})
    if not nuovo:
        return
    destinatari = [u.email for u in get_user_model().objects.filter(is_active=True).exclude(email="")
                   if u.is_superuser or u.has_perm("ai.change_provider")]
    if destinatari:
        send_mail(f"Assistente AI: spesa del mese a {spesa:.2f} $ su {limite} $",
                  f"La spesa dell'assistente per {azienda} questo mese è {spesa:.2f} $ su un tetto di {limite} $.\n"
                  "Al raggiungimento del tetto l'assistente smette di rispondere fino al mese prossimo.",
                  None, destinatari, fail_silently=True)
    log.info("avviso di spesa per %s: %s su %s", azienda, spesa, limite)
