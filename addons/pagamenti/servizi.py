"""Avviare un pagamento online e confermarlo: l'incasso si registra una volta sola, con incassa_fattura, quando il
fornitore dice che è pagato (al ritorno dal pagamento o con il webhook, chi arriva prima)."""
from decimal import Decimal

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from fatturazione import operazioni as fatture
from fatturazione.models import Fattura

from . import fornitori
from .models import FornitorePagamento, Pagamento

SALE_LINK = "pagamenti.fattura"
GIORNI_LINK = 90


def fornitore_attivo(azienda):
    return FornitorePagamento.objects.filter(azienda=azienda, attivo=True).order_by("pk").first() if azienda else None


def pagabile(fattura):
    """Si paga online una fattura emessa con qualcosa da pagare, se l'azienda ha un fornitore attivo."""
    return (fattura.stato == Fattura.EMESSA and fattura.tipo != Fattura.NOTA_CREDITO and not fattura.pagata
            and fattura.residuo > 0 and fornitore_attivo(fattura.azienda) is not None)


def link(fattura):
    """Il link firmato per pagare senza accesso al portale (per le email): vale GIORNI_LINK giorni."""
    token = signing.dumps([fattura.pk, fattura.azienda_id], salt=SALE_LINK)
    return f"{settings.SITO_URL}{reverse('pagamenti:fattura', args=[token])}"


def da_token(token):
    try:
        pk, azienda_id = signing.loads(token, salt=SALE_LINK, max_age=GIORNI_LINK * 86400)
    except (signing.BadSignature, ValueError, TypeError):
        return None
    return Fattura.objects.filter(pk=pk, azienda_id=azienda_id).select_related("cliente", "azienda").first()


def avvia(fattura):
    """Crea il pagamento e la pagina del fornitore: restituisce il Pagamento (con url_pagamento)."""
    fornitore = fornitore_attivo(fattura.azienda)
    if fornitore is None or not pagabile(fattura):
        raise fornitori.ErrorePagamento("Questa fattura non si può pagare online.")
    pagamento = Pagamento.objects.create(azienda=fattura.azienda, fattura=fattura, fornitore=fornitore, importo=fattura.residuo)
    firma = signing.dumps(pagamento.pk, salt="pagamenti.esito")
    ritorno = f"{settings.SITO_URL}{reverse('pagamenti:esito', args=[pagamento.pk, firma])}"
    annulla = f"{ritorno}?annullato=1"
    try:
        pagamento.id_esterno, pagamento.url_pagamento = fornitori.crea_sessione(fornitore, pagamento, ritorno, annulla)
    except fornitori.ErrorePagamento as e:
        pagamento.stato, pagamento.nota = Pagamento.FALLITO, str(e)[:300]
        pagamento.save(update_fields=["stato", "nota"])
        raise
    pagamento.save(update_fields=["id_esterno", "url_pagamento"])
    return pagamento


@transaction.atomic
def conferma(pagamento, riferimento=""):
    """Registra l'incasso del pagamento confermato dal fornitore. Idempotente: una seconda conferma non fa nulla."""
    pagamento = Pagamento.objects.select_for_update().select_related("fattura").get(pk=pagamento.pk)
    if pagamento.stato == Pagamento.PAGATO:
        return pagamento
    fattura = pagamento.fattura
    importo = min(pagamento.importo, fattura.residuo)
    if importo > Decimal(0):
        fatture.incassa_fattura(fattura, importo, metodo="carta", riferimento=f"{pagamento.fornitore or 'online'} {riferimento}"[:120])
        if importo < pagamento.importo:
            pagamento.nota = f"Pagati {pagamento.importo} €, ne restavano {importo}: il resto è da rimborsare."
    else:
        pagamento.nota = "La fattura risultava già incassata: da rimborsare o da verificare."
    pagamento.stato, pagamento.riferimento, pagamento.completato_il = Pagamento.PAGATO, riferimento[:255], timezone.now()
    pagamento.save(update_fields=["stato", "riferimento", "completato_il", "nota"])
    return pagamento


def verifica(pagamento):
    """Chiede al fornitore e, se è pagato, registra l'incasso. Restituisce il pagamento aggiornato."""
    if pagamento.stato != Pagamento.AVVIATO or pagamento.fornitore is None:
        return pagamento
    pagato, riferimento = fornitori.esito(pagamento.fornitore, pagamento)
    return conferma(pagamento, riferimento) if pagato else pagamento
