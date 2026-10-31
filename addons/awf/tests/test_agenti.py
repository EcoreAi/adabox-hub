import pytest
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied

from awf import agenti, operazioni
from awf.models import Agente, OperazioneAmmessa
from core.models import TokenApi


def test_utente_agente_confinato(collegato):
    buyer = User.objects.get(username="awf-buyer")
    assert buyer.is_active and not buyer.has_usable_password() and buyer.email == ""
    assert not buyer.is_staff and not buyer.is_superuser
    assert list(buyer.groups.values_list("name", flat=True)) == [agenti.GRUPPO]
    assert list(buyer.profilo.aziende.values_list("pk", flat=True)) == [1]


def test_gli_agenti_non_entrano_nell_interfaccia(client, collegato):
    r = client.post("/accounts/login/", {"username": "awf-buyer", "password": "qualunque"})
    assert r.status_code == 200 and "_auth_user_id" not in client.session          # password inutilizzabile
    buyer = User.objects.get(username="awf-buyer")
    with pytest.raises(PermissionDenied):                # anche con un backend che lo farebbe entrare
        client.force_login(buyer)
    assert "_auth_user_id" not in client.session
    assert client.get("/awf/stato/").status_code == 302                     # resta anonimo: al login
    buyer.set_password("una-password-messa-a-mano")
    buyer.save()
    r = client.post("/accounts/login/", {"username": "awf-buyer", "password": "una-password-messa-a-mano"})
    assert r.status_code == 403 and "_auth_user_id" not in client.session


def test_niente_token_api_per_gli_agenti(collegato):
    buyer = User.objects.get(username="awf-buyer")
    with pytest.raises(PermissionDenied):
        TokenApi.genera(buyer, "tentativo")
    assert not TokenApi.objects.filter(utente=buyer).exists()


def test_una_persona_non_diventa_agente(collegato):
    User.objects.create_user("awf-intruso", "x@example.com", "pass12345!")
    with pytest.raises(agenti.AgenteSconosciuto):
        agenti.assicura("Intruso")
    assert not Agente.objects.filter(utente__username="awf-intruso").exists()


def test_confina_toglie_gruppi_e_permessi_aggiunti_da_altri(collegato):
    buyer = User.objects.get(username="awf-buyer")
    buyer.groups.add(Group.objects.create(name="Tutti gli utenti attivi"))
    buyer.is_staff = True
    buyer.save()
    agenti.confina(buyer.agente_awf, collegato.azienda)
    buyer.refresh_from_db()
    assert not buyer.is_staff and list(buyer.groups.values_list("name", flat=True)) == [agenti.GRUPPO]


def test_permessi_solo_dalle_operazioni_con_vista(collegato, ammesse):
    perms = {f"{p.content_type.app_label}.{p.codename}" for p in operazioni.permessi_derivati()}
    assert perms == {"todo.view_attivita", "todo.change_attivita", "todo.add_attivita"}
    buyer = User.objects.get(username="awf-buyer")
    assert buyer.has_perm("todo.change_attivita") and not buyer.has_perm("todo.delete_attivita")
    OperazioneAmmessa.objects.filter(strumento="modifica_record").delete()            # il segnale riallinea
    buyer = User.objects.get(username="awf-buyer")
    assert not buyer.has_perm("todo.change_attivita") and buyer.has_perm("todo.add_attivita")


def test_default_solo_letture(db):
    assert operazioni.semina_predefinite() > 0
    esposte = operazioni.esposte()
    assert esposte and all(e.effetto == "read" for e in esposte)
    assert operazioni.semina_predefinite() == 0                                       # una volta sola


def test_agente_uscito_dall_ingaggio(collegato):
    agenti.sincronizza({"agents": [{"name": "Buyer"}]}, collegato.azienda)
    assert not Agente.objects.get(nome="Magazziniere").attivo
    with pytest.raises(agenti.AgenteSconosciuto):
        agenti.risolvi("Magazziniere", collegato.azienda)
    assert agenti.risolvi("agt_buyer", collegato.azienda).nome == "Buyer"
