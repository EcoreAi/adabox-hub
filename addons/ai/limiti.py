"""Prima di ogni turno: licenza valida, utenti entro il limite, spesa del mese entro il tetto dell'azienda."""
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


def verifica(azienda=None, utente=None, funzione="chat"):
    stato = licenza.attuale()
    if not stato.valida:
        raise ErroreModello("LIMITE", f"L'assistente non è attivo: {stato.motivo} Contatta l'amministratore.")
    if funzione not in stato.funzioni:
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
