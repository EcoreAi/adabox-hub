"""Le righe che si imputano: per ogni tipo, come si leggono importo con segno, data, documento e se il documento conta
(emesso, registrato, approvato). Ricavi positivi, costi negativi."""
from dataclasses import dataclass
from decimal import Decimal

from django.apps import apps
from django.contrib.contenttypes.models import ContentType


@dataclass
class Fonte:
    chiave: str                  # fatture, passive, spese
    nome: str
    modello: str                 # app_label.Model della riga
    categoria: str               # categoria del budget
    ricavo: bool

    def modello_cls(self):
        return apps.get_model(self.modello)

    def tipo(self):
        return ContentType.objects.get_for_model(self.modello_cls())

    def righe(self, azienda, dal=None, al=None, ids=None):
        """Il queryset delle righe dell'azienda nel periodo, dei soli documenti che contano."""
        M = self.modello_cls()
        if self.chiave == "fatture":
            from fatturazione.models import Fattura
            qs = M.objects.filter(fattura__azienda=azienda, fattura__stato=Fattura.EMESSA, is_bollo=False).select_related("fattura__cliente")
            campo = "fattura__data"
        elif self.chiave == "passive":
            qs = M.objects.filter(fattura__azienda=azienda).exclude(fattura__stato="contestata").select_related("fattura__fornitore")
            campo = "fattura__data"
        else:
            qs = M.objects.filter(nota__azienda=azienda, nota__stato__in=["approvata", "rimborsata"]).select_related("nota__dipendente", "categoria")
            campo = "data"
        if dal:
            qs = qs.filter(**{f"{campo}__gte": dal})
        if al:
            qs = qs.filter(**{f"{campo}__lte": al})
        if ids is not None:
            qs = qs.filter(pk__in=ids)
        return qs

    def importo(self, r):
        if self.chiave == "fatture":
            return -r.importo if r.fattura.tipo == "TD04" else r.importo
        if self.chiave == "passive":
            return r.importo if r.fattura.tipo_documento == "TD04" else -r.importo
        return -(r.importo or Decimal(0))

    def data(self, r):
        return r.fattura.data if self.chiave in ("fatture", "passive") else r.data

    def documento(self, r):
        return r.fattura if self.chiave in ("fatture", "passive") else r.nota

    def controparte(self, r):
        if self.chiave == "fatture":
            return r.fattura.cliente
        if self.chiave == "passive":
            return r.fattura.fornitore
        return r.nota.dipendente

    def descrizione(self, r):
        return r.descrizione if self.chiave != "spese" else f"{r.categoria}: {r.descrizione}"


FONTI = [Fonte("fatture", "Fatture emesse", "fatturazione.RigaFattura", "ricavi", True),
         Fonte("passive", "Fatture ricevute", "sdi.RigaPassiva", "acquisti", False),
         Fonte("spese", "Note spese", "spese.RigaSpesa", "spese", False)]


def disponibili():
    return [f for f in FONTI if apps.is_installed(f.modello.split(".")[0])]


def per_chiave(chiave):
    return next((f for f in disponibili() if f.chiave == chiave), None)


def per_tipo(tipo_id):
    for f in disponibili():
        if f.tipo().pk == tipo_id:
            return f
    return None


def documento_e_righe(documento):
    """(fonte, righe) per un documento: fattura, fattura ricevuta o nota spese."""
    nome = documento._meta.label
    if nome == "fatturazione.Fattura":
        return per_chiave("fatture"), list(documento.righe.filter(is_bollo=False))
    if nome == "sdi.FatturaPassiva":
        return per_chiave("passive"), list(documento.righe.all())
    if nome == "spese.NotaSpese":
        return per_chiave("spese"), list(documento.righe.select_related("categoria"))
    return None, []
