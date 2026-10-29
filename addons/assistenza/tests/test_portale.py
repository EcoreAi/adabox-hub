import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from assistenza.models import AccessoPortale, DatiTicket, Supporto
from assistenza.portale import invita
from contatti.models import Contatto
from core import allegati, chatter
from core.models import Azienda
from helpdesk.models import FaseTicket, Team, Ticket
from progetti.models import Progetto


@pytest.fixture
def scena(db, settings, tmp_path):
    import helpdesk
    call_command("loaddata", str(Path(helpdesk.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    azienda = Azienda.objects.get(pk=1)
    sara = User.objects.create_user("sara", "sara@example.com", "x")
    team = Team.objects.create(nome="Sviluppo")
    team.membri.add(sara)
    rossi = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True)
    anna = Contatto.objects.create(azienda=azienda, nome="Anna Rossi", tipo="persona", societa=rossi,
                                   email="anna@rossi.it")
    marco = Contatto.objects.create(azienda=azienda, nome="Marco Rossi", tipo="persona", societa=rossi,
                                    email="marco@rossi.it")
    bianchi = Contatto.objects.create(azienda=azienda, nome="Bianchi Spa", cliente=True, email="info@bianchi.it")
    progetto = Progetto.objects.create(azienda=azienda, nome="Gestionale Rossi", cliente=rossi)
    Supporto.objects.create(azienda=azienda, progetto=progetto, team=team, responsabile=sara)
    return {"azienda": azienda, "sara": sara, "rossi": rossi, "anna": anna, "marco": marco, "bianchi": bianchi,
            "progetto": progetto}


def _entra(client, scena, chi="anna"):
    accesso = invita(scena[chi], scena["sara"])
    client.force_login(accesso.utente)
    return accesso


def test_invito_con_il_link_per_la_password(client, scena):
    client.force_login(User.objects.create_superuser("root", "r@example.com", "x"))
    html = client.get(f"/contatti/contatti/{scena['anna'].pk}/").content.decode()
    assert "Invita al portale" in html
    client.post(f"/assistenza/contatto/{scena['anna'].pk}/invita/")
    accesso = AccessoPortale.objects.get(contatto=scena["anna"])
    assert accesso.utente.username == "anna@rossi.it" and accesso.utente.profilo.esterno
    link = re.search(r"https?://\S+/accounts/reset/\S+/", mail.outbox[-1].body).group(0)
    client.logout()
    r = client.get(urlparse(link).path, follow=True)
    assert "Scegli la password" in r.content.decode()
    client.force_login(User.objects.get(username="root"))
    client.post(f"/assistenza/contatto/{scena['anna'].pk}/revoca/")
    assert not User.objects.get(pk=accesso.utente.pk).is_active


def test_il_cliente_vede_solo_la_sua_azienda(client, scena):
    del_collega = Ticket.objects.create(azienda=scena["azienda"], oggetto="Del collega", contatto=scena["marco"])
    altrui = Ticket.objects.create(azienda=scena["azienda"], oggetto="Di Bianchi", contatto=scena["bianchi"])
    _entra(client, scena)
    html = client.get("/assistenza/portale/").content.decode()
    assert "Del collega" in html and "Di Bianchi" not in html
    assert client.get(f"/assistenza/portale/ticket/{del_collega.pk}/").status_code == 200
    assert client.get(f"/assistenza/portale/ticket/{altrui.pk}/").status_code == 404
    assert client.get("/dashboard/").status_code == 302                              # le pagine interne no
    progetti = client.get("/assistenza/portale/progetti/").content.decode()
    assert "Gestionale Rossi" in progetti


def test_note_interne_mai_visibili_e_risposta(client, scena):
    ticket = Ticket.objects.create(azienda=scena["azienda"], oggetto="Errore stampa", contatto=scena["anna"])
    chatter.scrivi(ticket, scena["sara"], "NOTA SEGRETA: il cliente non paga", tipo="nota")
    chatter.scrivi(ticket, scena["sara"], "Ciao Anna, ci guardiamo.")
    interno = allegati.salva(ticket, SimpleUploadedFile("log-interno.txt", b"x"), scena["sara"])
    accesso = _entra(client, scena)
    html = client.get(f"/assistenza/portale/ticket/{ticket.pk}/").content.decode()
    assert "Ciao Anna" in html and "NOTA SEGRETA" not in html and "log-interno.txt" not in html
    assert client.get(f"/assistenza/portale/ticket/{ticket.pk}/file/{interno.pk}/").status_code == 404
    ticket.fase = FaseTicket.objects.get(chiusa=True)
    ticket.save()
    client.post(f"/assistenza/portale/ticket/{ticket.pk}/", {
        "testo": "Ancora non va", "file": SimpleUploadedFile("schermata.png", b"\x89PNG", "image/png")})
    ticket.refresh_from_db()
    assert not ticket.fase.chiusa                                                     # si riapre
    risposta = chatter.messaggi_di(ticket).filter(autore=accesso.utente).get()
    allegato = risposta.allegati.get()
    assert risposta.corpo == "Ancora non va" and allegato.nome == "schermata.png"
    assert client.get(f"/assistenza/portale/ticket/{ticket.pk}/file/{allegato.pk}/").status_code == 200


def test_nuova_segnalazione_dal_portale(client, scena):
    _entra(client, scena)
    assert "Gestionale Rossi" in client.get("/assistenza/portale/nuovo/").content.decode()
    r = client.post("/assistenza/portale/nuovo/", {"progetto": scena["progetto"].pk, "tipo": "richiesta",
                                                   "oggetto": "Nuovo report vendite", "descrizione": "Per agente"})
    ticket = Ticket.objects.get(oggetto="Nuovo report vendite")
    assert r.status_code == 302 and ticket.contatto == scena["anna"] and ticket.assegnatario == scena["sara"]
    dati = DatiTicket.objects.get(ticket=ticket)
    assert dati.canale == "portale" and dati.tipo == "richiesta" and dati.progetto == scena["progetto"]
    altro = Progetto.objects.create(azienda=scena["azienda"], nome="Di Bianchi", cliente=scena["bianchi"])
    client.post("/assistenza/portale/nuovo/", {"progetto": altro.pk, "oggetto": "Furbo"})
    assert not Ticket.objects.filter(oggetto="Furbo").exists()                      # progetto non suo


def test_interni_fuori_dal_portale(client, scena):
    client.force_login(scena["sara"])
    assert client.get("/assistenza/portale/").status_code == 403
