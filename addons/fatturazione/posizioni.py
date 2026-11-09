"""Quale aliquota vale per un cliente: dichiarazione d'intento attiva (N3.5), poi la posizione fiscale scelta per lui
o quella automatica per nazione e partita IVA, altrimenti quella del prodotto."""
from django.utils import timezone

PAESI_UE = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "EL", "HR", "HU", "IE", "LT", "LU", "LV",
            "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK"}          # l'Italia a parte


def posizione_di(contatto):
    from .models import PosizioneContatto, PosizioneFiscale
    if contatto is None:
        return None
    scelta = PosizioneContatto.objects.filter(contatto=contatto).select_related("posizione").first()
    if scelta is not None:
        return scelta.posizione if scelta.posizione and scelta.posizione.attiva else None
    nazione = (contatto.nazione or "IT").upper()
    if nazione == "IT":
        return None
    if nazione in PAESI_UE:
        ambito = PosizioneFiscale.UE_B2B if contatto.partita_iva else None
    else:
        ambito = PosizioneFiscale.EXTRA_UE
    return PosizioneFiscale.objects.filter(ambito=ambito, attiva=True).first() if ambito else None


def dichiarazione_attiva(contatto, data=None, azienda=None):
    from .models import DichiarazioneIntento
    if contatto is None:
        return None
    data = data or timezone.localdate()
    qs = DichiarazioneIntento.objects.filter(cliente=contatto, dal__lte=data, al__gte=data).order_by("dal", "pk")
    if azienda is not None:
        qs = qs.filter(azienda=azienda)
    return next((d for d in qs if d.residuo > 0), None)


def aliquota_per(contatto, prodotto, aliquota, data=None):
    """L'aliquota da usare sulla riga per questo cliente, partendo da quella del prodotto. Solo le aliquote con IVA
    cambiano: un'esenzione già scelta resta."""
    from fiscale.models import AliquotaIva
    if aliquota is None or aliquota.percentuale == 0:
        return aliquota
    if dichiarazione_attiva(contatto, data) is not None:
        n35 = AliquotaIva.objects.filter(natura="N3.5", attiva=True).order_by("pk").first()
        if n35 is not None:
            return n35
    posizione = posizione_di(contatto)
    if posizione is None:
        return aliquota
    tipo = getattr(prodotto, "tipo", None)
    for r in posizione.regole.select_related("da_aliquota", "a_aliquota"):
        if r.tipo_prodotto != r.TUTTI and r.tipo_prodotto != tipo:
            continue
        if r.da_aliquota_id and r.da_aliquota_id != aliquota.pk:
            continue
        return r.a_aliquota
    return aliquota


def scorporo(prezzo, aliquota):
    """Il prezzo senza IVA da uno IVA inclusa."""
    from decimal import Decimal
    if prezzo is None or aliquota is None or not aliquota.percentuale:
        return prezzo
    return (Decimal(prezzo) * 100 / (100 + aliquota.percentuale)).quantize(Decimal("0.0001"))
