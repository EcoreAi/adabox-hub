"""Hook di installazione del Personale."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.utils import timezone

from core.models import Azienda


def post_install(modulo):
    Group.objects.get(name="Personale / Dipendente").user_set.add(*User.objects.filter(is_active=True))


def demo(modulo):
    """Due reparti, cinque dipendenti (il primo superuser è il direttore) e qualche assenza."""
    from . import calendario_lavoro, flusso
    from .models import Assenza, Dipendente, Reparto, TipoAssenza
    azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
    if azienda is None or Dipendente.objects.filter(azienda=azienda).exists():
        return
    capo_utente = User.objects.filter(is_superuser=True).order_by("pk").first()
    oggi = timezone.localdate()
    direzione = Reparto.objects.create(azienda=azienda, nome="Direzione")
    commerciale = Reparto.objects.create(azienda=azienda, nome="Commerciale")
    tecnico = Reparto.objects.create(azienda=azienda, nome="Tecnico")
    direttore = Dipendente.objects.create(azienda=azienda, nome="Laura", cognome="Ferri", reparto=direzione,
                                          ruolo="Direttrice", utente=capo_utente,
                                          data_assunzione=datetime.date(oggi.year - 6, 3, 1))
    direzione.responsabile = direttore
    direzione.save(update_fields=["responsabile"])
    persone = [("Marco", "Gialli", commerciale, "Commerciale"), ("Giulia", "Neri", commerciale, "Account"),
               ("Paolo", "Verdi", tecnico, "Sviluppatore"), ("Sara", "Blu", tecnico, "Sistemista")]
    dipendenti = [Dipendente.objects.create(azienda=azienda, nome=n, cognome=c, reparto=r, ruolo=ruolo,
                                            responsabile=direttore,
                                            data_assunzione=datetime.date(oggi.year - 2, 9, 1) if i else
                                            datetime.date(oggi.year, 2, 1), ore_settimanali=Decimal(40))
                  for i, (n, c, r, ruolo) in enumerate(persone)]
    ferie, permesso = TipoAssenza.objects.get(saldo="ferie"), TipoAssenza.objects.get(saldo="permessi")

    def lunedi(settimane):
        giorno = oggi + datetime.timedelta(weeks=settimane)
        return giorno - datetime.timedelta(days=giorno.weekday())

    piano = [(dipendenti[0], ferie, lunedi(-6), 4, None, True), (dipendenti[1], ferie, lunedi(2), 4, None, None),
             (dipendenti[2], permesso, lunedi(1) + datetime.timedelta(days=2), 0, Decimal(3), True),
             (dipendenti[3], ferie, lunedi(4), 4, None, None)]
    for dipendente, tipo, dal, giorni, ore, approvata in piano:
        al = dal + datetime.timedelta(days=giorni)
        if tipo.unita == "giorni" and not calendario_lavoro.giorni_lavorativi(dal, al):
            continue
        a = Assenza.objects.create(azienda=azienda, dipendente=dipendente, tipo=tipo, dal=dal, al=al, ore=ore,
                                   motivo="Dati dimostrativi")
        if approvata and capo_utente is not None:
            flusso.decidi(a, capo_utente, True)
