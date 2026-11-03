"""Tutti i kanban dei moduli: card ricche, e gli stati dei documenti non si cambiano trascinando."""
import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone

import fiscale
import helpdesk
import progetti
from contatti.models import Contatto
from core.models import Azienda
from core.viste import registry
from fatturazione.models import Fattura, RigaFattura, Scadenza
from helpdesk.models import FaseTicket, Ticket
from progetti.models import Compito, FaseCompito, Progetto, TipoCompito
from vendite.models import OrdineVendita


@pytest.fixture
def scena(db, client):
    for f in (Path(fiscale.__file__).parent / "data" / "iniziali.json", Path(progetti.__file__).parent / "data" / "fasi.json",
              Path(helpdesk.__file__).parent / "data" / "iniziali.json"):
        call_command("loaddata", str(f), verbosity=0)
    client.force_login(User.objects.create_superuser("root", "r@example.com", "x", first_name="Anna", last_name="Neri"))
    azienda = Azienda.objects.get(pk=1)
    return {"az": azienda, "cliente": Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True, partita_iva="12345678903"),
            "io": User.objects.get(username="root")}


def _viste():
    from django.apps import apps
    return [v for c in apps.get_app_configs() for v in registry.viste_di(c.label) if v.kanban_group]


def test_ogni_kanban_e_ricco_e_si_apre(scena, client):
    viste = _viste()
    assert len(viste) >= 18
    for v in viste:
        r = client.get(v.url("kanban"))
        assert r.status_code == 200, v
        assert v.kanban_ricco and "is-ricco" in r.content.decode(), v


@pytest.mark.parametrize("modello,attesa", [("fatturazione.Fattura", False), ("vendite.OrdineVendita", False), ("acquisti.OrdineAcquisto", False),
                                            ("magazzino.Consegna", False), ("magazzino.Ricevimento", False), ("spese.NotaSpese", False),
                                            ("personale.Assenza", False), ("documenti.Richiesta", False), ("todo.Attivita", True),
                                            ("progetti.Compito", True), ("helpdesk.Ticket", True), ("crm.Opportunita", True)])
def test_gli_stati_dei_documenti_non_si_trascinano(db, modello, attesa):
    from django.apps import apps
    assert registry.per_modello(apps.get_model(modello)).kanban_spostabile() is attesa


def test_una_fattura_non_si_emette_trascinandola(scena, client):
    f = Fattura.objects.create(azienda=scena["az"], cliente=scena["cliente"])
    RigaFattura.objects.create(fattura=f, descrizione="Prova", prezzo=100)
    f.ricalcola()
    vista = registry.per_modello(Fattura)
    html = client.get(vista.url("kanban")).content.decode()
    assert "data-trascinabile" not in html
    assert client.post(vista.url("sposta", pk=f.pk), {"valore": Fattura.EMESSA}).status_code == 403
    f.refresh_from_db()
    assert f.stato == Fattura.BOZZA and not f.numero


def test_fattura_scaduta_incassata_e_note_di_credito(scena, client):
    oggi = timezone.localdate()
    f = Fattura.objects.create(azienda=scena["az"], cliente=scena["cliente"], stato=Fattura.EMESSA, numero="1/2026", totale=D(1000))
    s = Scadenza.objects.create(fattura=f, data=oggi - datetime.timedelta(days=2), importo=D(1000))
    Fattura.objects.create(azienda=scena["az"], cliente=scena["cliente"], stato=Fattura.EMESSA, numero="2/2026", tipo=Fattura.NOTA_CREDITO, totale=D(300))
    html = client.get(registry.per_modello(Fattura).url("kanban")).content.decode()
    assert "is-accento-rosso" in html and "Scaduta il" in html and "700 €" in html
    Scadenza.objects.filter(pk=s.pk).update(pagata=True)
    assert "Incassata" in client.get(registry.per_modello(Fattura).url("kanban")).content.decode()


def test_compiti_tipo_stella_blocco_avatar_e_query(scena, client, django_assert_max_num_queries):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    p = Progetto.objects.create(azienda=scena["az"], nome="Portale")
    tipo = TipoCompito.objects.create(nome="Prova tipo", colore="#16a34a")
    strano = TipoCompito.objects.create(nome="Strano", colore='"><b>x')
    a = Compito.objects.create(azienda=scena["az"], progetto=p, titolo="Base", ore_previste=D(8), tipo=tipo, priorita=Compito.ALTA, punti=5)
    a.assegnatari.add(scena["io"])
    b = Compito.objects.create(azienda=scena["az"], progetto=p, titolo="Dopo", tipo=strano, fase=a.fase, scadenza=timezone.localdate() - datetime.timedelta(days=1))
    b.bloccato_da.add(a)
    url = registry.per_modello(Compito).url("kanban")
    with CaptureQueriesContext(connection) as una:
        html = client.get(url).content.decode()
    for testo in ('style="--ui-tinta:#16a34a"', "5 punti · 8 h previste", "Bloccato da 1 compito", "Priorità: Alta", ">AN<", "is-accento-rosso", "8 h previste"):
        assert testo in html, testo
    assert "<b>x" not in html
    for i in range(6):
        c = Compito.objects.create(azienda=scena["az"], progetto=p, titolo=f"Altro {i}", tipo=tipo, fase=a.fase)
        c.assegnatari.add(scena["io"])
        c.bloccato_da.add(a)
    with django_assert_max_num_queries(len(una)):
        client.get(url)


def test_ticket_sla_e_fase_chiusa_verde(scena, client):
    fase = FaseTicket.objects.filter(chiusa=False).first()
    Ticket.objects.create(azienda=scena["az"], oggetto="Urgente", fase=fase, priorita=Ticket.URGENTE, scadenza_sla=timezone.now() - datetime.timedelta(hours=1))
    Ticket.objects.create(azienda=scena["az"], oggetto="Vicino", fase=fase, scadenza_sla=timezone.now() + datetime.timedelta(hours=1))
    Ticket.objects.create(azienda=scena["az"], oggetto="Fatto", fase=FaseTicket.objects.filter(chiusa=True).first())
    Ticket.objects.filter(oggetto="Urgente").update(scadenza_sla=timezone.now() - datetime.timedelta(hours=1))
    Ticket.objects.filter(oggetto="Vicino").update(scadenza_sla=timezone.now() + datetime.timedelta(hours=1))
    html = client.get(registry.per_modello(Ticket).url("kanban")).content.decode()
    for testo in ("SLA scaduto il", "SLA entro le", "is-accento-verde", "Priorità: Urgente", 'ui-kanban-col ui-tinta-verde'):
        assert testo in html, testo


def test_preventivo_rifiutato_online(scena, client):
    OrdineVendita.objects.create(azienda=scena["az"], cliente=scena["cliente"], numero="PV/1", stato=OrdineVendita.INVIATO, risposta=OrdineVendita.RIFIUTATO, totale=D(1234))
    html = client.get(registry.per_modello(OrdineVendita).url("kanban")).content.decode()
    assert "Rifiutato online" in html and "1.234 €" in html
