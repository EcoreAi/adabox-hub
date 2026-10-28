"""Hook di installazione dei Documenti."""
from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile

from core.models import Azienda


def post_install(modulo):
    Group.objects.get(name="Documenti / Utente").user_set.add(*User.objects.filter(is_active=True))


def demo(modulo):
    """Tre cartelle con qualche documento di testo e una cartella riservata ai responsabili."""
    from . import servizi
    from .models import Cartella, Tag
    azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
    if Cartella.objects.filter(azienda=azienda).exists():
        return
    utente = User.objects.filter(is_superuser=True).order_by("pk").first()
    amministrazione = Cartella.objects.create(azienda=azienda, nome="Amministrazione")
    commerciale = Cartella.objects.create(azienda=azienda, nome="Commerciale")
    contratti = Cartella.objects.create(azienda=azienda, nome="Contratti", padre=commerciale)
    riservata = Cartella.objects.create(azienda=azienda, nome="Personale", descrizione="Solo per i responsabili")
    riservata.gruppi_lettura.set(Group.objects.filter(name="Documenti / Responsabile"))
    file = [(amministrazione, "Procedura note spese.txt", "Le note spese si consegnano entro il 5 del mese.", "Da rivedere"),
            (amministrazione, "Scadenzario 2026.csv", "data;descrizione\n16/11/2026;F24\n", None),
            (contratti, "Contratto quadro cliente.txt", "Bozza del contratto quadro di fornitura.", "Contratto"),
            (commerciale, "Listino servizi.txt", "Consulenza 60 €/h\nSviluppo 50 €/h", None),
            (riservata, "Regolamento interno.txt", "Orari, ferie e permessi.", "Riservato")]
    for cartella, nome, testo, tag in file:
        d = servizi.carica(cartella, ContentFile(testo.encode(), name=nome), utente)
        if tag:
            d.tag.add(Tag.objects.get(nome=tag))
