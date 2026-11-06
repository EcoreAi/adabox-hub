"""Invio dell'ordine al fornitore con il PDF (nel worker)."""
from django.contrib.auth import get_user_model

from core import chatter, modelli_email, report
from core.viste.gruppi import numero

from .models import OrdineAcquisto


def invia(ordine_id, utente_id=None):
    from core.viste import registry
    ordine = OrdineAcquisto.objects.select_related("fornitore", "azienda").get(pk=ordine_id)
    utente = get_user_model().objects.filter(pk=utente_id).first()
    richiesta = type("Richiesta", (), {"user": utente, "azienda": ordine.azienda})()
    email = modelli_email.messaggio("acquisti.ordine", ordine.azienda, {
        "numero": str(ordine), "fornitore": ordine.fornitore.nome, "data": f"{ordine.data:%d/%m/%Y}",
        "totale": f"{numero(ordine.totale)} €"}, [ordine.fornitore.email])
    try:
        email.attach(f"{ordine}".replace("/", "-") + ".pdf",
                     report.pdf(report.html(registry.per_modello(OrdineAcquisto), richiesta, [ordine], 0)),
                     "application/pdf")
    except report.ReportNonDisponibile:
        pass
    email.send()
    chatter.scrivi(ordine, utente, f"Ordine inviato a {ordine.fornitore.email}.", tipo="nota")
