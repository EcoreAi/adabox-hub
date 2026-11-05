"""Chi non ha un'azienda corrente non vede nulla: né i record, né i nomi nei filtri e nelle scelte dei form."""
import pytest
from django.contrib.auth.models import Permission, User
from django.forms import modelform_factory

from acquisti.models import OrdineAcquisto
from contatti.models import Contatto
from core.models import Azienda
from core.viste.base import form_per_azienda
from todo.models import Attivita

pytestmark = pytest.mark.django_db


@pytest.fixture
def scena(client):
    """Due aziende con dati propri; l'utente vede solo A, con i permessi per leggere e creare."""
    a, b = Azienda.objects.first(), Azienda.objects.create(nome="Azienda B")
    for azienda, sigla in ((a, "A"), (b, "B")):
        Attivita.objects.create(titolo=f"ATTIVITA-{sigla}", azienda=azienda)
        fornitore = Contatto.objects.create(azienda=azienda, nome=f"FORNITORE-{sigla}", fornitore=True)
        OrdineAcquisto.objects.create(azienda=azienda, fornitore=fornitore, numero=f"ORDINE-{sigla}")
    u = User.objects.create_user("utente", "u@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(codename__in=["view_attivita", "add_attivita", "view_ordineacquisto"]))
    u.profilo.aziende.set([a])
    u.profilo.azienda_predefinita = a
    u.profilo.save()
    client.force_login(u)
    return u, a, b


def _togli_aziende(u):
    u.profilo.aziende.clear()
    u.profilo.azienda_predefinita = None
    u.profilo.save()


def test_con_un_azienda_vede_solo_la_sua(client, scena):
    pagina = client.get("/todo/attivita/").content.decode()
    assert "ATTIVITA-A" in pagina and "ATTIVITA-B" not in pagina


@pytest.mark.parametrize("come", ["senza aziende", "azienda disattivata"])
def test_senza_azienda_corrente_la_lista_e_vuota(client, scena, come):
    u, a, b = scena
    if come == "senza aziende":
        _togli_aziende(u)
    else:
        u.profilo.aziende.set([b])
        Azienda.objects.filter(pk=b.pk).update(attiva=False)
    pagina = client.get("/todo/attivita/").content.decode()
    assert "ATTIVITA-A" not in pagina and "ATTIVITA-B" not in pagina


def test_senza_azienda_il_dettaglio_e_404(client, scena):
    _togli_aziende(scena[0])
    assert client.get(f"/todo/attivita/{Attivita.objects.first().pk}/").status_code == 404


def test_senza_azienda_non_si_crea(client, scena):
    _togli_aziende(scena[0])
    assert client.get("/todo/attivita/nuovo/").status_code == 403


def test_senza_azienda_i_filtri_non_mostrano_i_nomi(client, scena):
    assert "FORNITORE-B" not in client.get("/acquisti/ordini/").content.decode()
    _togli_aziende(scena[0])
    pagina = client.get("/acquisti/ordini/").content.decode()
    assert "FORNITORE-A" not in pagina and "FORNITORE-B" not in pagina and "ORDINE-B" not in pagina


def test_senza_azienda_il_kanban_e_vuoto(client, scena):
    _togli_aziende(scena[0])
    risposta = client.get("/acquisti/ordini/kanban/")
    assert risposta.status_code == 200
    pagina = risposta.content.decode()
    assert "FORNITORE-A" not in pagina and "ORDINE-B" not in pagina


def test_senza_azienda_le_scelte_dei_form_sono_vuote(scena):
    form = form_per_azienda(modelform_factory(OrdineAcquisto, fields=["fornitore"]), None)()
    assert not form.fields["fornitore"].queryset.exists()


def test_superuser_senza_aziende_non_fa_eccezione(client, scena):
    root = User.objects.create_superuser("root", "r@example.com", "pass12345!")
    _togli_aziende(root)
    client.force_login(root)
    assert "ATTIVITA-A" not in client.get("/todo/attivita/").content.decode()


def test_api_senza_azienda_non_restituisce_nulla(client, scena):
    from core.models import TokenApi
    u = scena[0]
    _, chiaro = TokenApi.genera(u, "prova")
    con_azienda = client.get("/api/v1/acquisti/ordini/", HTTP_AUTHORIZATION=f"Bearer {chiaro}")
    assert con_azienda.status_code == 200 and b"ORDINE-A" in con_azienda.content and b"ORDINE-B" not in con_azienda.content
    _togli_aziende(u)
    vuota = client.get("/api/v1/acquisti/ordini/", HTTP_AUTHORIZATION=f"Bearer {chiaro}")
    assert vuota.status_code == 200 and b"ORDINE-A" not in vuota.content and b"ORDINE-B" not in vuota.content


def _root_di(azienda):
    """Un superuser che lavora solo in un'azienda (o in nessuna): i permessi non contano, conta solo l'azienda."""
    root = User.objects.create_superuser("root", "r@example.com", "pass12345!")
    root.profilo.aziende.set([azienda] if azienda else [])
    root.profilo.azienda_predefinita = azienda
    root.profilo.save()
    return root


@pytest.mark.parametrize("url", ["/automazioni/", "/documenti/", "/banca/riconcilia/", "/capacita/carico/", "/fatturazione/scadenze/"])
def test_senza_azienda_le_pagine_rispondono_senza_errori(client, scena, url):
    """request.azienda è None davvero: i controlli `is None` scattano e i filtri non vanno in errore."""
    client.force_login(_root_di(None))
    assert client.get(url).status_code == 200


def test_senza_azienda_nessuno_spazio_documenti_viene_creato(client, scena):
    from documenti.models import Spazio
    client.force_login(_root_di(None))
    client.get("/documenti/")
    assert not Spazio.objects.exists()


def _fattura(azienda, sigla):
    from fatturazione.models import Fattura, Incasso, Scadenza
    cliente = Contatto.objects.create(azienda=azienda, nome=f"CLIENTE-{sigla}", cliente=True)
    fattura = Fattura.objects.create(azienda=azienda, cliente=cliente)
    scadenza = Scadenza.objects.create(fattura=fattura, data="2026-01-31", importo=100)
    return fattura, scadenza, Incasso.objects.create(scadenza=scadenza, data="2026-01-31", importo=100)


@pytest.mark.parametrize("lista", ["/fatturazione/scadenze/", "/fatturazione/incassi/"])
def test_le_righe_figlie_seguono_l_azienda_del_documento(client, scena, lista):
    """Scadenze e incassi non hanno un'azienda propria: si filtrano su quella della fattura, mai su tutte."""
    a, b = scena[1], scena[2]
    _fattura(a, "A"), _fattura(b, "B")
    client.force_login(_root_di(a))
    pagina = client.get(lista).content.decode()
    assert "CLIENTE-A" in pagina and "CLIENTE-B" not in pagina


@pytest.mark.parametrize("lista", ["/fatturazione/scadenze/", "/fatturazione/incassi/"])
def test_senza_azienda_le_righe_figlie_sono_vuote(client, scena, lista):
    _fattura(scena[1], "A")
    client.force_login(_root_di(None))
    assert "CLIENTE-A" not in client.get(lista).content.decode()


def test_senza_azienda_il_dettaglio_di_una_scadenza_e_404(client, scena):
    _, scadenza, _ = _fattura(scena[1], "A")
    client.force_login(_root_di(None))
    assert client.get(f"/fatturazione/scadenze/{scadenza.pk}/").status_code == 404


def test_invito_al_portale_solo_per_i_contatti_dell_azienda(client, scena, mailoutbox):
    a, b = scena[1], scena[2]
    altrui = Contatto.objects.create(azienda=b, nome="ALTRUI", email="altrui@example.com")
    client.force_login(_root_di(a))
    assert client.post(f"/assistenza/contatto/{altrui.pk}/invita/").status_code == 404
    assert not mailoutbox


def test_compito_di_sviluppo_solo_dai_ticket_dell_azienda(client, scena):
    from helpdesk.models import FaseTicket, Ticket
    from progetti.models import Compito
    a, b = scena[1], scena[2]
    altrui = Ticket.objects.create(azienda=b, oggetto="ALTRUI", fase=FaseTicket.objects.create(nome="Nuovo"))
    client.force_login(_root_di(a))
    assert client.post(f"/assistenza/ticket/{altrui.pk}/compito/").status_code == 404
    assert not Compito.objects.exists()


def test_xml_della_trasmissione_solo_dell_azienda(client, scena):
    from sdi.models import Trasmissione
    a, b = scena[1], scena[2]
    fattura, _, _ = _fattura(b, "B")
    trasmissione = Trasmissione.objects.create(azienda=b, fattura=fattura)
    for azienda in (a, None):
        User.objects.filter(username="root").delete()
        client.force_login(_root_di(azienda))
        assert client.get(f"/sdi/trasmissione/{trasmissione.pk}/xml/").status_code == 404


def test_collaudo_solo_dell_azienda(client, scena):
    from progetti.models import Progetto
    from qualita.models import Collaudo
    a, b = scena[1], scena[2]
    progetto = Progetto.objects.create(azienda=b, nome="ALTRUI")
    collaudo = Collaudo.objects.create(azienda=b, progetto=progetto, nome="ALTRUI")
    client.force_login(_root_di(a))
    assert client.get(f"/qualita/collaudi/{collaudo.pk}/esegui/").status_code == 404


def test_pagine_condivise_solo_nell_azienda_del_proprietario(client, scena):
    from grafici.models import Pagina
    a, b = scena[1], scena[2]
    collega = User.objects.create_user("collega", "c@example.com", "pass12345!")
    collega.profilo.aziende.set([a])
    esterno = User.objects.create_user("esterno", "e@example.com", "pass12345!")
    esterno.profilo.aziende.set([b])
    nostra = Pagina.objects.create(utente=collega, titolo="NOSTRA", condivisa=True)
    altrui = Pagina.objects.create(utente=esterno, titolo="ALTRUI", condivisa=True)
    u = scena[0]
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="grafici"))
    client.force_login(u)
    elenco = client.get("/grafici/").content.decode()
    assert "NOSTRA" in elenco and "ALTRUI" not in elenco
    assert client.get(f"/grafici/pagina/{nostra.pk}/").status_code == 200
    assert client.get(f"/grafici/pagina/{altrui.pk}/").status_code == 404


def test_i_dati_fiscali_solo_delle_aziende_dell_utente(client, scena):
    from fatturazione.models import DatiFiscali
    u, a, b = scena
    u.user_permissions.add(Permission.objects.get(codename="view_datifiscali"))
    DatiFiscali.objects.create(azienda=a, iban="IT00NOSTRO")
    altrui = DatiFiscali.objects.create(azienda=b, iban="IT00ALTRUI")
    client.force_login(User.objects.get(pk=u.pk))
    pagina = client.get("/fatturazione/dati/").content.decode()
    assert "IT00NOSTRO" in pagina and "IT00ALTRUI" not in pagina
    assert client.get(f"/fatturazione/dati/{altrui.pk}/").status_code == 404
