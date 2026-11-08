"""PLT-07: catene di approvazione generiche sui bottoni dei documenti (pagina, API, assistente): soglia, passi per
ruolo o persona, deleghe, rifiuto, nuovo giro se il valore sale, storico e promemoria."""
import datetime
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth.models import Permission, User
from django.utils import timezone

from core import approvazioni, chatter
from core.models import (Azienda, CatenaApprovazione, Delega, PassoApprovazione, RichiestaApprovazione, Ruolo, TokenApi)

pytestmark = pytest.mark.skipif(not apps.is_installed("vendite"), reason="serve vendite")


def _utente(nome, az, ruolo=None):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x")
    u.profilo.aziende.set([az])
    u.profilo.azienda_predefinita = az
    u.profilo.ruolo = ruolo
    u.profilo.save()
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="vendite"))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def s(db):
    from pathlib import Path

    from django.core.management import call_command

    import fiscale
    import prodotti
    from contatti.models import Contatto
    from prodotti.models import Prodotto
    from vendite.models import OrdineVendita, RigaVendita
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    az = Azienda.objects.get(pk=1)
    direzione = Ruolo.objects.create(nome="Direzione")
    capo, vice, anna = _utente("capo", az, direzione), _utente("vice", az), _utente("anna", az)
    cliente = Contatto.objects.create(azienda=az, nome="Rossi Srl", cliente=True, partita_iva="12345678903")
    prodotto = Prodotto.objects.create(azienda=az, nome="Server", prezzo_vendita=Decimal("2000"))

    def ordine(quantita=1):
        o = OrdineVendita.objects.create(azienda=az, cliente=cliente)
        RigaVendita.objects.create(ordine=o, prodotto=prodotto, quantita=quantita)
        o.ricalcola()
        return OrdineVendita.objects.get(pk=o.pk)
    catena = CatenaApprovazione.objects.create(nome="Preventivi importanti", vista="vendite.ordini", bottone="conferma",
                                               campo="totale", soglia=Decimal("1000"))
    PassoApprovazione.objects.create(catena=catena, ordine=1, ruolo=direzione, giorni=2)
    return {"az": az, "capo": capo, "vice": vice, "anna": anna, "ordine": ordine, "catena": catena}


def _conferma(client, o):
    return client.post(f"/vendite/ordini/{o.pk}/bottone/conferma/", follow=True)


def test_blocca_avvisa_approva_e_poi_passa(client, s):
    o = s["ordine"]()
    client.force_login(s["anna"])
    r = _conferma(client, o)
    o.refresh_from_db()
    assert o.stato != "confermato" and "serve l&#x27;approvazione" in r.content.decode().lower() or "serve l'approvazione" in r.content.decode().lower()
    rich = RichiestaApprovazione.objects.get()
    assert rich.stato == "attesa" and rich.valore == o.totale and rich.richiesta_da == s["anna"]
    assert "@capo" in chatter.messaggi_di(o).first().corpo
    assert "aspetta ancora" in _conferma(client, o).content.decode()                 # di nuovo: ancora in attesa
    client.force_login(s["capo"])
    assert o.__str__() in client.get("/approvazioni/").content.decode()
    pagina = client.get(f"/vendite/ordini/{o.pk}/").content.decode()
    assert "Approvazioni" in pagina and "decidi" in pagina
    client.post(f"/approvazioni/{rich.pk}/decidi/", {"esito": "approva", "nota": "ok"})
    assert RichiestaApprovazione.objects.get().stato == "approvata"
    client.force_login(s["anna"])
    _conferma(client, o)
    o.refresh_from_db()
    assert o.stato == "confermato"


def test_sotto_soglia_niente_approvazione(client, s):
    from vendite.models import RigaVendita
    o = s["ordine"]()
    riga = RigaVendita.objects.get(ordine=o)
    riga.prezzo = Decimal("100")
    riga.save()
    o.ricalcola()
    client.force_login(s["anna"])
    _conferma(client, o)
    o.refresh_from_db()
    assert o.stato == "confermato" and not RichiestaApprovazione.objects.exists()


def test_chi_chiede_non_approva_e_rifiuto(client, s):
    o = s["ordine"]()
    client.force_login(s["capo"])                         # il capo stesso chiede: non può approvarsi
    _conferma(client, o)
    rich = RichiestaApprovazione.objects.get()
    assert not approvazioni.puo_decidere(rich, s["capo"])[0]
    assert client.post(f"/approvazioni/{rich.pk}/decidi/", {"esito": "approva"}).status_code == 403
    rich.richiesta_da = s["anna"]
    rich.save()
    approvazioni.decidi(rich, s["capo"], False, "Sconto troppo alto")
    client.force_login(s["anna"])
    assert "rifiutata: Sconto troppo alto" in _conferma(client, o).content.decode()


def test_delega(client, s):
    o = s["ordine"]()
    client.force_login(s["anna"])
    _conferma(client, o)
    rich = RichiestaApprovazione.objects.get()
    assert not approvazioni.puo_decidere(rich, s["vice"])[0]
    Delega.objects.create(da=s["capo"], a=s["vice"], dal=timezone.localdate(), al=timezone.localdate() + datetime.timedelta(days=7))
    assert approvazioni.puo_decidere(rich, s["vice"]) == (True, s["capo"])
    approvazioni.decidi(rich, s["vice"], True)
    assert rich.decisioni.get().per_conto_di == s["capo"]


def test_se_il_valore_sale_serve_un_altra_approvazione(client, s):
    from vendite.models import RigaVendita
    o = s["ordine"]()
    client.force_login(s["anna"])
    _conferma(client, o)
    approvazioni.decidi(RichiestaApprovazione.objects.get(), s["capo"], True)
    riga = RigaVendita.objects.get(ordine=o)
    riga.quantita = 3
    riga.save()
    o.ricalcola()
    _conferma(client, o)
    o.refresh_from_db()
    assert o.stato != "confermato" and RichiestaApprovazione.objects.filter(stato="attesa").count() == 1


def test_anche_dall_api(client, s):
    o = s["ordine"]()
    client.logout()
    _, chiaro = TokenApi.genera(s["anna"], "t")
    r = client.post(f"/api/v1/vendite/ordini/{o.pk}/azioni/conferma/", HTTP_AUTHORIZATION=f"Bearer {chiaro}")
    assert "serve l'approvazione" in r.json()["esito"] and r.json()["dati"]["stato"] != "confermato"


def test_promemoria_dei_passi_scaduti(client, s):
    o = s["ordine"]()
    client.force_login(s["anna"])
    _conferma(client, o)
    RichiestaApprovazione.objects.update(scadenza=timezone.now() - datetime.timedelta(hours=1))
    assert approvazioni.promemoria() == 1 and "Promemoria" in chatter.messaggi_di(o).first().corpo


def test_catena_sbagliata_rifiutata(client, s):
    admin = User.objects.create_superuser("root", "r@example.com", "x")
    client.force_login(admin)
    client.post("/core/catene_approvazione/nuovo/", {"nome": "X", "vista": "vendite.ordini", "bottone": "inesistente", "soglia": "0",
                                                    "attiva": "on", "passi0-TOTAL_FORMS": "0", "passi0-INITIAL_FORMS": "0"})
    assert CatenaApprovazione.objects.count() == 1
