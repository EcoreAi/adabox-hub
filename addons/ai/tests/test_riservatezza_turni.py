"""Chat riservate nel ciclo della risposta: dopo una lettura riservata solo modelli locali (piano 2026-11-18)."""
import pytest
from django.contrib.auth.models import User

from ai import motore, riservatezza
from ai.gateway import finto
from ai.models import AnelloCatena, Conversazione, Modello, Profilo, Provider, Turno
from core import parametri
from core.models import Azienda

LETTURA = [("strumento", "aggrega_record", {"vista": "core.aziende"})]


@pytest.fixture
def s(db, monkeypatch):
    from ai.motore import titoli
    monkeypatch.setattr(titoli, "genera", lambda *a, **k: None)       # i titoli hanno il loro test (Task 4)
    cloud_p = Provider.objects.create(nome="Cloud finto", tipo="finto", locale=False)
    locale_p = Provider.objects.create(nome="Locale finto", tipo="finto", locale=True)
    cloud = Modello.objects.create(provider=cloud_p, id_api="finto-cloud", etichetta="Cloud", sceglibile=True)
    locale = Modello.objects.create(provider=locale_p, id_api="finto-locale", etichetta="Locale")
    profilo = Profilo.objects.create(nome="Chat", compito="chat")
    AnelloCatena.objects.create(profilo=profilo, modello=cloud, ordine=1)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    azienda = Azienda.objects.get(pk=1)
    parametri.scrivi("ai.app_riservate", "core", azienda)
    return {"cloud": cloud, "locale": locale, "profilo": profilo, "capo": capo, "azienda": azienda}


def _turno(s, conversazione, copione):
    with finto.con_copione(copione) as chiamate:
        turno = motore.avvia(conversazione, "Quante aziende ci sono?", s["capo"], s["azienda"], sincrono=True)
    turno.refresh_from_db()
    conversazione.refresh_from_db()
    return turno, [c["modello"] for c in chiamate]


def test_dopo_una_lettura_riservata_risponde_il_locale(s):
    c = Conversazione.objects.create(utente=s["capo"])
    turno, modelli = _turno(s, c, [LETTURA, ["Sono una."]])
    assert modelli == ["finto-cloud", "finto-locale"]
    assert c.riservata and c.riservata_motivo == "app «core»"
    assert turno.stato == Turno.COMPLETATO


def test_senza_locale_si_ferma_senza_inviare(s):
    Provider.objects.filter(locale=True).update(attivo=False)
    c = Conversazione.objects.create(utente=s["capo"])
    turno, modelli = _turno(s, c, [LETTURA, ["Non devo arrivare qui."]])
    assert modelli == ["finto-cloud"]                     # il risultato riservato non è uscito
    assert turno.stato == Turno.ERRORE
    assert riservatezza.MESSAGGIO_SENZA_LOCALE in turno.testo


def test_locale_fuori_dalla_catena(s):
    """Il locale non è nella catena del profilo ma è attivo nell'istanza: si usa quello (Review Focus 2)."""
    c = Conversazione.objects.create(utente=s["capo"])
    _, modelli = _turno(s, c, [LETTURA, ["Una."]])
    assert modelli[-1] == "finto-locale"


def test_chat_riservata_ignora_il_modello_scelto(s, monkeypatch):
    from ai import funzioni
    monkeypatch.setattr(funzioni, "attiva", lambda nome: True)
    c = Conversazione.objects.create(utente=s["capo"], modello=s["cloud"], riservata=True, riservata_motivo="x")
    _, modelli = _turno(s, c, [["Rispondo io."]])
    assert modelli == ["finto-locale"]


def test_risultato_in_errore_non_rende_riservata(s):
    c = Conversazione.objects.create(utente=s["capo"])
    _, modelli = _turno(s, c, [[("strumento", "aggrega_record", {"vista": "core.inesistente"})], ["Non trovo."]])
    assert not c.riservata and modelli == ["finto-cloud", "finto-cloud"]
