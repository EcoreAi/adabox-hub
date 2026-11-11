"""I sistemi esterni gestiti: per ognuno il connettore vero e la sua prova (stesso codice, trasporto finto)."""
from django.utils import timezone

from core import cifratura

from . import hubspot, prova, prova_salesforce, prova_zoho, salesforce, zoho
from .base import Deposito, ErroreConnettore

PROVE = {"hubspot": prova, "salesforce": prova_salesforce, "zoho": prova_zoho}


class DepositoCollegamento(Deposito):
    """Il token di accesso cifrato sul collegamento, finché non scade: lo condividono tutti i lavori."""

    def __init__(self, collegamento):
        self.collegamento = collegamento

    def leggi(self):
        c = self.collegamento
        if c.accesso_cifrato and c.accesso_scade and c.accesso_scade > timezone.now():
            try:
                return cifratura.decifra(c.accesso_cifrato)
            except Exception:                   # chiave cambiata: se ne chiede uno nuovo
                return None
        return None

    def salva(self, token, scade):
        c = self.collegamento
        c.accesso_cifrato, c.accesso_scade = cifratura.cifra(token), scade
        type(c).objects.filter(pk=c.pk).update(accesso_cifrato=c.accesso_cifrato, accesso_scade=scade)


def prova_di(collegamento):
    return PROVE[collegamento.sistema]


def client(collegamento):
    """Il connettore del collegamento: in prova parla con il sistema finto, se no con quello vero e le credenziali."""
    s, in_prova = collegamento.sistema, collegamento.modalita == "prova"
    if s not in PROVE:
        raise ErroreConnettore(f"Sistema non gestito: {s}")
    if s == "hubspot":
        if in_prova:
            return hubspot.HubSpot("prova", transport=prova.trasporto(collegamento))
        if not collegamento.token_cifrato:
            raise ErroreConnettore("Manca il token: inseriscilo nel collegamento.")
        return hubspot.HubSpot(collegamento.token())
    deposito = DepositoCollegamento(collegamento)
    if s == "salesforce":
        if in_prova:
            return salesforce.Salesforce(prova_salesforce.DOMINIO, "prova", "prova", deposito=deposito, transport=prova_salesforce.trasporto(collegamento))
        if not (collegamento.indirizzo and collegamento.client_id and collegamento.segreto_cifrato):
            raise ErroreConnettore("Mancano My Domain, client id o client secret: inseriscili nel collegamento.")
        return salesforce.Salesforce(collegamento.indirizzo, collegamento.client_id, collegamento.segreto(), deposito=deposito)
    if in_prova:
        return zoho.Zoho(prova_zoho.CENTRO, "prova", "prova", "prova", deposito=deposito, transport=prova_zoho.trasporto(collegamento))
    if not (collegamento.indirizzo and collegamento.client_id and collegamento.segreto_cifrato and collegamento.token_cifrato):
        raise ErroreConnettore("Mancano data center, client id, client secret o refresh token: inseriscili nel collegamento.")
    return zoho.Zoho(collegamento.indirizzo, collegamento.client_id, collegamento.segreto(), collegamento.token(), deposito=deposito)

