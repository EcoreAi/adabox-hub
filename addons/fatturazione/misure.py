"""Misure aziendali della Fatturazione (core.misure): fatturato, fatture emesse, da incassare, scaduto, incassato."""
from django.utils import timezone

from core.misure import Componente, Misura, registra

from .models import Fattura

# le fatture di vendita: niente note di credito (si sottraggono) né autofatture (sono acquisti)
VENDITE = [t for t, _ in Fattura.TIPI if t != Fattura.NOTA_CREDITO and t not in Fattura.AUTOFATTURE]
EMESSE_DI_VENDITA = {"stato": Fattura.EMESSA, "tipo__in": VENDITE}
NOTE_DI_CREDITO = {"stato": Fattura.EMESSA, "tipo": Fattura.NOTA_CREDITO}
APERTE = {"pagata": False, "fattura__stato": Fattura.EMESSA}

registra(Misura(
    nome="fatturazione.fatturato", etichetta="Fatturato",
    definizione="imponibile delle fatture emesse (IVA esclusa) meno quello delle note di credito, per data della fattura",
    sinonimi=("vendite", "ricavi", "fatturato"),
    raggruppamenti={"cliente": "cliente", "giorno": "data:giorno", "settimana": "data:settimana", "mese": "data:mese",
                    "anno": "data:anno"},
    periodo_su="data",
    componenti=(Componente("fatturazione.fatture", "sum:imponibile", EMESSE_DI_VENDITA),
                Componente("fatturazione.fatture", "sum:imponibile", NOTE_DI_CREDITO, segno=-1))))

registra(Misura(
    nome="fatturazione.fatture_emesse", etichetta="Fatture emesse", unita="",
    definizione="numero di fatture di vendita emesse, note di credito escluse, per data della fattura",
    raggruppamenti={"cliente": "cliente", "mese": "data:mese"}, periodo_su="data",
    componenti=(Componente("fatturazione.fatture", "count", EMESSE_DI_VENDITA),)))

registra(Misura(
    nome="fatturazione.da_incassare", etichetta="Da incassare",
    definizione="quanto resta da incassare delle scadenze aperte delle fatture emesse (importo meno incassato)",
    sinonimi=("crediti aperti", "da incassare"), raggruppamenti={"cliente": "fattura__cliente"},
    componenti=(Componente("fatturazione.scadenze", "sum:importo", APERTE),
                Componente("fatturazione.scadenze", "sum:incassato", APERTE, segno=-1))))


def _gia_scadute(request, di=""):
    return {"data__lt": timezone.localdate().isoformat()}


registra(Misura(
    nome="fatturazione.scaduto", etichetta="Scaduto",
    definizione="quanto resta da incassare delle scadenze aperte delle fatture emesse con scadenza prima di oggi",
    sinonimi=("insoluti", "scaduto", "chi ci deve dei soldi"), raggruppamenti={"cliente": "fattura__cliente"},
    filtri_dinamici=_gia_scadute,
    componenti=(Componente("fatturazione.scadenze", "sum:importo", APERTE),
                Componente("fatturazione.scadenze", "sum:incassato", APERTE, segno=-1))))

registra(Misura(
    nome="fatturazione.incassato", etichetta="Incassato",
    definizione="incassi registrati sulle scadenze (compensazioni e abbuoni esclusi), per data dell'incasso",
    sinonimi=("incassi",), raggruppamenti={"mese": "data:mese"},
    periodo_su="data",
    componenti=(Componente("fatturazione.incassi", "sum:importo", {"tipo": "incasso"}),)))
