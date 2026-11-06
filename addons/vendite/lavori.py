"""Invio del preventivo o dell'ordine al cliente, con il PDF allegato (nel worker)."""
from django.contrib.auth import get_user_model

from core import chatter, modelli_email, report
from core.viste.gruppi import numero

from . import operazioni
from .models import OrdineVendita


def invia(ordine_id, utente_id=None):
    from core.viste import registry
    ordine = OrdineVendita.objects.select_related("cliente", "azienda").get(pk=ordine_id)
    vista = registry.per_modello(OrdineVendita)
    utente = get_user_model().objects.filter(pk=utente_id).first()
    richiesta = type("Richiesta", (), {"user": utente, "azienda": ordine.azienda})()
    codice = "vendite.ordine" if ordine.titolo_documento == "Ordine" else "vendite.preventivo"
    email = modelli_email.messaggio(codice, ordine.azienda, {
        "numero": str(ordine), "cliente": ordine.cliente.nome, "data": f"{ordine.data:%d/%m/%Y}",
        "totale": f"{numero(ordine.totale)} €", "valido_fino_al": f"{ordine.validita:%d/%m/%Y}" if ordine.validita else "",
        "link": operazioni.link(ordine) if ordine.stato == OrdineVendita.INVIATO else ""},
        [ordine.cliente.email])
    try:
        email.attach(f"{ordine}".replace("/", "-") + ".pdf", report.pdf(report.html(vista, richiesta, [ordine], 0)),
                     "application/pdf")
        allegato = "con il PDF"
    except report.ReportNonDisponibile:
        allegato = "senza PDF (stampa non disponibile su questo server)"
    email.send()
    chatter.scrivi(ordine, utente, f"{ordine.titolo_documento} inviato a {ordine.cliente.email} {allegato}.",
                   tipo="nota")
    return ordine.cliente.email
