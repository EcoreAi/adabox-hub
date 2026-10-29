import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone

import progetti
from core.models import Azienda, Messaggio
from progetti.models import Compito, FaseCompito, Milestone, Progetto, Rilascio, Sprint, TipoCompito
from progetti.segnali import rilascio_pubblicato

CARTELLA = Path(progetti.__file__).parent


@pytest.fixture
def scena(db):
    call_command("loaddata", str(CARTELLA / "data" / "fasi.json"), str(CARTELLA / "data" / "tipi.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    progetto = Progetto.objects.create(azienda=azienda, nome="Gestionale", responsabile=capo)
    return {"azienda": azienda, "capo": capo, "progetto": progetto,
            "fatto": FaseCompito.objects.get(chiusa=True), "da_fare": FaseCompito.objects.order_by("ordine").first(),
            "bug": TipoCompito.objects.get(nome="Bug"), "funz": TipoCompito.objects.get(nome="Funzionalità")}


def _compito(scena, titolo, **campi):
    return Compito.objects.create(azienda=scena["azienda"], progetto=scena["progetto"], titolo=titolo, **campi)


def _campi_form(compito, **altro):
    dati = {"titolo": compito.titolo, "progetto": compito.progetto_id, "fase": compito.fase_id,
            "priorita": compito.priorita, "ore_previste": "0"}
    dati.update(altro)
    return dati


def test_completato_il_segue_la_fase_anche_dal_kanban(client, scena):
    c = _compito(scena, "Login")
    assert c.completato_il is None
    client.force_login(scena["capo"])
    client.post(f"/progetti/compiti/{c.pk}/sposta/", {"valore": scena["fatto"].pk}, HTTP_HX_REQUEST="true")
    c.refresh_from_db()
    assert c.fase == scena["fatto"] and c.completato_il is not None
    client.post(f"/progetti/compiti/{c.pk}/sposta/", {"valore": scena["da_fare"].pk}, HTTP_HX_REQUEST="true")
    c.refresh_from_db()
    assert c.completato_il is None


def test_dipendenze_bloccano_la_chiusura(client, scena):
    api = _compito(scena, "API ordini")
    ui = _compito(scena, "Schermata ordini")
    client.force_login(scena["capo"])
    r = client.post(f"/progetti/compiti/{ui.pk}/modifica/", _campi_form(ui, bloccato_da=[api.pk]))
    assert r.status_code == 302 and list(ui.bloccato_da.all()) == [api]
    r = client.post(f"/progetti/compiti/{api.pk}/modifica/", _campi_form(api, bloccato_da=[ui.pk]))
    assert "circolare" in r.content.decode()                                             # niente cicli
    r = client.post(f"/progetti/compiti/{ui.pk}/sposta/", {"valore": scena["fatto"].pk}, HTTP_HX_REQUEST="true")
    assert r.status_code == 409 and "API ordini" in r.content.decode()                   # dal kanban
    r = client.post(f"/progetti/compiti/{ui.pk}/modifica/", _campi_form(ui, fase=scena["fatto"].pk,
                                                                         bloccato_da=[api.pk]))
    assert "Prima vanno completati" in r.content.decode()                               # dal form
    client.post(f"/progetti/compiti/{ui.pk}/bottone/completa/", follow=True)
    ui.refresh_from_db()
    assert not ui.fase.chiusa                                                            # dal bottone
    client.post(f"/progetti/compiti/{api.pk}/bottone/completa/")
    client.post(f"/progetti/compiti/{ui.pk}/bottone/completa/")
    ui.refresh_from_db()
    assert ui.fase.chiusa


def test_pianificazione_dello_stesso_progetto(client, scena):
    altro = Progetto.objects.create(azienda=scena["azienda"], nome="Altro")
    sprint_altrui = Sprint.objects.create(azienda=scena["azienda"], progetto=altro, nome="S1",
                                          inizio=datetime.date(2026, 11, 2), fine=datetime.date(2026, 11, 13))
    c = _compito(scena, "Report")
    client.force_login(scena["capo"])
    r = client.post(f"/progetti/compiti/{c.pk}/modifica/", _campi_form(c, sprint=sprint_altrui.pk))
    assert "stesso progetto" in r.content.decode()


def test_sprint_burndown_e_chiusura(client, scena):
    p = scena["progetto"]
    s1 = Sprint.objects.create(azienda=scena["azienda"], progetto=p, nome="Sprint 1",
                               inizio=datetime.date(2026, 11, 2), fine=datetime.date(2026, 11, 6))
    s2 = Sprint.objects.create(azienda=scena["azienda"], progetto=p, nome="Sprint 2",
                               inizio=datetime.date(2026, 11, 9), fine=datetime.date(2026, 11, 13))
    a = _compito(scena, "A", sprint=s1, punti=5)
    b = _compito(scena, "B", sprint=s1, punti=3)
    _compito(scena, "C", sprint=s1)                                                     # senza stima: 1 punto
    a.fase = scena["fatto"]
    a.save()
    Compito.objects.filter(pk=a.pk).update(
        completato_il=timezone.make_aware(datetime.datetime(2026, 11, 4, 10)))
    assert s1.punti() == (9, 5)
    reale, ideale = s1.burndown(oggi=datetime.date(2026, 11, 5))
    assert [v for _, v in reale] == [9, 9, 4, 4] and ideale[0][1] == 9 and ideale[-1][1] == 0
    client.force_login(scena["capo"])
    html = client.get(f"/progetti/sprint/{s1.pk}/").content.decode()
    assert "Burndown di Sprint 1" in html and "Avvia lo sprint" in html
    client.post(f"/progetti/sprint/{s1.pk}/bottone/avvia/")
    client.post(f"/progetti/sprint/{s1.pk}/bottone/chiudi/")
    s1.refresh_from_db()
    b.refresh_from_db()
    assert s1.stato == Sprint.CHIUSO and b.sprint == s2                                  # aperti allo sprint dopo
    assert Compito.objects.get(pk=a.pk).sprint == s1


def test_rilascio_con_note_generate_e_segnale(client, scena):
    r = Rilascio.objects.create(azienda=scena["azienda"], progetto=scena["progetto"], versione="2.4.0")
    _compito(scena, "Export Excel", tipo=scena["funz"], rilascio=r, fase=scena["fatto"])
    _compito(scena, "Totale sbagliato", tipo=scena["bug"], rilascio=r, fase=scena["fatto"])
    _compito(scena, "Ancora da fare", rilascio=r)
    ricevuti = []
    rilascio_pubblicato.connect(lambda sender, rilascio, **_: ricevuti.append(rilascio), weak=False,
                                dispatch_uid="test.rilascio")
    try:
        client.force_login(scena["capo"])
        client.post(f"/progetti/rilasci/{r.pk}/bottone/rilascia/")
    finally:
        rilascio_pubblicato.disconnect(dispatch_uid="test.rilascio")
    r.refresh_from_db()
    assert r.stato == Rilascio.RILASCIATO and r.rilasciato_il and ricevuti == [r]
    assert r.note == "Funzionalità\n- Export Excel\n\nBug\n- Totale sbagliato"
    assert not r.rilascia()                                                              # una volta sola
    assert "Rilascia" not in client.get(f"/progetti/rilasci/{r.pk}/").content.decode().split("ui-card-title")[0]


def test_milestone_e_scheda_del_progetto(client, scena):
    m = Milestone.objects.create(azienda=scena["azienda"], progetto=scena["progetto"], nome="Beta")
    _compito(scena, "Uno", milestone=m, fase=scena["fatto"])
    _compito(scena, "Due", milestone=m)
    assert m.avanzamento() == (2, 1, 50) and not m.raggiunta()
    client.force_login(scena["capo"])
    html = client.get(f"/progetti/progetti/{scena['progetto'].pk}/").content.decode()
    assert "Pianificazione" in html and "Beta" in html


@pytest.mark.skipif(not __import__("django.apps", fromlist=["apps"]).apps.is_installed("timesheet"),
                    reason="serve il timesheet")
def test_avvisi_di_budget_dalle_ore(scena):
    from timesheet.models import RigaOre
    p = scena["progetto"]
    p.budget_ore = Decimal("10")
    p.save()
    riga = RigaOre.objects.create(azienda=scena["azienda"], utente=scena["capo"], progetto=p, ore=Decimal("8"))
    note = Messaggio.objects.filter(object_id=p.pk, tipo=Messaggio.NOTA, corpo__startswith="Budget")
    assert p.budget() == (Decimal("10"), Decimal("8"), 80) and note.count() == 1
    RigaOre.objects.create(azienda=scena["azienda"], utente=scena["capo"], progetto=p, ore=Decimal("1"))
    assert note.count() == 1                                                             # nessun doppione
    riga.ore = Decimal("9.5")
    riga.save()
    assert note.count() == 2 and "superato" in note.order_by("pk").last().corpo
