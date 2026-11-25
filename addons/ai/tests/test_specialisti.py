import datetime

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from ai import artifact, motore, specialisti, strumenti
from ai.gateway import finto
from ai.models import AnelloCatena, Artifact, Conversazione, Evento, Modello, Profilo, Provider
from ai.strumenti import specialisti as strumenti_specialisti
from core import parametri
from core.models import Azienda, Lavoro
from previsioni import motore as motore_previsioni
from previsioni import servizio as servizio_previsioni
from previsioni.tests.test_motore import _finta_risposta


@pytest.fixture
def servizi(monkeypatch):
    """Il decisore e il servizio di previsione finti: le chiamate in ordine, (chiave, percorso, dati)."""
    chiamate = []

    def chiama(chiave, percorso, dati, nome):
        chiamate.append((chiave, percorso, dati))
        return {"answers": {"d": {"type": "noul", "noul": 0.91, "backend": "embed_sim"}}}

    def prevedi(percorso, dati):
        chiamate.append(("previsioni", percorso, dati))
        return _finta_risposta(dati)
    monkeypatch.setattr(specialisti, "chiama", chiama)
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


def test_strumenti_solo_con_il_servizio_configurato(scena):
    nomi = {s.nome for s in strumenti.disponibili(scena["capo"])}
    assert "previsione" not in nomi and "classifica" not in nomi
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    nomi = {s.nome for s in strumenti.disponibili(scena["capo"])}
    assert "previsione" in nomi and "classifica" not in nomi


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
    r = strumenti_specialisti.previsione(_contesto(scena), "core.lavoro", "creato", per="mese", orizzonte=2)
    mese = motore_previsioni.etichetta(motore_previsioni.inizio(timezone.localdate(), "mese"), "mese")
    assert r["previsione"][0] == {"periodo": mese, "basso_10": 4.0, "mediana": 6.0, "alto_90": 8.0}
    assert r["totale_orizzonte"]["periodi"] == 2 and r["affidabilita"]["livello"] == "bassa"
    assert servizi[0][0] == "previsioni"
    with pytest.raises(strumenti.ErroreStrumento, match="non è un campo data"):
        strumenti_specialisti.previsione(_contesto(scena), "core.lavoro", "funzione")
    with pytest.raises(strumenti.ErroreStrumento, match="inesistente o non accessibile"):
        strumenti_specialisti.previsione(_contesto(scena), "core.nessuna", "creato")


def test_classifica(scena, servizi):
    r = strumenti_specialisti.classifica(_contesto(scena), "Il server è fermo", "È urgente?")
    assert r["noul"] == 0.91 and "indicative" in r["nota"]
    assert servizi[0][2]["questions"]["d"] == {"type": "noul", "instructions": "È urgente?"}
    with pytest.raises(strumenti.ErroreStrumento, match="opzioni"):
        strumenti_specialisti.classifica(_contesto(scena), "x", "y", tipo="scelta")


def test_filtro_con_data_su_campo_data_e_ora(scena, recwarn):
    from ai.strumenti import viste
    oggi = timezone.localdate()
    r = viste.aggrega_record(_contesto(scena), "core.lavoro", filtri={"creato__gte": oggi.replace(day=1).isoformat()})
    assert r["totale"] == 9 and not [w for w in recwarn if "naive datetime" in str(w.message)]


@pytest.mark.parametrize("modulo", ["ai.specialisti", "ai.pianificate", "ai.conoscenza", "ai.protezione",
                                    "ai.artifact", "ai.strumenti"])
def test_ogni_modulo_si_importa_per_primo(modulo):
    """Il worker e i comandi caricano i moduli in ordini diversi: nessun import circolare a seconda di chi parte."""
    import subprocess
    import sys

    from django.conf import settings
    esito = subprocess.run([sys.executable, "-c", f"import django; django.setup(); import {modulo}"],
                           cwd=settings.BASE_DIR, capture_output=True, text=True, timeout=120)
    assert esito.returncode == 0, esito.stderr[-1500:]


def test_l_affidabilita_va_sotto_la_risposta():
    import json
    from django.template.loader import render_to_string
    from ai import provenienza
    contenuto = json.dumps({"titolo": "Previsione fatturato", "modello": "Timestral",
                            "affidabilita": {"livello": "bassa", "motivi": ["Storia: 10 mesi"]}})
    p = provenienza._affidabilita(contenuto)
    assert p == {"titolo": "Previsione fatturato", "livello": "bassa", "motivi": ["Storia: 10 mesi"], "modello": "Timestral"}
    assert provenienza._affidabilita("non è json") is None
    html = render_to_string("ai/_provenienza.html", {"pv": {"esito": "verificato", "fonti": [], "previsioni": [p]}})
    assert "Affidabilità: bassa" in html and "is-avviso" in html and "Storia: 10 mesi" in html
