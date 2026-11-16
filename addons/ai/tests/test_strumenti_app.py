import datetime

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

from ai import strumenti
from ai.models import Conversazione
from ai.strumenti import app, registro
from core.models import Azienda
from core.registry import modules
from core.registry.manifest import Manifest


def test_strumenti_dichiarati_nel_manifest_con_l_app(db, monkeypatch, tmp_path):
    finto = Manifest(slug="prova", percorso=tmp_path, name="Prova", version="1.0.0", min_core="1.0",
                     ai="prova_ai_modulo")
    rotto = Manifest(slug="rotta", percorso=tmp_path, name="Rotta", version="1.0.0", min_core="1.0",
                     ai="rotta_inesistente.ai")
    (tmp_path / "prova_ai_modulo.py").write_text(
        "from ai.strumenti import Strumento, registra\n"
        "registra(Strumento('prova_saluta', 'Saluta', {'type': 'object', 'properties': {}}, lambda c: 'ciao'))\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(modules, "manifests_attivi", lambda: {"prova": finto, "rotta": rotto})
    monkeypatch.setattr(app, "_caricati", set())
    try:
        utente = User.objects.create_user("u")
        nomi = [s.nome for s in strumenti.disponibili(utente)]
        assert "prova_saluta" in nomi and registro._registro["prova_saluta"].app == "prova"
        assert "prova_saluta" not in [s.nome for s in strumenti.disponibili(utente, ambito="vendite")]
        assert "prova_saluta" in [s.nome for s in strumenti.disponibili(utente, ambito="prova")]
    finally:
        registro._registro.pop("prova_saluta", None)


@pytest.mark.skipif("calendario" not in settings.ADDONS_ATTIVI, reason="serve l'app calendario")
def test_agenda_del_calendario(db):
    from calendario.models import Evento
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    azienda = Azienda.objects.get(pk=1)
    oggi = timezone.localtime().replace(hour=10, minute=0, second=0, microsecond=0)
    Evento.objects.create(azienda=azienda, titolo="Riunione Rossi", inizio=oggi + datetime.timedelta(days=1),
                          fine=oggi + datetime.timedelta(days=1, hours=1), organizzatore=capo)
    Evento.objects.create(azienda=azienda, titolo="Fiera", inizio=oggi - datetime.timedelta(days=2),
                          fine=oggi + datetime.timedelta(days=2), organizzatore=capo)
    Evento.objects.create(azienda=azienda, titolo="Lontano", inizio=oggi + datetime.timedelta(days=30),
                          fine=oggi + datetime.timedelta(days=30, hours=1), organizzatore=capo)
    contesto = strumenti.Contesto(utente=capo, azienda=azienda, conversazione=Conversazione.objects.create(utente=capo))
    ammessi = {s.nome: s for s in strumenti.disponibili(capo)}
    assert ammessi["calendario_agenda"].app == "calendario"
    r = ammessi["calendario_agenda"].funzione(contesto)
    assert [e["titolo"] for e in r["eventi"]] == ["Fiera", "Riunione Rossi"] and r["eventi"][1]["url"]
    assert [e["stato"] for e in r["eventi"]] == ["in corso", "da venire"] and r["conteggio"]["passato"] == 0
    # uno già finito: lo stato lo calcola lo strumento, non il modello
    adesso = timezone.now()
    Evento.objects.create(azienda=azienda, titolo="Stamattina", inizio=adesso - datetime.timedelta(minutes=40),
                          fine=adesso - datetime.timedelta(minutes=10), organizzatore=capo)
    r = ammessi["calendario_agenda"].funzione(contesto, da=timezone.localtime(adesso - datetime.timedelta(minutes=40)).date().isoformat())
    passato = next(e for e in r["eventi"] if e["titolo"] == "Stamattina")
    assert passato["stato"] == "passato" and r["conteggio"]["passato"] == 1 and r["adesso"]
    assert "1 già passato" in r["sintesi"] and r["sintesi"].endswith(".")
    from calendario.ai import sintesi
    assert sintesi({"passato": 6, "in corso": 0, "da venire": 4}) == "10 appuntamenti nel periodo: 6 già passati, nessuno in corso, 4 da venire."
    assert sintesi({"passato": 0, "in corso": 1, "da venire": 0}) == "1 appuntamento nel periodo: 0 già passati, 1 in corso, 0 da venire."
    assert sintesi({"passato": 0, "in corso": 0, "da venire": 0}) == "Nessun appuntamento nel periodo."
    with pytest.raises(strumenti.ErroreStrumento, match="Periodo non valido"):
        ammessi["calendario_agenda"].funzione(contesto, da="2026-01-01", a="2026-12-31")
    nessuno = User.objects.create_user("nessuno")
    assert "calendario_agenda" not in [s.nome for s in strumenti.disponibili(nessuno)]
