"""Varianti: da un modello «con varianti» e dai suoi attributi, un prodotto vero per ogni combinazione di valori.

Ogni variante è un Prodotto come gli altri (codice, giacenza, listini, righe dei documenti), legato al modello da
`variante_di`: così magazzino, ordini e fatture non devono sapere nulla delle varianti."""
import itertools
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Prodotto

COPIATI = ("tipo", "categoria", "unita", "unita_vendita", "unita_acquisto", "aliquota_iva", "costo", "peso")


def combinazioni(modello):
    """[(valore, ...)] di tutte le combinazioni dei valori scelti sul modello, nell'ordine degli attributi."""
    righe = [list(r.valori.select_related("attributo").order_by("ordine", "pk"))
             for r in modello.attributi.select_related("attributo").order_by("attributo__ordine", "attributo__nome")]
    if not righe or any(not valori for valori in righe):
        return []
    return list(itertools.product(*righe))


def _codice_libero(modello, sigle):
    base = f"{modello.codice}-{'-'.join(sigle)}" if modello.codice else "-".join(sigle)
    base, codice, n = base[:40], base[:40], 2
    while Prodotto.objects.filter(azienda_id=modello.azienda_id, codice=codice).exists():
        codice = f"{base[:36]}~{n}"
        n += 1
    return codice


@transaction.atomic
def genera(modello):
    """Crea le varianti che mancano e disattiva quelle la cui combinazione non c'è più (non si cancellano: possono
    avere movimenti e documenti). Restituisce (create, disattivate)."""
    if not modello.con_varianti:
        raise ValidationError("Segna il prodotto «con varianti» e scegli attributi e valori.")
    tutte = combinazioni(modello)
    if not tutte:
        raise ValidationError("Aggiungi almeno un attributo con i suoi valori (es. Taglia: S, M, L).")
    esistenti = {frozenset(v.valori.values_list("pk", flat=True)): v for v in modello.varianti.prefetch_related("valori")}
    valide, create = set(), 0
    for valori in tutte:
        chiave = frozenset(v.pk for v in valori)
        valide.add(chiave)
        if chiave in esistenti:
            continue
        nomi = ", ".join(v.nome for v in valori)
        descrizione = "\n".join(filter(None, [modello.descrizione_vendita or modello.nome,
                                              ", ".join(f"{v.attributo.nome}: {v.nome}" for v in valori)]))
        variante = Prodotto(
            azienda_id=modello.azienda_id, variante_di=modello, nome=f"{modello.nome} ({nomi})"[:200],
            codice=_codice_libero(modello, [v.sigla for v in valori]), descrizione_vendita=descrizione,
            prezzo_vendita=modello.prezzo_vendita + sum((v.sovrapprezzo for v in valori), Decimal(0)),
            attivo=modello.attivo, **{c: getattr(modello, c) for c in COPIATI})
        variante.save()
        variante.valori.set(valori)
        create += 1
    disattivate = 0
    for chiave, variante in esistenti.items():
        if chiave not in valide and variante.attivo:
            variante.attivo = False
            variante.save(update_fields=["attivo"])
            disattivate += 1
    return create, disattivate


def per_valori(modello, valori):
    """La variante del modello con esattamente quei valori (oggetti o pk), o None: per importazioni e API."""
    cercati = frozenset(getattr(v, "pk", v) for v in valori)
    for variante in modello.varianti.prefetch_related("valori"):
        if frozenset(v.pk for v in variante.valori.all()) == cercati:
            return variante
    return None


def sovrapprezzo(variante):
    """Di quanto la variante costa più del modello (può essere negativo): serve ai listini fatti sul modello."""
    if not variante.variante_di_id:
        return Decimal(0)
    return variante.prezzo_vendita - variante.variante_di.prezzo_vendita
