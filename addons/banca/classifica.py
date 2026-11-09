"""Movimenti senza fattura: classificati a mano o dalle regole, con categoria e conto per lo studio."""
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import MovimentoBanca, RegolaMovimento


def applica(azienda, movimenti=None):
    """Le regole attive dell'azienda sui movimenti da abbinare (tutti, o quelli indicati). Restituisce quanti ne classifica."""
    regole = list(RegolaMovimento.objects.filter(azienda=azienda, attiva=True))
    if not regole:
        return 0
    qs = movimenti if movimenti is not None else MovimentoBanca.objects.filter(azienda=azienda)
    fatti = 0
    for m in qs.filter(stato=MovimentoBanca.DA_ABBINARE, abbinamenti__isnull=True):
        regola = next((r for r in regole if r.corrisponde(m)), None)
        if regola is not None:
            m.stato, m.categoria, m.codice_studio, m.regola = MovimentoBanca.CLASSIFICATO, regola.categoria, regola.codice_studio, regola
            m.save(update_fields=["stato", "categoria", "codice_studio", "regola"])
            fatti += 1
    return fatti


@transaction.atomic
def classifica(movimento, categoria, codice_studio="", crea_regola=False):
    """A mano. Con crea_regola nasce anche la regola per i prossimi movimenti uguali (dalla controparte, o dalle prime
    parole della descrizione)."""
    categoria = (categoria or "").strip()[:80]
    if not categoria:
        raise ValidationError("Scrivi la categoria, per esempio Commissioni bancarie.")
    if movimento.abbinamenti.exists():
        raise ValidationError("Il movimento è abbinato a un documento: togli prima l'abbinamento.")
    regola = None
    if crea_regola:
        controparte = (movimento.controparte or "").strip()
        testo = " ".join((movimento.descrizione or "").split()[:3])
        if not controparte and not testo:
            raise ValidationError("Il movimento non ha né controparte né descrizione da cui fare una regola.")
        regola = RegolaMovimento.objects.create(
            azienda=movimento.azienda, nome=categoria, categoria=categoria, codice_studio=codice_studio[:40],
            controparte_contiene=controparte[:120], descrizione_contiene="" if controparte else testo[:200],
            segno=RegolaMovimento.ENTRATE if movimento.importo > 0 else RegolaMovimento.USCITE)
    movimento.stato, movimento.categoria, movimento.codice_studio, movimento.regola = (
        MovimentoBanca.CLASSIFICATO, categoria, codice_studio[:40], regola)
    movimento.save(update_fields=["stato", "categoria", "codice_studio", "regola"])
    if regola is not None:
        applica(movimento.azienda)
    return regola


def declassifica(movimento):
    if movimento.stato != MovimentoBanca.CLASSIFICATO:
        return
    movimento.stato, movimento.categoria, movimento.codice_studio, movimento.regola = MovimentoBanca.DA_ABBINARE, "", "", None
    movimento.save(update_fields=["stato", "categoria", "codice_studio", "regola"])


def categorie(azienda):
    """Le categorie già usate, per suggerirle."""
    usate = set(RegolaMovimento.objects.filter(azienda=azienda).values_list("categoria", flat=True))
    usate |= set(MovimentoBanca.objects.filter(azienda=azienda).exclude(categoria="").values_list("categoria", flat=True).distinct()[:200])
    return sorted(usate | {"Commissioni bancarie", "F24", "Stipendi", "Utenze", "Interessi", "Giroconto", "Prelievo"})
