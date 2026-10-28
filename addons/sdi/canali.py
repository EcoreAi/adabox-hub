"""Canali di trasmissione verso lo SDI: manuale (portale), PEC, prova (simulatore). Uno per azienda (parametro)."""
import random

from django.core.mail import EmailMessage
from django.utils import timezone

from core import parametri

from .models import Trasmissione

NS_MESSAGGI = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/messaggi/v1.0"


class Manuale:
    nome = "manuale"

    def invia(self, trasmissione):
        """Niente da spedire: l'XML si scarica e si carica sul portale; poi si segna come caricato."""
        trasmissione.stato = Trasmissione.PRONTA
        trasmissione.save(update_fields=["stato"])
        return "XML pronto: scaricalo e caricalo sul portale «Fatture e Corrispettivi», poi segnalo come caricato."


class Prova:
    """Simula lo SDI: accetta il file e risponde subito con una ricevuta di consegna. Solo per demo e test."""
    nome = "prova"

    def invia(self, trasmissione):
        from . import notifiche
        trasmissione.stato, trasmissione.inviata_il = Trasmissione.INVIATA, timezone.now()
        trasmissione.save(update_fields=["stato", "inviata_il"])
        base = trasmissione.nome_file.removesuffix(".xml")
        notifiche.registra(ricevuta_consegna(trasmissione.nome_file), f"{base}_RC_001.xml")
        return "Inviata al simulatore dello SDI (canale di prova)."


def ricevuta_consegna(nome_file, identificativo=None):
    """XML di una ricevuta di consegna come quelle dello SDI (per il canale di prova e per i test)."""
    adesso = timezone.now().replace(microsecond=0).isoformat()
    identificativo = identificativo or str(random.randint(10**8, 10**9 - 1))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<ns3:RicevutaConsegna xmlns:ns3="{NS_MESSAGGI}" versione="1.0">'
            f"<IdentificativoSdI>{identificativo}</IdentificativoSdI><NomeFile>{nome_file}</NomeFile>"
            f"<DataOraRicezione>{adesso}</DataOraRicezione><DataOraConsegna>{adesso}</DataOraConsegna>"
            f"<Destinatario><Codice>0000000</Codice><Descrizione>Prova</Descrizione></Destinatario>"
            f"<MessageId>{identificativo}</MessageId></ns3:RicevutaConsegna>").encode()


class Pec:
    nome = "pec"

    def invia(self, trasmissione):
        from . import pec
        azienda = trasmissione.azienda
        mittente = parametri.leggi("sdi.pec_indirizzo", azienda)
        destinatario = parametri.leggi("sdi.indirizzo_sdi", azienda)
        smtp = parametri.leggi("sdi.pec_smtp", azienda)
        if not (mittente and destinatario and smtp):
            raise ValueError("Configura indirizzo PEC, server di invio e indirizzo dello SDI nelle impostazioni.")
        email = EmailMessage(f"Invio File {trasmissione.nome_file}", "Invio fattura elettronica.", mittente,
                             [destinatario], connection=pec.connessione_smtp(smtp))
        with trasmissione.file.open("rb") as f:
            email.attach(trasmissione.nome_file, f.read(), "application/xml")
        email.send()
        trasmissione.stato, trasmissione.inviata_il = Trasmissione.INVIATA, timezone.now()
        trasmissione.save(update_fields=["stato", "inviata_il"])
        return f"Inviata via PEC a {destinatario}: l'esito arriva sulla casella PEC."


CANALI = {c.nome: c for c in (Manuale, Pec, Prova)}


def per_azienda(azienda):
    return CANALI.get(parametri.leggi("sdi.canale", azienda), Manuale)()
