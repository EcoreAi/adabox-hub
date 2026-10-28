"""Invio del preventivo o dell'ordine al cliente, con il PDF allegato (nel worker)."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage

from core import chatter, report

from .models import OrdineVendita


def invia(ordine_id, utente_id=None):
    from core.viste import registry
    ordine = OrdineVendita.objects.select_related("cliente", "azienda").get(pk=ordine_id)
    vista = registry.per_modello(OrdineVendita)
    utente = get_user_model().objects.filter(pk=utente_id).first()
    richiesta = type("Richiesta", (), {"user": utente, "azienda": ordine.azienda})()
    email = EmailMessage(f"{ordine.titolo_documento} {ordine} — {ordine.azienda}",
                         f"Gentile {ordine.cliente.nome},\nin allegato il {ordine.titolo_documento.lower()} {ordine}.\n\n"
                         f"Cordiali saluti\n{ordine.azienda}", to=[ordine.cliente.email])
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
