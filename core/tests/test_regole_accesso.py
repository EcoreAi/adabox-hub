"""PLT-03: regole sulle righe e permessi per campo per ruolo, dichiarati dall'interfaccia e applicati a lista,
dettaglio, form, export, API e assistente. Il superuser non ha limiti."""
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command

from core.models import Azienda, PermessoCampo, RegolaRiga, Ruolo, TokenApi


@pytest.fixture
def s(db, superuser):
    import crm
    from crm.models import Opportunita
    cache.clear()
    call_command("loaddata", str(Path(crm.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    az = Azienda.objects.get(pk=1)
    commerciale = Ruolo.objects.create(nome="Commerciale", livello_base="lavoro")
    persone = {}
    for nome in ("anna", "bruno"):
        u = User.objects.create_user(nome, f"{nome}@example.com", "x")
        u.profilo.aziende.set([az])
        u.profilo.azienda_predefinita = az
        u.profilo.ruolo = commerciale
        u.profilo.save()
        from django.contrib.auth.models import Permission
        u.user_permissions.add(*Permission.objects.filter(content_type__app_label="crm",
                                                          codename__in=["view_opportunita", "change_opportunita", "add_opportunita",
                                                                        "view_fasecrm"]))
        persone[nome] = User.objects.get(pk=u.pk)
    sua = Opportunita.objects.create(azienda=az, titolo="Di Anna", commerciale=persone["anna"], valore_atteso=Decimal("5000"), probabilita=30)
    altra = Opportunita.objects.create(azienda=az, titolo="Di Bruno", commerciale=persone["bruno"], valore_atteso=Decimal("9000"))
    RegolaRiga.objects.create(vista="crm.opportunita", ruolo=commerciale, campo="commerciale", operatore="utente")
    PermessoCampo.objects.create(vista="crm.opportunita", campo="valore_atteso", ruolo=commerciale, livello="nascosto")
    PermessoCampo.objects.create(vista="crm.opportunita", campo="probabilita", ruolo=commerciale, livello="lettura")
    return {"az": az, "anna": persone["anna"], "sua": sua, "altra": altra, "capo": superuser}


def test_lista_dettaglio_e_form(client, s):
    client.force_login(s["anna"])
    lista = client.get("/crm/opportunita/").content.decode()
    assert "Di Anna" in lista and "Di Bruno" not in lista and "Valore atteso" not in lista
    assert client.get(f"/crm/opportunita/{s['altra'].pk}/").status_code == 404            # la riga non si vede
    dettaglio = client.get(f"/crm/opportunita/{s['sua'].pk}/").content.decode()
    assert "5000" not in dettaglio and "5.000" not in dettaglio
    form = client.get(f"/crm/opportunita/{s['sua'].pk}/modifica/").content.decode()
    assert 'name="valore_atteso"' not in form and "in sola lettura per il tuo ruolo" in form
    from crm.models import Opportunita
    o = Opportunita.objects.get(pk=s["sua"].pk)
    dati = {"titolo": "Di Anna 2", "fase": o.fase_id, "stato": o.stato, "probabilita": 99, "priorita": 0, "valore_atteso": 1,
            "commerciale": s["anna"].pk}
    client.post(f"/crm/opportunita/{o.pk}/modifica/", dati)
    o.refresh_from_db()
    assert o.titolo == "Di Anna 2" and o.probabilita == 30 and o.valore_atteso == Decimal("5000")   # bloccati e nascosti restano


def test_export_api_e_assistente(client, s):
    client.force_login(s["anna"])
    csv = client.get("/crm/opportunita/esporta/?formato=csv").content.decode("utf-8-sig")
    assert "Di Anna" in csv and "Di Bruno" not in csv and "valore" not in csv.splitlines()[0].lower()
    client.logout()
    _, chiaro = TokenApi.genera(s["anna"], "t")
    r = client.get("/api/v1/crm/opportunita/", HTTP_AUTHORIZATION=f"Bearer {chiaro}").json()
    assert r["count"] == 1 and "valore_atteso" not in r["results"][0]
    from ai.strumenti import Contesto
    from ai.strumenti.viste import aggrega_record, cerca_record, leggi_record
    ctx = Contesto(utente=s["anna"], azienda=s["az"])
    trovati = cerca_record(ctx, "crm.opportunita", campi=None)
    assert trovati["totale"] == 1 and all("valore_atteso" not in r for r in trovati["risultati"])
    assert "valore_atteso" not in leggi_record(ctx, "crm.opportunita", s["sua"].pk)
    with pytest.raises(Exception, match="non è disponibile per il tuo ruolo"):
        aggrega_record(ctx, "crm.opportunita", misura="sum:valore_atteso")


def test_il_superuser_vede_tutto(client, s):
    client.force_login(s["capo"])
    lista = client.get("/crm/opportunita/").content.decode()
    assert "Di Anna" in lista and "Di Bruno" in lista and "Valore atteso" in lista


def test_regole_sbagliate_rifiutate(client, s):
    client.force_login(s["capo"])
    ruolo = Ruolo.objects.get(nome="Commerciale")
    client.post("/core/regole_righe/nuovo/", {"vista": "crm.opportunita", "ruolo": ruolo.pk, "campo": "titolo",
                                              "operatore": "utente", "attiva": "on"})
    client.post("/core/regole_righe/nuovo/", {"vista": "crm.opportunita", "ruolo": ruolo.pk, "campo": "inesistente",
                                              "operatore": "uguale", "valore": "x", "attiva": "on"})
    assert RegolaRiga.objects.count() == 1
    client.post("/core/permessi_campo/nuovo/", {"vista": "crm.opportunita", "campo": "titolo", "ruolo": ruolo.pk, "livello": "nascosto"})
    assert not PermessoCampo.objects.filter(campo="titolo").exists()                     # obbligatorio: niente nascosto
    assert "Regole sulle righe" in client.get("/utenti/ruoli/").content.decode()


def test_regola_rotta_nasconde_tutto(client, s):
    RegolaRiga.objects.filter(vista="crm.opportunita").update(campo="sparito")
    client.force_login(s["anna"])
    assert "Di Anna" not in client.get("/crm/opportunita/").content.decode()
