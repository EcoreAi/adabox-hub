import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.core.management import call_command

import personale
from core.models import Azienda, Messaggio
from personale import calendario_lavoro, flusso, hooks, saldi
from personale.models import Assenza, Dipendente, TipoAssenza

ANNO = 2026


def _utente(nome, *codici):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x")
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="personale",
                                                     codename__in=["view_assenza", "add_assenza", *codici]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def scena(db):
    call_command("loaddata", str(Path(personale.__file__).parent / "data" / "tipi.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    capo_u, mario_u, altro_u = _utente("capo"), _utente("mario"), _utente("altro")
    capo = Dipendente.objects.create(azienda=azienda, nome="Laura", cognome="Ferri", utente=capo_u,
                                     data_assunzione=datetime.date(2020, 1, 1))
    mario = Dipendente.objects.create(azienda=azienda, nome="Mario", cognome="Rossi", utente=mario_u, responsabile=capo,
                                      data_assunzione=datetime.date(2020, 1, 1))
    Dipendente.objects.create(azienda=azienda, nome="Altro", cognome="Collega", utente=altro_u,
                              data_assunzione=datetime.date(2020, 1, 1))
    return {"azienda": azienda, "capo": capo, "mario": mario, "capo_u": capo_u, "mario_u": mario_u, "altro_u": altro_u,
            "ferie": TipoAssenza.objects.get(saldo="ferie"), "permesso": TipoAssenza.objects.get(saldo="permessi"),
            "malattia": TipoAssenza.objects.get(nome="Malattia")}


def test_calendario_lavorativo():
    assert calendario_lavoro.pasqua(2026) == datetime.date(2026, 4, 5)
    assert calendario_lavoro.pasqua(2027) == datetime.date(2027, 3, 28)
    assert datetime.date(2026, 4, 6) in calendario_lavoro.festivita(2026)                     # Pasquetta
    # dal 30/12/2026 (mer) al 7/1/2027 (gio): 30, 31, 4, 5, 7 (1 e 6 gennaio festivi, 2-3 weekend)
    assert calendario_lavoro.giorni_lavorativi(datetime.date(2026, 12, 30), datetime.date(2027, 1, 7)) == 5
    assert calendario_lavoro.giorni_lavorativi(datetime.date(2026, 8, 15), datetime.date(2026, 8, 16)) == 0


def test_validazioni(scena):
    mario, ferie, permesso = scena["mario"], scena["ferie"], scena["permesso"]
    a = Assenza(azienda=scena["azienda"], dipendente=mario, tipo=ferie, dal=datetime.date(2026, 8, 10),
                al=datetime.date(2026, 8, 7))
    with pytest.raises(ValidationError, match="prima dell'inizio"):
        a.full_clean()
    with pytest.raises(ValidationError, match="quante ore"):
        Assenza(azienda=scena["azienda"], dipendente=mario, tipo=permesso, dal=datetime.date(2026, 8, 10),
                al=datetime.date(2026, 8, 10)).full_clean()
    with pytest.raises(ValidationError, match="giorni lavorativi"):
        Assenza(azienda=scena["azienda"], dipendente=mario, tipo=ferie, dal=datetime.date(2026, 8, 15),
                al=datetime.date(2026, 8, 16)).full_clean()
    Assenza.objects.create(azienda=scena["azienda"], dipendente=mario, tipo=ferie, dal=datetime.date(2026, 8, 10),
                           al=datetime.date(2026, 8, 14))
    with pytest.raises(ValidationError, match="già un'assenza"):
        Assenza(azienda=scena["azienda"], dipendente=mario, tipo=ferie, dal=datetime.date(2026, 8, 14),
                al=datetime.date(2026, 8, 18)).full_clean()


def test_saldo(scena):
    mario, ferie, permesso = scena["mario"], scena["ferie"], scena["permesso"]
    Assenza.objects.create(azienda=mario.azienda, dipendente=mario, tipo=ferie, dal=datetime.date(ANNO, 8, 10),
                           al=datetime.date(ANNO, 8, 14), stato="approvata")                    # 5 giorni
    Assenza.objects.create(azienda=mario.azienda, dipendente=mario, tipo=permesso, dal=datetime.date(ANNO, 3, 3),
                           al=datetime.date(ANNO, 3, 3), ore=Decimal(4))                       # da approvare
    Assenza.objects.create(azienda=mario.azienda, dipendente=mario, tipo=ferie, dal=datetime.date(ANNO, 9, 7),
                           al=datetime.date(ANNO, 9, 7), stato="rifiutata")
    s = saldi.saldo(mario, ANNO)
    assert s["ferie"] == {"unita": "giorni", "spettanti": Decimal("26.00"), "godute": Decimal("5.00"),
                          "richieste": Decimal("0.00"), "residue": Decimal("21.00")}
    assert s["permessi"]["richieste"] == Decimal("4.00") and s["permessi"]["residue"] == Decimal("68.00")
    mario.data_assunzione = datetime.date(ANNO, 7, 1)                                            # metà anno
    assert saldi.saldo(mario, ANNO)["ferie"]["spettanti"] == Decimal("13.11")


def test_richiesta_dalla_pagina_e_approvazione(client, scena):
    client.force_login(scena["mario_u"])
    html = client.get("/personale/mie/").content.decode()
    assert "Saldo" in html and "Nuova richiesta" in html
    r = client.post("/personale/mie/", {"tipo": scena["ferie"].pk, "dal": "2026-08-10", "al": "2026-08-14",
                                        "motivo": "Mare"})
    assert r.status_code == 302
    a = Assenza.objects.get()
    assert a.stato == "richiesta" and a.dipendente == scena["mario"] and a.quantita == 5
    assert Messaggio.objects.filter(object_id=a.pk, corpo__contains="Nuova richiesta").exists()
    assert client.post(f"/personale/assenze/{a.pk}/bottone/approva/").status_code == 403      # non si approva da sé
    a.refresh_from_db()
    assert a.stato == "richiesta"
    client.force_login(scena["altro_u"])
    assert client.get(f"/personale/assenze/{a.pk}/").status_code == 404                        # non è sua né del team
    client.force_login(scena["capo_u"])
    html = client.get(f"/personale/assenze/{a.pk}/").content.decode()
    assert "bottone/approva/" in html
    client.post(f"/personale/assenze/{a.pk}/bottone/approva/")
    a.refresh_from_db()
    assert a.stato == "approvata" and a.decisa_da == scena["capo_u"]


def test_rifiuto_annullo_e_permessi(scena):
    mario, capo_u, mario_u, altro_u = scena["mario"], scena["capo_u"], scena["mario_u"], scena["altro_u"]
    a = Assenza.objects.create(azienda=mario.azienda, dipendente=mario, tipo=scena["ferie"],
                               dal=datetime.date(2099, 8, 10), al=datetime.date(2099, 8, 11))
    from django.core.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied):
        flusso.decidi(a, altro_u, True)
    with pytest.raises(PermissionDenied):
        flusso.decidi(a, mario_u, True)                                         # non si approva da sé
    flusso.decidi(a, capo_u, False, "Periodo di chiusura bilancio")
    assert a.stato == "rifiutata" and a.nota_decisione == "Periodo di chiusura bilancio"
    with pytest.raises(ValidationError):
        flusso.decidi(a, capo_u, True)
    b = Assenza.objects.create(azienda=mario.azienda, dipendente=mario, tipo=scena["ferie"],
                               dal=datetime.date(2099, 9, 7), al=datetime.date(2099, 9, 8), stato="approvata")
    flusso.annulla(b, mario_u)
    assert b.stato == "annullata"


def test_pagina_senza_scheda_dipendente(client, db):
    u = _utente("nessuno")
    client.force_login(u)
    assert "non è collegato" in client.get("/personale/mie/").content.decode()


def test_gestore_vede_tutto_e_approva_in_blocco(client, scena):
    hr = _utente("hr", "vedi_tutte_assenze", "change_assenza")
    for d in (datetime.date(2099, 3, 2), datetime.date(2099, 3, 9)):
        Assenza.objects.create(azienda=scena["azienda"], dipendente=scena["mario"], tipo=scena["ferie"], dal=d, al=d)
    client.force_login(hr)
    client.post("/personale/assenze/azione/approva_selezionate/", {"pk": list(Assenza.objects.values_list("pk", flat=True))})
    assert not Assenza.objects.filter(stato="richiesta").exists()


def test_dettaglio_dipendente_e_demo(client, superuser, scena):
    html = client.get(f"/personale/dipendenti/{scena['mario'].pk}/").content.decode()
    assert "Ferie (giorni)" in html
    Dipendente.objects.all().delete()
    from django.contrib.auth.models import Group
    Group.objects.create(name="Personale / Dipendente")
    hooks.post_install(None)
    hooks.demo(None)
    hooks.demo(None)
    assert Dipendente.objects.count() == 5 and Assenza.objects.filter(stato="approvata").exists()


def test_dashboard(rf, scena):
    from personale.dashboard import kpi
    Assenza.objects.create(azienda=scena["azienda"], dipendente=scena["mario"], tipo=scena["ferie"],
                           dal=datetime.date(2099, 3, 2), al=datetime.date(2099, 3, 2))
    richiesta = rf.get("/")
    richiesta.user, richiesta.azienda = scena["capo_u"], scena["azienda"]
    valori = {k["etichetta"]: k["valore"] for k in kpi(richiesta)["kpi"]}
    assert valori["richieste da approvare"] == 1 and valori["tue ferie residue"] == "26"
