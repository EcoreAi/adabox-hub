"""Prenotazione online degli appuntamenti: le fasce libere dagli orari del tipo, al netto degli eventi degli
operatori; la prenotazione crea l'evento, il contatto (e l'opportunità, se c'è il CRM), manda la conferma con il .ics
e un link firmato per annullare."""
import datetime

from django.apps import apps
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core import lavori

from .ics import ics
from .models import Evento, Prenotazione, TipoAppuntamento

SALE = "calendario.prenotazione"


def _occupati(operatori, dal, al):
    """{operatore_id: [(inizio, fine), ...]} degli eventi che toccano l'intervallo."""
    ids = [o.pk for o in operatori]
    occupati = {i: [] for i in ids}
    eventi = (Evento.objects.filter(inizio__lt=al, fine__gt=dal)
              .filter(Q(organizzatore_id__in=ids) | Q(partecipanti__in=ids))
              .prefetch_related("partecipanti").distinct())
    for e in eventi:
        persone = {p.pk for p in e.partecipanti.all()} | {e.organizzatore_id}
        for i in ids:
            if i in persone:
                occupati[i].append((e.inizio, e.fine))
    return occupati


def _libero(occupati, inizio, fine):
    return all(fine <= a or inizio >= b for a, b in occupati)


def fasce(tipo, dal=None, giorni=None, adesso=None):
    """[(inizio, [operatori liberi])] delle fasce prenotabili, in ordine."""
    adesso = adesso or timezone.now()
    oggi = timezone.localdate(adesso)
    dal = max(dal or oggi, oggi)
    ultimo = oggi + datetime.timedelta(days=tipo.giorni_avanti)
    al = min(dal + datetime.timedelta(days=giorni or tipo.giorni_avanti), ultimo)
    operatori = list(tipo.operatori.filter(is_active=True))
    orari = list(tipo.orari.all())
    if not operatori or not orari or al < dal:
        return []
    minimo = adesso + datetime.timedelta(hours=tipo.preavviso)
    durata, passo = datetime.timedelta(minutes=tipo.durata), datetime.timedelta(minutes=tipo.durata + tipo.pausa)
    pausa = datetime.timedelta(minutes=tipo.pausa)
    tz = timezone.get_current_timezone()
    inizio_finestra = timezone.make_aware(datetime.datetime.combine(dal, datetime.time.min), tz)
    fine_finestra = timezone.make_aware(datetime.datetime.combine(al + datetime.timedelta(days=1), datetime.time.min), tz)
    occupati = _occupati(operatori, inizio_finestra, fine_finestra)
    risultato = []
    giorno = dal
    while giorno <= al:
        for orario in (o for o in orari if o.giorno == giorno.weekday()):
            ora = timezone.make_aware(datetime.datetime.combine(giorno, orario.dalle), tz)
            chiusura = timezone.make_aware(datetime.datetime.combine(giorno, orario.alle), tz)
            while ora + durata <= chiusura:
                if ora >= minimo:
                    liberi = [o for o in operatori if _libero(occupati[o.pk], ora, ora + durata + pausa)]
                    if liberi:
                        risultato.append((ora, liberi))
                ora += passo
        giorno += datetime.timedelta(days=1)
    risultato.sort(key=lambda f: f[0])
    return risultato


def link(prenotazione):
    token = signing.dumps(prenotazione.pk, salt=SALE)
    return f"{settings.SITO_URL}{reverse('calendario:prenotazione', args=[token])}"


def da_token(token):
    try:
        pk = signing.loads(token, salt=SALE, max_age=400 * 86400)
    except (signing.BadSignature, ValueError, TypeError):
        return None
    return Prenotazione.objects.filter(pk=pk).select_related("tipo", "operatore", "azienda").first()


def _contatto(azienda, nome, email, telefono, societa):
    from contatti.models import Contatto
    contatto = Contatto.objects.filter(azienda=azienda, email__iexact=email).order_by("pk").first()
    if contatto is None:
        contatto = Contatto.objects.create(azienda=azienda, tipo=Contatto.PERSONA, nome=nome, email=email,
                                           telefono=telefono, cliente=False)
        if societa:
            ditta = Contatto.objects.filter(azienda=azienda, tipo=Contatto.AZIENDA, nome__iexact=societa).first()
            if ditta:
                contatto.societa = ditta
                contatto.save(update_fields=["societa"])
    return contatto


def _opportunita(prenotazione):
    if not (prenotazione.tipo.crea_opportunita and apps.is_installed("crm")):
        return None
    from crm.models import FaseCrm, Opportunita
    if not FaseCrm.objects.exists():
        return None
    return Opportunita.objects.create(
        azienda=prenotazione.azienda, titolo=f"{prenotazione.tipo.nome}: {prenotazione.societa or prenotazione.nome}",
        contatto=prenotazione.contatto, nome_contatto=prenotazione.nome, email=prenotazione.email,
        telefono=prenotazione.telefono, commerciale=prenotazione.operatore, note=prenotazione.note,
        origine=f"Prenotazione online: {prenotazione.tipo.nome}")


def prenota(tipo, inizio, nome, email, telefono="", societa="", note=""):
    """Prenota la fascia che inizia a `inizio`. ValidationError se non è più libera."""
    nome, email = nome.strip()[:200], email.strip()[:254]
    if not nome or not email:
        raise ValidationError("Indica nome ed email.")
    with transaction.atomic():
        TipoAppuntamento.objects.select_for_update().get(pk=tipo.pk)       # una prenotazione alla volta per tipo
        giorno = timezone.localdate(inizio)
        libere = dict(fasce(tipo, dal=giorno, giorni=0))
        liberi = libere.get(inizio)
        if not liberi:
            raise ValidationError("L'orario scelto non è più libero: scegline un altro.")
        # il primo libero con meno appuntamenti quel giorno
        operatore = min(liberi, key=lambda o: (Prenotazione.objects.filter(
            operatore=o, stato=Prenotazione.CONFERMATA, inizio__date=giorno).count(), o.pk))
        fine = inizio + datetime.timedelta(minutes=tipo.durata)
        contatto = _contatto(tipo.azienda, nome, email, telefono.strip()[:40], societa.strip()[:200])
        dettagli = "\n".join(r for r in [f"Prenotato da {nome} <{email}>" + (f", tel. {telefono}" if telefono else ""),
                                         f"Azienda: {societa}" if societa else "", note] if r)
        evento = Evento.objects.create(azienda=tipo.azienda, titolo=f"{tipo.nome}: {nome}", inizio=inizio, fine=fine,
                                       luogo=tipo.luogo, descrizione=dettagli, organizzatore=operatore,
                                       promemoria=tipo.promemoria)
        evento.partecipanti.add(operatore)
        evento.contatti.add(contatto)
        p = Prenotazione.objects.create(azienda=tipo.azienda, tipo=tipo, inizio=inizio, fine=fine, operatore=operatore,
                                        evento=evento, nome=nome, email=email, telefono=telefono.strip()[:40],
                                        societa=societa.strip()[:200], note=note.strip()[:2000], contatto=contatto)
        opp = _opportunita(p)
        if opp:
            p.opportunita_id = opp.pk
            p.save(update_fields=["opportunita_id"])
        transaction.on_commit(lambda: lavori.accoda("calendario.prenotazioni.invia_conferma", prenotazione_id=p.pk))
        transaction.on_commit(lambda: lavori.accoda("calendario.lavori.invia_inviti", evento_id=evento.pk))
    return p


def _quando(p):
    return f"{timezone.localtime(p.inizio):%d/%m/%Y alle %H:%M}"


def _brand():
    return settings.THEME.get("brand", "")


def invia_conferma(prenotazione_id):
    p = Prenotazione.objects.select_related("tipo", "operatore", "evento").get(pk=prenotazione_id)
    if p.stato != Prenotazione.CONFERMATA or p.evento is None:
        return 0
    testo = (f"Gentile {p.nome},\n\nil suo appuntamento «{p.tipo.nome}» è confermato per il {_quando(p)}"
             + (f", {p.tipo.luogo}" if p.tipo.luogo else "") + ".\n"
             + (f"La riceverà {p.operatore.get_full_name() or p.operatore.username}.\n" if p.operatore else "")
             + f"\nPer annullarlo: {link(p)}\n")
    email = EmailMessage(f"[{_brand()}] Appuntamento confermato: {p.tipo.nome} ({_quando(p)})", testo, to=[p.email])
    email.attach("appuntamento.ics", ics(p.evento, "REQUEST"), "text/calendar; method=REQUEST; charset=utf-8")
    email.send()
    return 1


def annulla(p, da_cliente=True, motivo=""):
    if p.stato == Prenotazione.ANNULLATA:
        return
    evento = p.evento
    p.stato, p.annullata_il, p.evento = Prenotazione.ANNULLATA, timezone.now(), None
    p.save(update_fields=["stato", "annullata_il", "evento"])
    if evento:
        cancellazione = ics(evento, "CANCEL").replace("END:VEVENT", "STATUS:CANCELLED\r\nEND:VEVENT")
        evento.delete()
    else:
        cancellazione = None
    chi = "dal cliente" if da_cliente else "da noi"
    if p.operatore and p.operatore.email:
        EmailMessage(f"[{_brand()}] Appuntamento annullato: {p.tipo.nome} ({_quando(p)})",
                     f"{p.nome} <{p.email}>: l'appuntamento del {_quando(p)} è stato annullato {chi}."
                     + (f"\nMotivo: {motivo}" if motivo else ""), to=[p.operatore.email]).send()
    if not da_cliente:
        email = EmailMessage(f"[{_brand()}] Appuntamento annullato: {p.tipo.nome} ({_quando(p)})",
                             f"Gentile {p.nome},\n\nil suo appuntamento del {_quando(p)} è stato annullato."
                             + (f"\nMotivo: {motivo}" if motivo else "") + "\n\nPuò prenotarne un altro: "
                             + f"{settings.SITO_URL}{reverse('calendario:prenota', args=[p.tipo.codice])}", to=[p.email])
        if cancellazione:
            email.attach("annullato.ics", cancellazione, "text/calendar; method=CANCEL; charset=utf-8")
        email.send()


def promemoria_clienti(adesso=None):
    """I promemoria ai clienti, con il tempo scelto nel tipo di appuntamento."""
    adesso = adesso or timezone.now()
    vicine = Prenotazione.objects.filter(stato=Prenotazione.CONFERMATA, promemoria_inviato=False, inizio__gt=adesso,
                                         inizio__lte=adesso + datetime.timedelta(days=1), tipo__promemoria__gt=0
                                         ).select_related("tipo")
    inviati = 0
    for p in vicine:
        if p.inizio - datetime.timedelta(minutes=p.tipo.promemoria) > adesso:
            continue
        EmailMessage(f"[{_brand()}] Promemoria: {p.tipo.nome} ({_quando(p)})",
                     f"Gentile {p.nome},\n\nle ricordiamo l'appuntamento «{p.tipo.nome}» del {_quando(p)}"
                     + (f", {p.tipo.luogo}" if p.tipo.luogo else "") + f".\n\nSe non può venire, lo annulli qui: {link(p)}\n",
                     to=[p.email]).send()
        Prenotazione.objects.filter(pk=p.pk).update(promemoria_inviato=True)
        inviati += 1
    return inviati
