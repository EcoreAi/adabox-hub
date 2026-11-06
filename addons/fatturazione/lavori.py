"""Invio della fattura o della nota di credito al cliente, con il PDF allegato (nel worker)."""
from django.contrib.auth import get_user_model
from core import chatter, modelli_email, report
from core.viste.gruppi import numero

from .models import Fattura


def invia(fattura_id, utente_id=None):
    from core.viste import registry
    fattura = Fattura.objects.select_related("cliente", "azienda").get(pk=fattura_id)
    vista = registry.per_modello(Fattura)
    utente = get_user_model().objects.filter(pk=utente_id).first()
    richiesta = type("Richiesta", (), {"user": utente, "azienda": fattura.azienda})()
    documento = str(fattura)
    email = modelli_email.messaggio("fatturazione.invio", fattura.azienda, {
        "documento": documento, "documento_testo": f"{documento[0].lower()}{documento[1:]}", "numero": fattura.numero,
        "cliente": fattura.cliente.nome, "data": f"{fattura.data:%d/%m/%Y}", "totale": f"{numero(fattura.totale)} €",
        "da_pagare": f"{numero(fattura.da_incassare)} €"}, [fattura.cliente.email])
    try:
        email.attach(f"{fattura}".replace("/", "-") + ".pdf", report.pdf(report.html(vista, richiesta, [fattura], 0)),
                     "application/pdf")
        allegato = "con il PDF"
    except report.ReportNonDisponibile:
        allegato = "senza PDF (stampa non disponibile su questo server)"
    email.send()
    chatter.scrivi(fattura, utente, f"{fattura} inviata a {fattura.cliente.email} {allegato}.", tipo="nota")
    return fattura.cliente.email
