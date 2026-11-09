"""Controlli qualità della merce: al ricevimento la merce dei prodotti con un punto di controllo va in quarantena e
nasce il controllo da fare; superato, la merce passa in giacenza; respinto, resta in quarantena e si apre la non
conformità verso il fornitore. Prima della spedizione i controlli obbligatori devono essere superati."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ControlloQualita, Movimento, NonConformita, PuntoControllo, Ubicazione


def punti(azienda, fase, prodotto):
    return [p for p in PuntoControllo.objects.filter(azienda=azienda, fase=fase, attivo=True) if p.vale_per(prodotto)]


def ubicazione_quarantena(magazzino):
    u = Ubicazione.objects.filter(magazzino=magazzino, quarantena=True, attiva=True).first()
    if u is None:
        u = Ubicazione.objects.create(azienda=magazzino.azienda, magazzino=magazzino, codice="QUARANTENA", nome="Merce da controllare",
                                      quarantena=True)
    return u


def dopo_il_ricevimento(ricevimento):
    """Sposta in quarantena i carichi dei prodotti con controlli al ricevimento e crea i controlli da fare."""
    from django.contrib.contenttypes.models import ContentType

    from .models import Ricevimento
    ct = ContentType.objects.get_for_model(Ricevimento)
    creati = []
    for m in Movimento.objects.filter(content_type=ct, object_id=ricevimento.pk, quantita__gt=0).select_related("prodotto"):
        da_fare = punti(ricevimento.azienda, PuntoControllo.RICEVIMENTO, m.prodotto)
        if not da_fare:
            continue
        q = ubicazione_quarantena(ricevimento.magazzino)
        Movimento.objects.filter(pk=m.pk).update(ubicazione=q)
        for p in da_fare:
            creati.append(ControlloQualita.objects.create(azienda=ricevimento.azienda, punto=p, prodotto=m.prodotto, quantita=m.quantita,
                                                          lotto=m.lotto, ricevimento=ricevimento))
    return creati


@transaction.atomic
def registra(controllo, esito, utente=None, nota=""):
    if controllo.esito != ControlloQualita.DA_FARE:
        raise ValidationError("Il controllo è già registrato.")
    if esito not in (ControlloQualita.SUPERATO, ControlloQualita.RESPINTO):
        raise ValidationError("Esito non valido.")
    if esito == ControlloQualita.RESPINTO and not nota.strip():
        raise ValidationError("Scrivi che cosa non va.")
    controllo.esito, controllo.nota, controllo.controllato_da, controllo.controllato_il = esito, nota, utente, timezone.now()
    controllo.save(update_fields=["esito", "nota", "controllato_da", "controllato_il"])
    if controllo.ricevimento_id:
        r = controllo.ricevimento
        if esito == ControlloQualita.RESPINTO:
            NonConformita.objects.create(azienda=controllo.azienda, controllo=controllo, fornitore=r.fornitore, prodotto=controllo.prodotto,
                                         quantita=controllo.quantita, descrizione=nota)
        elif not ControlloQualita.objects.filter(ricevimento=r, prodotto=controllo.prodotto).exclude(esito=ControlloQualita.SUPERATO).exists():
            _libera(controllo, utente)                           # tutti i controlli del prodotto superati: in giacenza
    return controllo


def _libera(controllo, utente):
    from . import operazioni
    r = controllo.ricevimento
    q = ubicazione_quarantena(r.magazzino)
    operazioni.trasferisci(controllo.prodotto, controllo.quantita, r.magazzino, r.magazzino, q, Ubicazione.predefinita_di(r.magazzino),
                           utente, f"Controllo superato: {controllo.punto}", controllo.lotto)


def mancanti_per_spedire(consegna):
    """I controlli prima della spedizione non superati per i prodotti della consegna (li crea se mancano)."""
    mancano = []
    for riga in consegna.righe.select_related("prodotto"):
        for p in punti(consegna.azienda, PuntoControllo.CONSEGNA, riga.prodotto):
            c, _ = ControlloQualita.objects.get_or_create(azienda=consegna.azienda, punto=p, prodotto=riga.prodotto, consegna=consegna,
                                                          defaults={"quantita": riga.quantita})
            if c.esito != ControlloQualita.SUPERATO:
                mancano.append(c)
    return mancano
