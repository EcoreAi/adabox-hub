"""Lo strumento `previsione` di Ada, registrato dal modulo (previsioni/ai.py)."""
import datetime

import pytest
from django.apps import apps
from django.contrib.auth.models import User
from django.utils import timezone

from core import parametri
from core.models import Azienda, Lavoro
from previsioni import motore as motore_previsioni
from previsioni import servizio as servizio_previsioni
from previsioni.tests.test_motore import _finta_risposta

pytestmark = pytest.mark.skipif(not apps.is_installed("ai"), reason="serve l'Assistente AI")

if apps.is_installed("ai"):
    from ai import artifact, motore, strumenti
    from ai.gateway import finto
    from ai.models import AnelloCatena, Artifact, Conversazione, Evento, Modello, Profilo, Provider
    from previsioni import ai as ai_previsioni


@pytest.fixture
def servizi(monkeypatch):
    """Il servizio di previsione finto: le chiamate in ordine, (chiave, percorso, dati)."""
    chiamate = []

    def prevedi(percorso, dati):
        chiamate.append(("previsioni", percorso, dati))
        return _finta_risposta(dati)
    monkeypatch.setattr(servizio_previsioni, "chiama", prevedi)
    return chiamate


@pytest.fixture
def scena(db, client):
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(capo)
    oggi = timezone.localdate().replace(day=15)
    for mesi_fa, quanti in [(8, 2), (7, 3), (6, 3), (5, 4), (4, 4), (3, 5), (2, 5), (1, 6), (0, 9)]:
        mese = motore_previsioni.avanti(oggi.replace(day=1), "mese", -mesi_fa)
        for _ in range(quanti):
            lavoro = Lavoro.objects.create(funzione="prova.lavoro")
            Lavoro.objects.filter(pk=lavoro.pk).update(creato=timezone.make_aware(
                datetime.datetime.combine(mese.replace(day=10), datetime.time(9))))
    return {"capo": capo, "azienda": Azienda.objects.get(pk=1), "client": client,
            "conversazione": Conversazione.objects.create(utente=capo)}


def _contesto(scena):
    return strumenti.Contesto(utente=scena["capo"], azienda=scena["azienda"], conversazione=scena["conversazione"])


def test_strumento_solo_con_il_servizio_configurato(scena):
    nomi = {s.nome for s in strumenti.disponibili(scena["capo"])}
    assert "previsione" not in nomi
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    nomi = {s.nome for s in strumenti.disponibili(scena["capo"])}
    assert "previsione" in nomi
    assert "previsione" in {s.nome for s in strumenti.disponibili(scena["capo"], ambito="todo")}   # anche nella chat di un'app


def test_dal_motore_con_grafico_e_numeri_verificati(scena, servizi):
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto")
    AnelloCatena.objects.create(profilo=Profilo.objects.create(nome="Chat", compito="chat"), modello=modello)
    with finto.con_copione([[("strumento", "previsione", {"vista": "core.lavoro", "data": "creato"})],
                            ["Il mese prossimo circa 7 lavori (tra 5 e 9)."]]):
        turno = motore.avvia(scena["conversazione"], "Quanti lavori nei prossimi mesi?", scena["capo"],
                             scena["azienda"])
    turno.refresh_from_db()
    assert not Evento.objects.get(tipo="strumento").dati["risultati"][0]["errore"]
    assert turno.provenienza["esito"] == "verificato"
    html = scena["client"].get(f"/ai/chat/{scena['conversazione'].pk}/").content.decode()
    assert "Fascia 10-90 %" in html
    a = Artifact.objects.get()
    assert a.spec["grafico"] == "previsione" and len(a.dati["storico"]) == 8 and len(a.dati["futuro"]) == 3
    csv = artifact.csv_di(a, a.dati)
    assert "Previsione mediana" in csv and csv.count("\n") == 12
    pagina = scena["client"].get(f"/ai/artifact/{a.pk}/").content.decode()
    assert "Mediana" in pagina and "finto-timestral" in pagina and "Totale (3 periodi)" in pagina


def test_lo_strumento_previsione_usa_il_motore_del_modulo(scena, servizi):
    """Lo strumento chiama il motore del modulo Previsioni: i suoi errori arrivano ad Ada come errori dello strumento."""
    r = ai_previsioni.previsione(_contesto(scena), "core.lavoro", "creato", per="mese", orizzonte=2)
    mese = motore_previsioni.etichetta(motore_previsioni.inizio(timezone.localdate(), "mese"), "mese")
    assert r["previsione"][0] == {"periodo": mese, "basso_10": 4.0, "mediana": 6.0, "alto_90": 8.0}
    assert r["totale_orizzonte"]["periodi"] == 2 and r["affidabilita"]["livello"] == "bassa"
    assert servizi[0][0] == "previsioni"
    with pytest.raises(strumenti.ErroreStrumento, match="non è un campo data"):
        ai_previsioni.previsione(_contesto(scena), "core.lavoro", "funzione")
    with pytest.raises(strumenti.ErroreStrumento, match="inesistente o non accessibile"):
        ai_previsioni.previsione(_contesto(scena), "core.nessuna", "creato")


def test_in_una_chat_limitata_a_un_app_si_prevede_solo_sulle_sue_viste(scena, servizi):
    """Come prima dello spostamento del motore: lo strumento e il ricalcolo dell'artifact vedono solo le viste della
    chat (ambito e viste sostituite per Ada), con lo stesso errore di vista_per."""
    from ai.strumenti.viste import vista_per
    scena["conversazione"].ambito = "todo"
    scena["conversazione"].save(update_fields=["ambito"])
    with pytest.raises(strumenti.ErroreStrumento) as atteso:
        vista_per(_contesto(scena), "core.lavoro")
    with pytest.raises(strumenti.ErroreStrumento) as e:
        ai_previsioni.previsione(_contesto(scena), "core.lavoro", "creato")
    assert str(e.value) == str(atteso.value)
    spec = {"tipo": Artifact.GRAFICO, "grafico": "previsione", "vista": "core.lavoro", "data": "creato", "misura": "count",
            "per": "mese", "orizzonte": 3}
    with pytest.raises(strumenti.ErroreStrumento) as e:
        artifact.calcola(spec, _contesto(scena))
    assert str(e.value) == str(atteso.value)
    assert not servizi


def _tre_gruppi(scena):
    """Tre «funzioni» con otto mesi di storia, in più dei lavori già nella scena."""
    oggi = timezone.localdate().replace(day=1)
    for i, quanti in enumerate([4, 3, 2]):
        for mesi_fa in range(1, 9):
            mese = motore_previsioni.avanti(oggi, "mese", -mesi_fa)
            for _ in range(quanti):
                lavoro = Lavoro.objects.create(funzione=f"prova.f{i}")
                Lavoro.objects.filter(pk=lavoro.pk).update(creato=timezone.make_aware(
                    datetime.datetime.combine(mese.replace(day=10), datetime.time(9))))


def test_ada_prevede_i_primi_prodotti_in_una_tabella(scena, servizi):
    _tre_gruppi(scena)
    r = ai_previsioni.previsione(_contesto(scena), "core.lavoro", "creato", per="mese", orizzonte=2,
                                 raggruppa="funzione", primi=3)
    a = Artifact.objects.get(pk=r["artifact"])
    assert a.tipo == Artifact.TABELLA
    assert a.spec["grafico"] == "previsione" and a.spec["raggruppa"] == "funzione" and a.spec["primi"] == 3
    assert len(a.dati["righe"]) == 3
    assert a.dati["colonne"][0] == "Gruppo" and a.dati["colonne"][-2:] == ["Totale previsto (10–90 %)", "Affidabilità"]
    assert [g["nome"] for g in r["gruppi"]][0] == a.dati["righe"][0][0]
    assert set(r["gruppi"][0]) == {"nome", "totale", "affidabilita"} and r["gruppi"][0]["totale"]["mediana"] is not None
    assert r["modello"] == "finto-timestral" and "non sommare" in r["nota"].lower()
    assert len([c for c in servizi if c[0] == "previsioni"]) == 1                      # una sola chiamata per tutti
    assert artifact.svg_di(a) == ""                                                    # una tabella non si disegna
    # il ricalcolo (↻) rifà la tabella
    assert artifact.calcola(a.spec, _contesto(scena))["colonne"] == a.dati["colonne"]


def test_senza_raggruppa_resta_il_grafico_di_prima(scena, servizi):
    r = ai_previsioni.previsione(_contesto(scena), "core.lavoro", "creato", per="mese", orizzonte=2)
    a = Artifact.objects.get(pk=r["artifact"])
    assert a.tipo == Artifact.GRAFICO and "raggruppa" not in a.spec and "primi" not in a.spec
    assert "previsione" in r and "gruppi" not in r


def test_primi_fuori_limite(scena, servizi):
    _tre_gruppi(scena)
    r = ai_previsioni.previsione(_contesto(scena), "core.lavoro", "creato", raggruppa="funzione", primi=80)
    assert Artifact.objects.get(pk=r["artifact"]).spec["primi"] == 50
    r = ai_previsioni.previsione(_contesto(scena), "core.lavoro", "creato", raggruppa="funzione", primi=-5)
    assert Artifact.objects.get(pk=r["artifact"]).spec["primi"] == 1
    with pytest.raises(strumenti.ErroreStrumento, match="«primi»"):
        ai_previsioni.previsione(_contesto(scena), "core.lavoro", "creato", raggruppa="funzione", primi="tanti")
