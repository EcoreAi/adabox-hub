"""Invio della fattura o della nota di credito al cliente, con il PDF allegato (nel worker)."""
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage

from core import chatter, report

from .models import Fattura


def invia(fattura_id, utente_id=None):
    from core.viste import registry
    fattura = Fattura.objects.select_related("cliente", "azienda").get(pk=fattura_id)
    vista = registry.per_modello(Fattura)
    utente = get_user_model().objects.filter(pk=utente_id).first()
    richiesta = type("Richiesta", (), {"user": utente, "azienda": fattura.azienda})()
    email = EmailMessage(f"{fattura} — {fattura.azienda}",
                         f"Gentile {fattura.cliente.nome},\nin allegato {str(fattura)[0].lower()}{str(fattura)[1:]}.\n\n"
                         f"Cordiali saluti\n{fattura.azienda}", to=[fattura.cliente.email])
    try:
        email.attach(f"{fattura}".replace("/", "-") + ".pdf", report.pdf(report.html(vista, richiesta, [fattura], 0)),
                     "application/pdf")
        allegato = "con il PDF"
    except report.ReportNonDisponibile:
        allegato = "senza PDF (stampa non disponibile su questo server)"
    email.send()
    chatter.scrivi(fattura, utente, f"{fattura} inviata a {fattura.cliente.email} {allegato}.", tipo="nota")
    return fattura.cliente.email
